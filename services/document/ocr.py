"""OCR service for document pipeline.

This module provides lazy PaddleOCR loading and structured OCR output for
single or multiple images.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrConfig:
    confidence_threshold: float = 0.45
    max_image_side: int = 2000
    max_workers: int = 2


class OcrProcessor:
    """PaddleOCR-backed extraction with confidence-aware outputs."""

    _ocr_instance: Any = None
    _ocr_init_error: str | None = None
    _init_lock = threading.Lock()

    def __init__(self, config: OcrConfig | None = None) -> None:
        self._config = config or OcrConfig()

    def extract_image_file(self, image_path: str) -> dict[str, Any]:
        """Run OCR for a local image path and return structured output."""
        if not os.path.isfile(image_path):
            return {
                "text": "",
                "confidence": 0.0,
                "warning": "OCR skipped because image file is missing.",
                "error": f"file_not_found:{image_path}",
            }

        try:
            ocr = self._get_ocr()
            results = self._run_ocr(ocr, image_path)
            text_lines, confidences = self._extract_lines_and_confidence(results)
            confidence = self._average(confidences)
            text = "\n".join(text_lines).strip()

            warning = ""
            if not text:
                warning = "OCR produced empty text."
            elif confidence < self._config.confidence_threshold:
                warning = (
                    "OCR confidence is below threshold; text may be noisy. "
                    f"confidence={confidence:.3f}, threshold={self._config.confidence_threshold:.3f}"
                )

            return {
                "text": text,
                "confidence": confidence,
                "warning": warning,
                "error": "",
            }
        except ImportError as exc:
            return {
                "text": "",
                "confidence": 0.0,
                "warning": "PaddleOCR is not installed. OCR was skipped.",
                "error": str(exc),
            }
        except Exception as exc:
            logger.warning("OCR extraction failed for %s: %s", image_path, exc)
            return {
                "text": "",
                "confidence": 0.0,
                "warning": "OCR processing failed and was safely skipped.",
                "error": str(exc),
            }

    def extract_image_bytes(
        self,
        image_bytes: bytes,
        *,
        suffix: str = ".png",
    ) -> dict[str, Any]:
        """Run OCR on image bytes by writing to a temporary file."""
        if not image_bytes:
            return {
                "text": "",
                "confidence": 0.0,
                "warning": "OCR skipped because no image bytes were provided.",
                "error": "empty_image_bytes",
            }

        fd, temp_path = tempfile.mkstemp(prefix="jarvis_ocr_bytes_", suffix=suffix)
        os.close(fd)
        try:
            with open(temp_path, "wb") as f:
                f.write(image_bytes)
            return self.extract_image_file(temp_path)
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def extract_images(self, images: list[dict[str, Any]]) -> dict[str, Any]:
        """Run OCR on multiple image payloads and aggregate output."""
        if not images:
            return {
                "text": "",
                "confidence": 0.0,
                "warning": "",
                "error": "",
                "per_image": [],
            }

        results: list[dict[str, Any] | None] = [None] * len(images)
        worker_count = max(1, min(self._config.max_workers, len(images)))

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_idx = {
                executor.submit(self._extract_single_payload, payload): idx
                for idx, payload in enumerate(images)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    results[idx] = {
                        "text": "",
                        "confidence": 0.0,
                        "warning": "OCR failed for one image payload.",
                        "error": str(exc),
                        "source": str(images[idx].get("source") or f"image_{idx + 1}"),
                    }

        per_image = [item for item in results if isinstance(item, dict)]
        texts = [str(item.get("text") or "").strip() for item in per_image]
        merged_text = "\n".join(part for part in texts if part).strip()
        confidence_values = [float(item.get("confidence") or 0.0) for item in per_image]
        avg_confidence = self._average(confidence_values)

        warnings = [str(item.get("warning") or "").strip() for item in per_image if str(item.get("warning") or "").strip()]
        errors = [str(item.get("error") or "").strip() for item in per_image if str(item.get("error") or "").strip()]

        warning = " | ".join(warnings[:3]).strip()
        error = " | ".join(errors[:2]).strip()
        if avg_confidence < self._config.confidence_threshold and merged_text:
            low_conf_warning = (
                "Aggregate OCR confidence is below threshold; extracted text may require verification. "
                f"confidence={avg_confidence:.3f}, threshold={self._config.confidence_threshold:.3f}"
            )
            warning = f"{warning} | {low_conf_warning}".strip(" |")

        return {
            "text": merged_text,
            "confidence": avg_confidence,
            "warning": warning,
            "error": error,
            "per_image": per_image,
        }

    def _extract_single_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = str(payload.get("source") or "image")
        image_bytes = payload.get("bytes")
        if not isinstance(image_bytes, (bytes, bytearray)):
            return {
                "text": "",
                "confidence": 0.0,
                "warning": "OCR payload missing image bytes.",
                "error": "invalid_image_payload",
                "source": source,
            }

        suffix = self._suffix_from_mime(str(payload.get("mime_type") or "image/png"))
        result = self.extract_image_bytes(bytes(image_bytes), suffix=suffix)
        result["source"] = source
        return result

    @staticmethod
    def _suffix_from_mime(mime_type: str) -> str:
        normalized = mime_type.lower().strip()
        if normalized == "image/jpeg":
            return ".jpg"
        if normalized == "image/webp":
            return ".webp"
        if normalized == "image/bmp":
            return ".bmp"
        if normalized in {"image/tif", "image/tiff"}:
            return ".tiff"
        return ".png"

    @staticmethod
    def _average(values: list[float]) -> float:
        filtered = [max(0.0, min(1.0, float(value))) for value in values if value is not None]
        if not filtered:
            return 0.0
        return sum(filtered) / len(filtered)

    def _get_ocr(self) -> Any:
        if OcrProcessor._ocr_instance is not None:
            return OcrProcessor._ocr_instance

        if OcrProcessor._ocr_init_error:
            raise RuntimeError(OcrProcessor._ocr_init_error)

        with OcrProcessor._init_lock:
            if OcrProcessor._ocr_instance is not None:
                return OcrProcessor._ocr_instance
            if OcrProcessor._ocr_init_error:
                raise RuntimeError(OcrProcessor._ocr_init_error)

            try:
                os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
                from paddleocr import PaddleOCR

                init_variants = (
                    {
                        "enable_mkldnn": False,
                        "lang": "en",
                        "ocr_version": "PP-OCRv5",
                        "use_doc_orientation_classify": False,
                        "use_doc_unwarping": False,
                        "use_textline_orientation": False,
                        "text_detection_model_name": "PP-OCRv5_mobile_det",
                        "text_recognition_model_name": "en_PP-OCRv5_mobile_rec",
                        "text_det_limit_side_len": int(self._config.max_image_side),
                    },
                    {
                        "enable_mkldnn": False,
                        "lang": "en",
                        "use_doc_orientation_classify": False,
                        "use_doc_unwarping": False,
                        "use_textline_orientation": False,
                        "text_det_limit_side_len": int(self._config.max_image_side),
                    },
                    {
                        "enable_mkldnn": False,
                        "lang": "en",
                    },
                    {},
                )

                last_error: Exception | None = None
                for kwargs in init_variants:
                    try:
                        OcrProcessor._ocr_instance = PaddleOCR(**kwargs)
                        return OcrProcessor._ocr_instance
                    except (TypeError, ValueError) as exc:
                        last_error = exc
                        continue

                raise RuntimeError(
                    f"PaddleOCR initialization failed for compatibility variants: {last_error}"
                )
            except ImportError:
                OcrProcessor._ocr_init_error = (
                    "PaddleOCR is not installed. Install with: pip install paddleocr paddlepaddle"
                )
                raise
            except Exception as exc:
                OcrProcessor._ocr_init_error = (
                    "PaddleOCR initialization failed. "
                    f"Original error: {exc}"
                )
                raise

    @staticmethod
    def _run_ocr(ocr: Any, image_path: str) -> Any:
        attempts = (
            lambda: ocr.ocr(image_path, cls=False),
            lambda: ocr.ocr(image_path),
            lambda: ocr.predict(image_path),
        )

        last_error: Exception | None = None
        for fn in attempts:
            try:
                return fn()
            except TypeError as exc:
                last_error = exc
                continue

        raise RuntimeError(f"OCR invocation failed across compatibility calls: {last_error}")

    @staticmethod
    def _extract_lines_and_confidence(results: Any) -> tuple[list[str], list[float]]:
        lines: list[str] = []
        confidences: list[float] = []

        def push(text: Any, score: Any = None) -> None:
            normalized = str(text or "").strip()
            if not normalized:
                return
            lines.append(normalized)
            try:
                if score is not None:
                    value = float(score)
                    confidences.append(max(0.0, min(1.0, value)))
            except Exception:
                pass

        def walk(node: Any) -> None:
            if node is None:
                return

            if isinstance(node, dict):
                rec_texts = node.get("rec_texts")
                rec_scores = node.get("rec_scores")
                if isinstance(rec_texts, (list, tuple)):
                    if isinstance(rec_scores, (list, tuple)):
                        for idx, text in enumerate(rec_texts):
                            score = rec_scores[idx] if idx < len(rec_scores) else None
                            push(text, score)
                    else:
                        for text in rec_texts:
                            push(text)

                if "rec_text" in node:
                    push(node.get("rec_text"), node.get("score") or node.get("rec_score"))

                for value in node.values():
                    walk(value)
                return

            if isinstance(node, (list, tuple)):
                if len(node) == 2 and isinstance(node[0], str):
                    push(node[0], node[1])
                elif len(node) >= 2 and isinstance(node[1], (list, tuple)) and node[1]:
                    if isinstance(node[1][0], str):
                        score = node[1][1] if len(node[1]) > 1 else None
                        push(node[1][0], score)

                for item in node:
                    walk(item)
                return

            if hasattr(node, "to_dict"):
                try:
                    walk(node.to_dict())
                    return
                except Exception:
                    pass

            if hasattr(node, "__dict__"):
                try:
                    walk(vars(node))
                except Exception:
                    pass

        walk(results)

        deduped_lines: list[str] = []
        deduped_scores: list[float] = []
        seen: set[str] = set()
        for idx, line in enumerate(lines):
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped_lines.append(line)
            if idx < len(confidences):
                deduped_scores.append(confidences[idx])

        return deduped_lines, deduped_scores
