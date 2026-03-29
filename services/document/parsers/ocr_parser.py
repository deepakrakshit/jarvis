"""OCR parser using PaddleOCR for images and scanned PDFs.

PaddleOCR is treated as an optional dependency — if not installed,
the parser returns a clear error without crashing the pipeline.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any

from services.document.models import PageContent, RawExtractionResult, TableData
from services.document.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read integer env values with bounds and safe fallback."""
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _is_paddleocr_available() -> bool:
    """Check if PaddleOCR is installed."""
    try:
        from paddleocr import PaddleOCR  # noqa: F401

        return True
    except ImportError:
        return False


class OcrParser(BaseParser):
    """OCR-based parser for images and scanned documents.

    Uses PaddleOCR for text extraction with bounding boxes.
    Falls back gracefully when PaddleOCR is not installed.
    """

    _ocr_instance: Any = None
    _ocr_runtime_error: str | None = None

    @staticmethod
    def _max_image_side() -> int:
        return _int_env("DOCUMENT_OCR_MAX_IMAGE_SIDE", 2000, 1200, 5000)

    @staticmethod
    def _pdf_base_dpi() -> int:
        return _int_env("DOCUMENT_OCR_PDF_DPI", 180, 96, 400)

    @staticmethod
    def _pdf_min_dpi() -> int:
        return _int_env("DOCUMENT_OCR_PDF_MIN_DPI", 48, 36, 300)

    @staticmethod
    def _pdf_max_side() -> int:
        return _int_env("DOCUMENT_OCR_PDF_MAX_SIDE", 2000, 1200, 5000)

    def _prepare_image_for_ocr(self, file_path: str) -> tuple[str, str | None]:
        """Downscale very large images to reduce OCR latency."""
        max_side = self._max_image_side()
        try:
            from PIL import Image
        except Exception:
            return file_path, None

        try:
            with Image.open(file_path) as image:
                width, height = image.size
                largest = max(width, height)
                if largest <= max_side:
                    return file_path, None

                scale = max_side / float(largest)
                resized_w = max(1, int(width * scale))
                resized_h = max(1, int(height * scale))

                resampling = getattr(Image, "Resampling", Image).LANCZOS
                resized = image.convert("RGB").resize((resized_w, resized_h), resampling)

                fd, temp_path = tempfile.mkstemp(prefix="jarvis_ocr_scaled_", suffix=".png")
                os.close(fd)
                resized.save(temp_path, format="PNG", optimize=True)
                return temp_path, temp_path
        except Exception:
            return file_path, None

    def _get_ocr(self) -> Any:
        """Lazy-initialize PaddleOCR (heavy import, singleton pattern)."""
        if OcrParser._ocr_instance is not None:
            return OcrParser._ocr_instance

        if OcrParser._ocr_runtime_error:
            raise RuntimeError(OcrParser._ocr_runtime_error)

        try:
            # Prevent PaddleX model-host probing from blocking document analysis.
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

            from paddleocr import PaddleOCR

            # PaddleOCR changed constructor args across releases.
            # Try progressively minimal argument sets for compatibility.
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
                    "text_det_limit_side_len": self._max_image_side(),
                },
                {
                    "enable_mkldnn": False,
                    "lang": "en",
                    "ocr_version": "PP-OCRv5",
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                    "text_det_limit_side_len": self._max_image_side(),
                },
                {
                    "enable_mkldnn": False,
                    "use_angle_cls": False,
                    "lang": "en",
                    "use_gpu": False,
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                    "text_det_limit_side_len": self._max_image_side(),
                },
                {
                    "enable_mkldnn": False,
                    "lang": "en",
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                    "text_det_limit_side_len": self._max_image_side(),
                },
                {
                    "enable_mkldnn": False,
                    "lang": "en",
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                    "text_det_limit_side_len": self._max_image_side(),
                },
                {
                    "enable_mkldnn": False,
                    "lang": "en",
                },
                {},
            )

            last_init_error: Exception | None = None
            for kwargs in init_variants:
                try:
                    OcrParser._ocr_instance = PaddleOCR(**kwargs)
                    return OcrParser._ocr_instance
                except (TypeError, ValueError) as exc:
                    last_init_error = exc
                    continue

            raise RuntimeError(
                f"PaddleOCR initialization failed for all compatibility variants: {last_init_error}"
            )
        except ImportError:
            raise ImportError(
                "PaddleOCR is not installed. "
                "Install with: pip install paddleocr paddlepaddle"
            )
        except Exception as exc:
            raise RuntimeError(
                "PaddleOCR initialization failed. "
                "If model host checks are slow on your network, keep "
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True. "
                f"Original error: {exc}"
            ) from exc

    @staticmethod
    def _extract_text_lines(results: Any) -> list[str]:
        """Extract recognized text from multiple PaddleOCR output formats."""
        lines: list[str] = []

        def push(text: Any) -> None:
            value = str(text or "").strip()
            if value:
                lines.append(value)

        def walk(node: Any) -> None:
            if node is None:
                return

            if isinstance(node, dict):
                rec_texts = node.get("rec_texts")
                if isinstance(rec_texts, (list, tuple)):
                    for text in rec_texts:
                        push(text)

                if "rec_text" in node:
                    push(node.get("rec_text"))

                for value in node.values():
                    walk(value)
                return

            if isinstance(node, (list, tuple)):
                if len(node) >= 2 and isinstance(node[1], (list, tuple)) and node[1]:
                    # Legacy format: [box, (text, score)]
                    if isinstance(node[1][0], str):
                        push(node[1][0])

                if len(node) == 2 and isinstance(node[0], str) and isinstance(node[1], (int, float)):
                    # Legacy tuple format: (text, score)
                    push(node[0])

                for item in node:
                    walk(item)
                return

            if hasattr(node, "rec_texts"):
                walk(getattr(node, "rec_texts"))
            if hasattr(node, "rec_text"):
                push(getattr(node, "rec_text"))

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

        # Deduplicate while preserving order.
        unique_lines: list[str] = []
        seen: set[str] = set()
        for line in lines:
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_lines.append(line)

        return unique_lines

    def _run_ocr(self, ocr: Any, input_path: str) -> Any:
        """Run OCR across PaddleOCR API versions with fast compatibility fallbacks."""
        attempts = (
            ("ocr(cls=False)", lambda: ocr.ocr(input_path, cls=False)),
            ("ocr()", lambda: ocr.ocr(input_path)),
            ("predict()", lambda: ocr.predict(input_path)),
        )

        last_error: Exception | None = None
        for _, fn in attempts:
            try:
                return fn()
            except TypeError as exc:
                last_error = exc
                continue
            except NotImplementedError as exc:
                OcrParser._ocr_runtime_error = (
                    "OCR runtime backend is not supported by the installed Paddle stack. "
                    "The parser now fails fast to avoid repeated long stalls. "
                    "Try reinstalling compatible versions of paddlepaddle and paddleocr, "
                    "or run with enable_mkldnn=False. "
                    f"Original error: {exc}"
                )
                raise RuntimeError(OcrParser._ocr_runtime_error) from exc

        if last_error is not None:
            raise RuntimeError(
                "PaddleOCR API compatibility failure while invoking OCR. "
                f"Last error: {last_error}"
            ) from last_error

        raise RuntimeError("PaddleOCR invocation failed for unknown reasons.")

    def parse(self, file_path: str) -> RawExtractionResult:
        """Parse a single image file via OCR."""
        try:
            return self._parse_image(file_path)
        except ImportError as exc:
            return RawExtractionResult(
                text="",
                pages=[],
                tables=[],
                metadata={"file_path": file_path},
                source_type="image",
                file_path=file_path,
                error=str(exc),
            )
        except Exception as exc:
            logger.exception("OCR parsing failed for %s", file_path)
            return RawExtractionResult(
                text="",
                pages=[],
                tables=[],
                metadata={"file_path": file_path},
                source_type="image",
                file_path=file_path,
                error=f"OCR parsing failed: {exc}",
            )

    def _parse_image(self, file_path: str) -> RawExtractionResult:
        """Extract text from a single image using PaddleOCR."""
        ocr = self._get_ocr()
        input_path, temp_input = self._prepare_image_for_ocr(file_path)
        start = time.perf_counter()
        try:
            results = self._run_ocr(ocr, input_path)
        finally:
            if temp_input:
                try:
                    os.remove(temp_input)
                except OSError:
                    pass
        text_lines = self._extract_text_lines(results)
        elapsed = round(time.perf_counter() - start, 3)

        combined_text = "\n".join(text_lines)
        pages = [
            PageContent(
                page_number=1,
                text=combined_text,
                has_images=True,
            )
        ]

        return RawExtractionResult(
            text=combined_text,
            pages=pages,
            tables=[],
            metadata={
                "file_path": file_path,
                "ocr_applied": True,
                "line_count": len(text_lines),
                "ocr_elapsed_seconds": elapsed,
            },
            source_type="image",
            file_path=file_path,
        )

    def parse_pdf_as_images(self, file_path: str) -> RawExtractionResult:
        """Convert PDF pages to images and OCR each one.

        Used as fallback for scanned PDFs detected by PdfParser.
        """
        try:
            import fitz  # PyMuPDF for rendering PDF pages to images
        except ImportError:
            return RawExtractionResult(
                text="",
                pages=[],
                tables=[],
                metadata={"file_path": file_path},
                source_type="scanned_pdf",
                file_path=file_path,
                error="PyMuPDF required for scanned PDF rendering",
            )

        ocr = self._get_ocr()
        pages: list[PageContent] = []
        all_text_parts: list[str] = []
        total_ocr_seconds = 0.0

        doc = fitz.open(file_path)
        temp_dir = tempfile.mkdtemp(prefix="jarvis_ocr_")

        try:
            for page_num in range(len(doc)):
                page = doc[page_num]
                # Render page at adaptive DPI to reduce OCR latency on large pages.
                base_dpi = self._pdf_base_dpi()
                min_dpi = self._pdf_min_dpi()
                max_side = self._pdf_max_side()
                page_max_points = max(float(page.rect.width), float(page.rect.height), 1.0)

                dpi = base_dpi
                estimated_max_side = page_max_points * base_dpi / 72.0
                if estimated_max_side > max_side:
                    scaled_dpi = int((max_side * 72.0) / page_max_points)
                    dpi = max(min_dpi, min(base_dpi, scaled_dpi))

                pix = page.get_pixmap(dpi=dpi, alpha=False)
                img_path = os.path.join(temp_dir, f"page_{page_num + 1}.png")
                pix.save(img_path)

                # Downscale oversized rendered pages before OCR to reduce latency.
                input_path, temp_input = self._prepare_image_for_ocr(img_path)
                start = time.perf_counter()
                try:
                    results = self._run_ocr(ocr, input_path)
                finally:
                    if temp_input:
                        try:
                            os.remove(temp_input)
                        except OSError:
                            pass
                total_ocr_seconds += time.perf_counter() - start
                text_lines = self._extract_text_lines(results)

                page_text = "\n".join(text_lines)
                pages.append(
                    PageContent(
                        page_number=page_num + 1,
                        text=page_text,
                        has_images=True,
                    )
                )
                if page_text:
                    all_text_parts.append(page_text)

                # Clean up temp image
                try:
                    os.remove(img_path)
                except OSError:
                    pass

        finally:
            doc.close()
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass

        combined_text = "\n\n".join(all_text_parts)

        return RawExtractionResult(
            text=combined_text,
            pages=pages,
            tables=[],
            metadata={
                "file_path": file_path,
                "ocr_applied": True,
                "page_count": len(pages),
                "ocr_elapsed_seconds": round(total_ocr_seconds, 3),
            },
            source_type="scanned_pdf",
            file_path=file_path,
        )
