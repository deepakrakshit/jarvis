"""Hybrid Document Intelligence Pipeline.

Flow:
- Detect file type
- Route image files directly through vision extraction
- Route PDF/DOCX to parser, then run OCR and vision in parallel when needed
- Fuse all modalities into a single structured object
- Send fused object to Groq for final reasoning
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.settings import AppConfig
from services.document.llm_client import DocumentLLMClient
from services.document.models import (
    DocumentIntelligence,
    DocumentStructure,
    PipelineProgress,
    RawExtractionResult,
    Section,
)
from services.document.ocr import OcrConfig, OcrProcessor
from services.document.parsers.docx_parser import DocxParser
from services.document.parsers.pdf_parser import PdfParser
from services.document.processors.chunker import SemanticChunker
from services.document.processors.cleaner import DocumentCleaner
from services.document.processors.fusion import FusionProcessor
from services.document.vision import VisionConfig, VisionProcessor

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

_FINAL_REASONING_SYSTEM_PROMPT = """You are a production document intelligence synthesizer.
You will receive one fused structured object with keys:
- text_content
- ocr_content
- vision_data
- metadata

Instructions:
- Use only the provided structured data.
- Merge signals across text, OCR, and vision; resolve overlaps conservatively.
- Do not hallucinate missing facts.
- Return strict JSON only with this exact schema:
{
  "summary": "...",
  "insights": ["..."],
  "key_points": ["..."],
  "metrics": [{"name": "...", "value": "...", "context": "..."}],
  "risks": ["..."]
}
"""


class DocumentPipeline:
    """Hybrid pipeline that fuses parser, OCR, and vision outputs."""

    def __init__(self, llm_client: DocumentLLMClient, config: AppConfig) -> None:
        self._llm = llm_client
        self._cleaner = DocumentCleaner(llm_client)
        self._chunker = SemanticChunker(max_tokens=1800, overlap_tokens=120)
        self._fusion = FusionProcessor()

        vision_config = VisionConfig(
            api_key=config.openrouter_api_key,
            api_url=config.openrouter_base_url,
            primary_model=config.document_vision_primary_model,
            fallback_models=config.document_vision_fallback_models,
            timeout_seconds=float(config.document_vision_timeout_seconds),
            max_retries_per_model=int(config.document_vision_max_retries_per_model),
            retry_backoff_seconds=float(config.document_vision_retry_backoff_seconds),
            fast_fail_on_429=bool(config.document_vision_fast_fail_on_429),
        )
        self._vision = VisionProcessor(vision_config)

        max_image_side = int(os.getenv("DOCUMENT_OCR_MAX_IMAGE_SIDE", "2000"))
        self._ocr_confidence_threshold = float(config.document_ocr_confidence_threshold)
        ocr_config = OcrConfig(
            confidence_threshold=self._ocr_confidence_threshold,
            max_image_side=max_image_side,
            max_workers=2,
        )
        self._ocr = OcrProcessor(ocr_config)

        self._pdf_parser = PdfParser()
        self._docx_parser = DocxParser()

    def process(
        self,
        file_path: str,
        *,
        progress: PipelineProgress | None = None,
    ) -> DocumentIntelligence:
        prog = progress or PipelineProgress()
        started = time.time()

        try:
            ext = Path(file_path).suffix.lower().strip()
            if ext in _IMAGE_EXTENSIONS:
                return self._process_image(file_path, prog)

            if ext in {".pdf", ".docx", ".doc"}:
                return self._process_document(file_path, prog)

            return self._error_intelligence(
                f"Unsupported document type: {ext or 'unknown'}",
                file_path,
            )
        except Exception as exc:
            logger.exception("Hybrid pipeline failed for %s", file_path)
            prog.error = str(exc)
            return self._error_intelligence(f"Pipeline error: {exc}", file_path)
        finally:
            elapsed = time.time() - started
            logger.info("Document pipeline completed in %.2fs for %s", elapsed, file_path)

    def _process_image(self, file_path: str, progress: PipelineProgress) -> DocumentIntelligence:
        progress.advance("parsing", "Running direct vision image extraction")
        image_name = Path(file_path).name
        vision_result: dict[str, Any] = {
            "visible_text": "",
            "layout": "",
            "categories": [],
            "key_elements": [],
            "tables": [],
            "summary": "",
            "warning": "",
            "error": "",
            "source": image_name,
            "model": "",
            "attempted_models": [],
        }

        try:
            candidate = self._vision.analyze_image_file(file_path, source=image_name)
            if isinstance(candidate, dict):
                vision_result = candidate
        except Exception as exc:
            logger.warning("Image vision task failed: %s", exc)

        metadata = {
            "file_path": file_path,
            "source_type": "image",
            "vision_model": vision_result.get("model") or "",
            "vision_attempted_models": vision_result.get("attempted_models") or [],
            "vision_warning": vision_result.get("warning") or "",
            "vision_error": vision_result.get("error") or "",
            "vision_skipped": False,
            "ocr_applied": False,
            "ocr_confidence": 0.0,
            "ocr_warning": "",
            "ocr_error": "",
        }

        cleaned_ocr_text = ""

        progress.advance("merging", "Fusing vision output")
        fused = self._fusion.fuse(
            text_content="",
            ocr_content="",
            vision_data=[vision_result],
            metadata=metadata,
        )

        vision_bundle = fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {}
        has_vision_signal = self._has_vision_signal(vision_bundle)

        if not has_vision_signal:
            progress.advance("processing_chunks", "Vision unavailable; running OCR fallback on image")
            fallback_ocr = self._ocr.extract_image_file(file_path)
            cleaned_ocr_text = self._cleaner.clean_ocr_text(str(fallback_ocr.get("text") or ""))
            metadata["ocr_applied"] = True
            metadata["ocr_confidence"] = float(fallback_ocr.get("confidence") or 0.0)
            metadata["ocr_warning"] = str(fallback_ocr.get("warning") or "")
            metadata["ocr_error"] = str(fallback_ocr.get("error") or "")

            if cleaned_ocr_text:
                progress.advance("merging", "Fusing OCR fallback with vision output")
                fused = self._fusion.fuse(
                    text_content="",
                    ocr_content=cleaned_ocr_text,
                    vision_data=[vision_result],
                    metadata=metadata,
                )
                vision_bundle = fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {}
                has_vision_signal = self._has_vision_signal(vision_bundle)

        if not has_vision_signal and not cleaned_ocr_text:
            detail_parts: list[str] = []
            vision_error = str(metadata.get("vision_error") or "").strip()
            ocr_error = str(metadata.get("ocr_error") or "").strip()
            if vision_error:
                detail_parts.append(f"vision={vision_error}")
            if ocr_error:
                detail_parts.append(f"ocr={ocr_error}")
            detail = f": {'; '.join(detail_parts)}" if detail_parts else ""
            return self._error_intelligence(
                f"Image content extraction failed{detail}",
                file_path,
            )

        progress.advance("intelligence", "Generating final reasoning from fused data")
        return self._reason_over_fused_data(
            fused=fused,
            tables=[],
            prefer_fast_model=True,
        )

    def _process_document(self, file_path: str, progress: PipelineProgress) -> DocumentIntelligence:
        progress.advance("parsing", "Extracting document text and media")
        extraction = self._parse_document(file_path)
        if extraction.error:
            return self._error_intelligence(f"Parsing failed: {extraction.error}", file_path)

        text_content = self._cleaner.clean_extracted_text(extraction.text)
        raw_metadata = dict(extraction.metadata or {})
        vision_inputs = self._coerce_image_payloads(raw_metadata.get("vision_images"))
        ocr_inputs = self._coerce_image_payloads(raw_metadata.get("ocr_images"))

        should_run_ocr = bool(ocr_inputs) and bool(raw_metadata.get("is_scanned"))
        should_run_vision = bool(vision_inputs)
        ocr_applied = should_run_ocr

        ocr_result: dict[str, Any] = {
            "text": "",
            "confidence": 0.0,
            "warning": "",
            "error": "",
            "per_image": [],
        }
        vision_results: list[dict[str, Any]] = []

        progress.advance("processing_chunks", "Running OCR and vision tasks")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures: dict[Any, str] = {}
            if should_run_ocr:
                futures[executor.submit(self._ocr.extract_images, ocr_inputs)] = "ocr"
            if should_run_vision:
                futures[executor.submit(self._vision.analyze_images, vision_inputs, max_workers=3)] = "vision"

            for future in as_completed(futures):
                task_name = futures[future]
                try:
                    if task_name == "ocr":
                        value = future.result()
                        if isinstance(value, dict):
                            ocr_result = value
                    elif task_name == "vision":
                        value = future.result()
                        if isinstance(value, list):
                            vision_results = [item for item in value if isinstance(item, dict)]
                except Exception as exc:
                    logger.warning("Parallel %s task failed: %s", task_name, exc)

        cleaned_ocr_text = self._cleaner.clean_ocr_text(str(ocr_result.get("text") or ""))

        if should_run_vision and not cleaned_ocr_text and not self._vision_results_have_signal(vision_results):
            progress.advance("processing_chunks", "Vision unavailable; running OCR fallback on embedded images")
            ocr_applied = True
            fallback_ocr = self._ocr.extract_images(vision_inputs)
            cleaned_fallback = self._cleaner.clean_ocr_text(str(fallback_ocr.get("text") or ""))
            if cleaned_fallback:
                cleaned_ocr_text = cleaned_fallback
            ocr_result = self._merge_ocr_payloads(ocr_result, fallback_ocr)

        sanitized_metadata = self._sanitize_metadata(raw_metadata)
        sanitized_metadata.update(
            {
                "file_path": file_path,
                "source_type": extraction.source_type,
                "ocr_applied": ocr_applied,
                "vision_applied": should_run_vision,
                "ocr_confidence": float(ocr_result.get("confidence") or 0.0),
                "ocr_warning": str(ocr_result.get("warning") or ""),
                "ocr_error": str(ocr_result.get("error") or ""),
                "vision_item_count": len(vision_results),
                "table_count": len(extraction.tables),
            }
        )

        progress.advance("merging", "Fusing text, OCR, and vision outputs")
        fused = self._fusion.fuse(
            text_content=text_content,
            ocr_content=cleaned_ocr_text,
            vision_data=vision_results,
            metadata=sanitized_metadata,
        )

        vision_bundle = fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {}
        has_vision_signal = self._has_vision_signal(vision_bundle)

        if not fused.get("text_content") and not fused.get("ocr_content") and not has_vision_signal:
            return self._error_intelligence("No usable content extracted from document", file_path)

        tables = [table.to_dict() for table in extraction.tables]

        progress.advance("intelligence", "Generating final reasoning from fused data")
        return self._reason_over_fused_data(fused=fused, tables=tables)

    def _parse_document(self, file_path: str) -> RawExtractionResult:
        ext = Path(file_path).suffix.lower().strip()
        if ext == ".pdf":
            return self._pdf_parser.parse(file_path)

        if ext == ".doc":
            return RawExtractionResult(
                text="",
                pages=[],
                tables=[],
                metadata={"file_path": file_path},
                source_type="doc",
                file_path=file_path,
                error="Legacy .doc files are not directly supported. Please save as .docx and retry.",
            )

        return self._docx_parser.parse(file_path)

    @staticmethod
    def _coerce_image_payloads(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        payloads: list[dict[str, Any]] = []
        for idx, item in enumerate(value):
            if not isinstance(item, dict):
                continue

            image_bytes = item.get("bytes")
            if not isinstance(image_bytes, (bytes, bytearray)):
                continue

            payloads.append(
                {
                    "source": str(item.get("source") or f"image_{idx + 1}"),
                    "mime_type": str(item.get("mime_type") or "image/png"),
                    "bytes": bytes(image_bytes),
                }
            )

            if len(payloads) >= 16:
                break

        return payloads

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(metadata)
        sanitized.pop("vision_images", None)
        sanitized.pop("ocr_images", None)
        return sanitized

    @staticmethod
    def _vision_results_have_signal(vision_results: list[dict[str, Any]]) -> bool:
        for item in vision_results:
            if not isinstance(item, dict):
                continue
            if str(item.get("visible_text") or "").strip():
                return True
            if str(item.get("layout") or "").strip():
                return True
            if str(item.get("summary") or "").strip():
                return True
            if item.get("categories"):
                return True
            if item.get("key_elements"):
                return True
            if item.get("tables"):
                return True
        return False

    @staticmethod
    def _merge_notes(*parts: Any) -> str:
        notes: list[str] = []
        seen: set[str] = set()
        for part in parts:
            text = str(part or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            notes.append(text)
        return " | ".join(notes)

    @classmethod
    def _merge_ocr_payloads(
        cls,
        primary: dict[str, Any],
        secondary: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(primary or {})
        if not isinstance(secondary, dict):
            return merged

        primary_text = str(merged.get("text") or "").strip()
        secondary_text = str(secondary.get("text") or "").strip()
        if not primary_text and secondary_text:
            merged["text"] = secondary_text
            merged["confidence"] = float(secondary.get("confidence") or 0.0)
        elif primary_text:
            merged["confidence"] = float(merged.get("confidence") or 0.0)

        merged["warning"] = cls._merge_notes(merged.get("warning"), secondary.get("warning"))
        merged["error"] = cls._merge_notes(merged.get("error"), secondary.get("error"))

        existing_per_image = merged.get("per_image") if isinstance(merged.get("per_image"), list) else []
        secondary_per_image = secondary.get("per_image") if isinstance(secondary.get("per_image"), list) else []
        merged["per_image"] = [*existing_per_image, *secondary_per_image]
        return merged

    @staticmethod
    def _has_vision_signal(vision_bundle: dict[str, Any]) -> bool:
        if str(vision_bundle.get("visible_text") or "").strip():
            return True
        if str(vision_bundle.get("layout") or "").strip():
            return True
        if str(vision_bundle.get("summary") or "").strip():
            return True
        if vision_bundle.get("categories"):
            return True
        if vision_bundle.get("key_elements"):
            return True
        if vision_bundle.get("tables"):
            return True

        items = vision_bundle.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("visible_text") or "").strip():
                    return True
                if str(item.get("layout") or "").strip():
                    return True
                if str(item.get("summary") or "").strip():
                    return True
                if item.get("categories"):
                    return True
                if item.get("key_elements"):
                    return True
                if item.get("tables"):
                    return True

        return False

    def _reason_over_fused_data(
        self,
        *,
        fused: dict[str, Any],
        tables: list[dict[str, Any]],
        prefer_fast_model: bool = False,
    ) -> DocumentIntelligence:
        prompt_payload = self._build_reasoning_payload(fused)
        user_prompt = (
            "Here is structured document data: "
            f"{json.dumps(prompt_payload, ensure_ascii=True)}. "
            "Generate a clean final answer."
        )

        if prefer_fast_model:
            result = self._llm.extract_json_fast(
                system_prompt=_FINAL_REASONING_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.15,
                max_tokens=1600,
            )
        else:
            result = self._llm.extract_json_deep(
                system_prompt=_FINAL_REASONING_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=2500,
            )

        if isinstance(result, dict):
            metadata = dict(fused.get("metadata") or {})
            metadata.update(
                {
                    "fusion_applied": True,
                    "vision_items_used": len(((fused.get("vision_data") or {}).get("items") or [])),
                    "text_chars": len(str(fused.get("text_content") or "")),
                    "ocr_chars": len(str(fused.get("ocr_content") or "")),
                }
            )

            return DocumentIntelligence(
                summary=self._coerce_text(result.get("summary")) or "Document processed successfully.",
                insights=self._coerce_string_list(result.get("insights")),
                tables=tables,
                key_points=self._coerce_string_list(result.get("key_points")),
                metrics=self._coerce_metrics(result.get("metrics")),
                risks=self._coerce_string_list(result.get("risks")),
                metadata=metadata,
            )

        return self._fallback_intelligence(fused=fused, tables=tables)

    def _build_reasoning_payload(self, fused: dict[str, Any]) -> dict[str, Any]:
        text_content = str(fused.get("text_content") or "")
        ocr_content = str(fused.get("ocr_content") or "")
        vision_data = fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {}
        metadata = fused.get("metadata") if isinstance(fused.get("metadata"), dict) else {}

        return {
            "text_content": self._chunked_preview(text_content, max_chunks=6),
            "ocr_content": self._limit_chars(ocr_content, 6000),
            "vision_data": {
                "visible_text": self._limit_chars(str(vision_data.get("visible_text") or ""), 5000),
                "layout": self._limit_chars(str(vision_data.get("layout") or ""), 2000),
                "categories": self._coerce_string_list(vision_data.get("categories"), max_items=32),
                "key_elements": self._coerce_string_list(vision_data.get("key_elements"), max_items=48),
                "summary": self._limit_chars(str(vision_data.get("summary") or ""), 2000),
                "tables": vision_data.get("tables") if isinstance(vision_data.get("tables"), list) else [],
                "warnings": self._coerce_string_list(vision_data.get("warnings"), max_items=8),
                "errors": self._coerce_string_list(vision_data.get("errors"), max_items=8),
            },
            "metadata": self._compact_metadata(metadata),
        }

    def _chunked_preview(self, text: str, *, max_chunks: int) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""

        structure = DocumentStructure(
            title="Document",
            sections=[
                Section(
                    heading="Content",
                    level=1,
                    content=normalized,
                )
            ],
            tables=[],
            metadata={},
        )
        chunks = self._chunker.chunk(structure)
        if not chunks:
            return self._limit_chars(normalized, 12000)

        selected = chunks[:max_chunks]
        excerpt = "\n\n".join(chunk.text for chunk in selected if chunk.text.strip())
        if len(chunks) > max_chunks:
            excerpt += "\n\n[... additional chunks omitted for brevity ...]"
        return self._limit_chars(excerpt, 12000)

    @staticmethod
    def _limit_chars(value: str, max_chars: int) -> str:
        text = str(value or "")
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                compact[key] = value
            elif isinstance(value, list):
                compact[key] = value[:20]
            elif isinstance(value, dict):
                compact[key] = {
                    sub_key: sub_value
                    for sub_key, sub_value in value.items()
                    if isinstance(sub_value, (str, int, float, bool))
                }
        return compact

    @staticmethod
    def _coerce_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value).strip()
        if isinstance(value, dict):
            for key in ("text", "name", "value", "entity", "label", "title"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            return ""
        if isinstance(value, (list, tuple, set)):
            parts = [DocumentPipeline._coerce_text(item) for item in value]
            non_empty = [part for part in parts if part]
            return ", ".join(non_empty[:4]).strip()
        return str(value).strip()

    @staticmethod
    def _coerce_string_list(value: Any, *, max_items: int = 64) -> list[str]:
        if value is None:
            return []

        if isinstance(value, (list, tuple, set)):
            candidates = list(value)
        else:
            candidates = [value]

        output: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = DocumentPipeline._coerce_text(candidate)
            lowered = normalized.lower()
            if not normalized or lowered in seen:
                continue
            seen.add(lowered)
            output.append(normalized)
            if len(output) >= max_items:
                break

        return output

    @staticmethod
    def _coerce_metrics(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, (list, tuple)):
            return []

        metrics: list[dict[str, Any]] = []
        for item in value[:64]:
            if isinstance(item, dict):
                name = DocumentPipeline._coerce_text(item.get("name"))
                metric_value = DocumentPipeline._coerce_text(item.get("value"))
                context = DocumentPipeline._coerce_text(item.get("context"))

                metric: dict[str, Any] = {}
                if name:
                    metric["name"] = name
                if metric_value:
                    metric["value"] = metric_value
                if context:
                    metric["context"] = context
                if metric:
                    metrics.append(metric)
                continue

            fallback_name = DocumentPipeline._coerce_text(item)
            if fallback_name:
                metrics.append({"name": fallback_name})

        return metrics

    @staticmethod
    def _fallback_intelligence(
        *,
        fused: dict[str, Any],
        tables: list[dict[str, Any]],
    ) -> DocumentIntelligence:
        metadata = dict(fused.get("metadata") or {})
        summary_parts = [
            str(fused.get("text_content") or "").strip(),
            str(fused.get("ocr_content") or "").strip(),
            str(((fused.get("vision_data") or {}).get("summary") or "")).strip(),
        ]
        summary = " ".join(part for part in summary_parts if part).strip()
        summary = summary[:600] if summary else "Document processed but final reasoning fallback was used."

        risks: list[str] = []
        vision_errors = ((fused.get("vision_data") or {}).get("errors") or [])
        if vision_errors:
            risks.extend(str(item) for item in vision_errors if str(item).strip())

        return DocumentIntelligence(
            summary=summary,
            insights=["Final JSON reasoning fallback was used; output may be less detailed."],
            tables=tables,
            key_points=[summary] if summary else [],
            metrics=[],
            risks=risks,
            metadata=metadata,
        )

    @staticmethod
    def _error_intelligence(error: str, file_path: str) -> DocumentIntelligence:
        return DocumentIntelligence(
            summary=f"Document processing failed: {error}",
            insights=[],
            tables=[],
            key_points=[],
            metrics=[],
            risks=[error],
            metadata={"file_path": file_path, "error": error},
        )
