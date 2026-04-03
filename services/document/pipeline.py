"""Hybrid Document Intelligence Pipeline.

Flow:
- Detect file type
- Route image files directly through vision extraction
- Route PDF/DOCX to parser, then run OCR and vision in parallel when needed
- Fuse all modalities into a single structured object
- Send fused object to Gemini for final reasoning
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
from services.document.fast_reasoning import (
    compact_sentences,
    extract_key_points_fast,
    query_needs_visual_reasoning,
)
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
from services.document.pipeline_utils import (
    coerce_image_payloads,
    coerce_metrics,
    coerce_string_list,
    coerce_text,
    compact_metadata,
    has_vision_signal,
    limit_chars,
    merge_ocr_payloads,
    sanitize_metadata,
    vision_results_have_signal,
)
from services.document.processors.chunker import SemanticChunker
from services.document.processors.cleaner import DocumentCleaner
from services.document.processors.entities import extract_key_entities, merge_entities, normalize_entities
from services.document.processors.fusion import FusionProcessor
from services.document.processors.retriever import SemanticRetriever
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
    "risks": ["..."],
    "entities": {
        "names": ["..."],
        "dates": ["..."],
        "prices": ["..."],
        "companies": ["..."],
        "plans": ["..."],
        "features": ["..."]
    }
}
"""

_TEXT_PRIMARY_SYSTEM_PROMPT = """You are a text-first document analyzer.
You will receive extracted document text and a user query.
Return strict JSON only with this exact schema:
{
    "summary": "...",
    "key_points": ["..."],
    "risks": ["..."]
}
Rules:
- Use only the provided text.
- Keep output concise and factual.
- Do not add commentary outside JSON.
"""


class DocumentPipeline:
    """Hybrid pipeline that fuses parser, OCR, and vision outputs."""

    def __init__(self, llm_client: DocumentLLMClient, config: AppConfig) -> None:
        self._llm = llm_client
        self._cleaner = DocumentCleaner(llm_client)
        self._chunker = SemanticChunker(max_tokens=1800, overlap_tokens=120)
        self._fusion = FusionProcessor()
        self._retriever = SemanticRetriever(max_chunk_chars=720, overlap_chars=120)
        self._vision_max_workers = max(1, int(config.document_vision_max_workers))
        self._reasoning_max_chunks = max(4, int(config.document_reasoning_max_chunks))
        self._reasoning_text_char_budget = max(6000, int(config.document_reasoning_text_char_budget))
        self._reasoning_ocr_char_budget = max(3000, int(config.document_reasoning_ocr_char_budget))
        self._reasoning_vision_visible_char_budget = max(
            2000,
            int(config.document_reasoning_vision_visible_char_budget),
        )
        self._reasoning_vision_layout_char_budget = max(
            1000,
            int(config.document_reasoning_vision_layout_char_budget),
        )
        self._reasoning_vision_summary_char_budget = max(
            800,
            int(config.document_reasoning_vision_summary_char_budget),
        )
        self._reasoning_fast_path_threshold_chars = max(
            4000,
            int(config.document_reasoning_fast_path_threshold_chars),
        )
        self._reasoning_default_fast = bool(config.document_reasoning_default_fast)
        self._ultra_fast_enabled = bool(config.document_ultra_fast_enabled)
        self._ultra_fast_min_chars = max(300, int(config.document_ultra_fast_min_chars))
        self._skip_vision_for_text_rich = bool(config.document_skip_vision_for_text_rich)
        self._text_rich_min_chars = max(600, int(config.document_text_rich_min_chars))
        self._text_primary_max_vision_support_images = max(
            1,
            int(os.getenv("DOCUMENT_TEXT_PRIMARY_MAX_VISION_SUPPORT_IMAGES", "3")),
        )
        self._vision_support_second_pass = str(
            os.getenv("DOCUMENT_VISION_SUPPORT_SECOND_PASS", "false")
        ).strip().lower() in {"1", "true", "yes", "on"}

        vision_config = VisionConfig(
            api_key=config.gemini_api_key,
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
            max_workers=max(1, int(config.document_ocr_max_workers)),
        )
        self._ocr = OcrProcessor(ocr_config)

        self._pdf_parser = PdfParser()
        self._docx_parser = DocxParser()

    def process(
        self,
        file_path: str,
        *,
        progress: PipelineProgress | None = None,
        user_query: str = "",
    ) -> DocumentIntelligence:
        prog = progress or PipelineProgress()
        started = time.time()

        try:
            ext = Path(file_path).suffix.lower().strip()
            if ext in _IMAGE_EXTENSIONS:
                return self._process_image(file_path, prog, user_query=user_query)

            if ext in {".pdf", ".docx", ".doc"}:
                return self._process_document(file_path, prog, user_query=user_query)

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

    def _process_image(
        self,
        file_path: str,
        progress: PipelineProgress,
        *,
        user_query: str,
    ) -> DocumentIntelligence:
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
        has_vision_data = has_vision_signal(vision_bundle)

        if not has_vision_data:
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
                has_vision_data = has_vision_signal(vision_bundle)

        if not has_vision_data and not cleaned_ocr_text:
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

        retrieval_chunks = self._build_retrieval_chunks(
            text_content=str(fused.get("text_content") or ""),
            ocr_content=str(fused.get("ocr_content") or ""),
            vision_bundle=fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {},
            tables=[],
        )
        metadata["retrieval_chunks"] = retrieval_chunks
        fused["metadata"] = metadata

        progress.advance("intelligence", "Generating final reasoning from fused data")
        return self._reason_over_fused_data(
            fused=fused,
            tables=[],
            prefer_fast_model=True,
            user_query=user_query,
        )

    def _process_document(
        self,
        file_path: str,
        progress: PipelineProgress,
        *,
        user_query: str,
    ) -> DocumentIntelligence:
        progress.advance("parsing", "Extracting document text and media")
        extraction = self._parse_document(file_path)
        if extraction.error:
            return self._error_intelligence(f"Parsing failed: {extraction.error}", file_path)

        text_content = self._cleaner.clean_extracted_text(extraction.text)
        raw_metadata = dict(extraction.metadata or {})
        vision_inputs = coerce_image_payloads(raw_metadata.get("vision_images"))
        ocr_inputs = coerce_image_payloads(raw_metadata.get("ocr_images"))

        visual_query = query_needs_visual_reasoning(user_query)
        text_length = len(text_content)
        text_primary_threshold = self._text_rich_min_chars
        text_primary_mode = text_length > text_primary_threshold

        text_primary_result: dict[str, Any] = {
            "summary": "",
            "key_points": [],
            "risks": [],
            "mode": "",
        }

        should_run_ocr = bool(ocr_inputs) and bool(raw_metadata.get("is_scanned"))
        # Keep vision as supporting context whenever document images are available.
        should_run_vision = bool(vision_inputs)
        original_vision_input_count = len(vision_inputs)
        if should_run_vision and text_primary_mode and not visual_query:
            vision_inputs = self._limit_vision_inputs_for_support_context(vision_inputs)

        ocr_applied = should_run_ocr

        ocr_result: dict[str, Any] = {
            "text": "",
            "confidence": 0.0,
            "warning": "",
            "error": "",
            "per_image": [],
        }
        vision_results: list[dict[str, Any]] = []

        if should_run_ocr or should_run_vision or text_primary_mode:
            progress.advance("processing_chunks", "Running text, OCR, and vision tasks")
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures: dict[Any, str] = {}
                if text_primary_mode:
                    futures[
                        executor.submit(
                            self._run_text_primary_analysis,
                            text_content=text_content,
                            user_query=user_query,
                        )
                    ] = "text_primary"
                if should_run_ocr:
                    futures[executor.submit(self._ocr.extract_images, ocr_inputs)] = "ocr"
                if should_run_vision:
                    futures[
                        executor.submit(
                            self._vision.analyze_images,
                            vision_inputs,
                            max_workers=self._vision_max_workers,
                            allow_second_pass=self._vision_support_second_pass,
                        )
                    ] = "vision"

                for future in as_completed(futures):
                    task_name = futures[future]
                    try:
                        if task_name == "text_primary":
                            value = future.result()
                            if isinstance(value, dict):
                                text_primary_result = value
                        elif task_name == "ocr":
                            value = future.result()
                            if isinstance(value, dict):
                                ocr_result = value
                        elif task_name == "vision":
                            value = future.result()
                            if isinstance(value, list):
                                vision_results = [item for item in value if isinstance(item, dict)]
                    except Exception as exc:
                        logger.warning("Parallel %s task failed: %s", task_name, exc)
        else:
            progress.advance("processing_chunks", "Skipping OCR/vision fast lane; using extracted text")

        cleaned_ocr_text = self._cleaner.clean_ocr_text(str(ocr_result.get("text") or ""))

        if should_run_vision and not cleaned_ocr_text and not vision_results_have_signal(vision_results):
            progress.advance("processing_chunks", "Vision unavailable; running OCR fallback on embedded images")
            ocr_applied = True
            fallback_ocr = self._ocr.extract_images(vision_inputs)
            cleaned_fallback = self._cleaner.clean_ocr_text(str(fallback_ocr.get("text") or ""))
            if cleaned_fallback:
                cleaned_ocr_text = cleaned_fallback
            ocr_result = merge_ocr_payloads(ocr_result, fallback_ocr)

        sanitized_metadata = sanitize_metadata(raw_metadata)
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
                "vision_input_count_original": original_vision_input_count,
                "vision_input_count_used": len(vision_inputs),
                "vision_skipped_fast_lane": False,
                "text_rich_input": text_primary_mode,
                "text_length": text_length,
                "text_primary_threshold": text_primary_threshold,
                "text_primary_applied": text_primary_mode,
                "text_primary_summary": str(text_primary_result.get("summary") or ""),
                "text_primary_key_points": coerce_string_list(text_primary_result.get("key_points"), max_items=6),
                "text_primary_risks": coerce_string_list(text_primary_result.get("risks"), max_items=4),
                "text_primary_mode": str(text_primary_result.get("mode") or ""),
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
        has_vision_data = has_vision_signal(vision_bundle)

        if not fused.get("text_content") and not fused.get("ocr_content") and not has_vision_data:
            return self._error_intelligence("No usable content extracted from document", file_path)

        tables = [table.to_dict() for table in extraction.tables]
        retrieval_chunks = self._build_retrieval_chunks(
            text_content=str(fused.get("text_content") or ""),
            ocr_content=str(fused.get("ocr_content") or ""),
            vision_bundle=vision_bundle,
            tables=tables,
        )
        sanitized_metadata["retrieval_chunks"] = retrieval_chunks
        fused["metadata"] = sanitized_metadata

        progress.advance("intelligence", "Generating final reasoning from fused data")
        return self._reason_over_fused_data(
            fused=fused,
            tables=tables,
            user_query=user_query,
        )

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

    def _limit_vision_inputs_for_support_context(self, vision_inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(vision_inputs) <= self._text_primary_max_vision_support_images:
            return vision_inputs

        target = self._text_primary_max_vision_support_images
        if target <= 1:
            return [vision_inputs[0]]

        # Sample across the document (front/middle/back) instead of only first pages.
        last_index = len(vision_inputs) - 1
        sampled_indices = {
            round((last_index * idx) / max(1, target - 1))
            for idx in range(target)
        }
        selected = [vision_inputs[idx] for idx in sorted(sampled_indices)]

        if len(selected) < target:
            for idx, item in enumerate(vision_inputs):
                if idx in sampled_indices:
                    continue
                selected.append(item)
                if len(selected) >= target:
                    break

        return selected[:target]

    def _reason_over_fused_data(
        self,
        *,
        fused: dict[str, Any],
        tables: list[dict[str, Any]],
        prefer_fast_model: bool = False,
        user_query: str = "",
    ) -> DocumentIntelligence:
        normalized_query = str(user_query or "").strip().lower()
        asks_depth = any(
            token in normalized_query
            for token in (
                "detailed",
                "in detail",
                "deep",
                "comprehensive",
                "exhaustive",
                "full breakdown",
            )
        )
        visual_query = query_needs_visual_reasoning(normalized_query)

        if self._should_use_ultra_fast_reasoning(
            fused=fused,
            normalized_query=normalized_query,
            asks_depth=asks_depth,
            visual_query=visual_query,
        ):
            deterministic = self._build_ultra_fast_intelligence(fused=fused, tables=tables)
            if deterministic is not None:
                return deterministic

        prompt_payload = self._build_reasoning_payload(fused, user_query=user_query)

        signal_chars = (
            len(str(fused.get("text_content") or ""))
            + len(str(fused.get("ocr_content") or ""))
            + len(str(((fused.get("vision_data") or {}).get("visible_text") or "")))
            + len(str(((fused.get("vision_data") or {}).get("summary") or "")))
        )

        if not prefer_fast_model:
            very_large_payload = signal_chars >= (self._reasoning_fast_path_threshold_chars * 2)

            if self._reasoning_default_fast and not asks_depth and not very_large_payload:
                prefer_fast_model = True
            elif signal_chars <= self._reasoning_fast_path_threshold_chars and str(user_query or "").strip():
                prefer_fast_model = True

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
            entities = self._coerce_entities(result.get("entities"))
            if not any(entities.get(key) for key in entities):
                entities = self._extract_entities_fallback(
                    text_content=str(fused.get("text_content") or ""),
                    ocr_content=str(fused.get("ocr_content") or ""),
                    vision_data=fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {},
                )

            metadata.update(
                {
                    "fusion_applied": True,
                    "vision_items_used": len(((fused.get("vision_data") or {}).get("items") or [])),
                    "text_chars": len(str(fused.get("text_content") or "")),
                    "ocr_chars": len(str(fused.get("ocr_content") or "")),
                    "entity_counts": {key: len(value) for key, value in entities.items()},
                }
            )

            return DocumentIntelligence(
                summary=coerce_text(result.get("summary")) or "Document processed successfully.",
                insights=coerce_string_list(result.get("insights")),
                tables=tables,
                key_points=coerce_string_list(result.get("key_points")),
                metrics=coerce_metrics(result.get("metrics")),
                risks=coerce_string_list(result.get("risks")),
                entities=entities,
                metadata=metadata,
            )

        return self._fallback_intelligence(fused=fused, tables=tables)

    def _run_text_primary_analysis(
        self,
        *,
        text_content: str,
        user_query: str,
    ) -> dict[str, Any]:
        payload_text = self._chunked_preview(
            text_content,
            max_chunks=max(4, min(10, self._reasoning_max_chunks)),
            max_chars=self._reasoning_text_char_budget,
        )

        if not payload_text.strip():
            return {
                "summary": "",
                "key_points": [],
                "risks": [],
                "mode": "empty",
            }

        prompt_payload = {
            "user_query": limit_chars(str(user_query or "").strip(), 320),
            "text_content": payload_text,
        }
        user_prompt = (
            "Analyze this extracted document text and return concise JSON: "
            f"{json.dumps(prompt_payload, ensure_ascii=True)}"
        )

        result = self._llm.extract_json_fast(
            system_prompt=_TEXT_PRIMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=1000,
        )

        if isinstance(result, dict):
            summary = coerce_text(result.get("summary"))
            key_points = coerce_string_list(result.get("key_points"), max_items=6)
            risks = coerce_string_list(result.get("risks"), max_items=4)
            if summary or key_points:
                return {
                    "summary": summary,
                    "key_points": key_points,
                    "risks": risks,
                    "mode": "llm_text_primary",
                }

        fallback_summary = compact_sentences(payload_text, max_sentences=3, max_chars=320)
        fallback_points = extract_key_points_fast(payload_text, max_items=5)
        return {
            "summary": fallback_summary,
            "key_points": coerce_string_list(fallback_points, max_items=5),
            "risks": [],
            "mode": "deterministic_text_primary",
        }

    def _should_use_ultra_fast_reasoning(
        self,
        *,
        fused: dict[str, Any],
        normalized_query: str,
        asks_depth: bool,
        visual_query: bool,
    ) -> bool:
        if not self._ultra_fast_enabled:
            return False
        if asks_depth or visual_query:
            return False
        if any(token in normalized_query for token in ("compare", "comparison", "difference", "differences", "versus", " vs ")):
            return False

        text_chars = len(str(fused.get("text_content") or "")) + len(str(fused.get("ocr_content") or ""))
        vision_bundle = fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {}
        vision_chars = len(str(vision_bundle.get("visible_text") or "")) + len(str(vision_bundle.get("summary") or ""))
        signal_chars = text_chars + vision_chars
        if signal_chars < self._ultra_fast_min_chars:
            return False

        if has_vision_signal(vision_bundle) and text_chars < self._text_rich_min_chars:
            return False

        return True

    def _build_ultra_fast_intelligence(
        self,
        *,
        fused: dict[str, Any],
        tables: list[dict[str, Any]],
    ) -> DocumentIntelligence | None:
        text_content = str(fused.get("text_content") or "")
        ocr_content = str(fused.get("ocr_content") or "")
        vision_data = fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {}
        metadata = dict(fused.get("metadata") or {})

        evidence = "\n".join(
            part.strip()
            for part in (
                text_content,
                ocr_content,
                str(vision_data.get("visible_text") or ""),
                str(vision_data.get("summary") or ""),
            )
            if str(part or "").strip()
        )
        if len(evidence) < self._ultra_fast_min_chars:
            return None

        summary = compact_sentences(evidence, max_sentences=3, max_chars=420)
        key_points = extract_key_points_fast(evidence, max_items=6)
        insights = key_points[:3] if key_points else ([summary] if summary else [])

        entities = self._extract_entities_fallback(
            text_content=text_content,
            ocr_content=ocr_content,
            vision_data=vision_data,
        )
        risks = self._collect_fast_risks(metadata, vision_data)

        metadata.update(
            {
                "fusion_applied": True,
                "reasoning_mode": "ultra_fast_deterministic",
                "llm_skipped": True,
                "vision_items_used": len((vision_data.get("items") or [])) if isinstance(vision_data, dict) else 0,
                "text_chars": len(text_content),
                "ocr_chars": len(ocr_content),
                "entity_counts": {key: len(value) for key, value in entities.items()},
            }
        )

        return DocumentIntelligence(
            summary=summary or "Document processed successfully.",
            insights=coerce_string_list(insights, max_items=4),
            tables=tables,
            key_points=coerce_string_list(key_points, max_items=6),
            metrics=[],
            risks=coerce_string_list(risks, max_items=4),
            entities=entities,
            metadata=metadata,
        )

    @staticmethod
    def _collect_fast_risks(metadata: dict[str, Any], vision_data: dict[str, Any]) -> list[str]:
        risks: list[str] = []
        for key in ("error", "ocr_error", "vision_error", "warning", "ocr_warning", "vision_warning"):
            value = str(metadata.get(key) or "").strip()
            if value:
                risks.append(value)

        risks.extend(coerce_string_list(vision_data.get("errors"), max_items=4))
        risks.extend(coerce_string_list(vision_data.get("warnings"), max_items=4))
        return coerce_string_list(risks, max_items=6)

    def _build_reasoning_payload(self, fused: dict[str, Any], *, user_query: str) -> dict[str, Any]:
        text_content = str(fused.get("text_content") or "")
        ocr_content = str(fused.get("ocr_content") or "")
        vision_data = fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {}
        metadata = fused.get("metadata") if isinstance(fused.get("metadata"), dict) else {}
        metadata_for_prompt = dict(metadata)
        metadata_for_prompt.pop("retrieval_chunks", None)

        dynamic_chunks = min(
            self._reasoning_max_chunks,
            max(4, (len(text_content) // 3500) + 4),
        )

        return {
            "user_query": limit_chars(str(user_query or "").strip(), 420),
            "text_primary_context": {
                "applied": bool(metadata.get("text_primary_applied")),
                "summary": limit_chars(str(metadata.get("text_primary_summary") or ""), 360),
                "key_points": coerce_string_list(metadata.get("text_primary_key_points"), max_items=6),
                "risks": coerce_string_list(metadata.get("text_primary_risks"), max_items=4),
                "mode": str(metadata.get("text_primary_mode") or ""),
            },
            "text_content": self._chunked_preview(
                text_content,
                max_chunks=dynamic_chunks,
                max_chars=self._reasoning_text_char_budget,
            ),
            "ocr_content": limit_chars(ocr_content, self._reasoning_ocr_char_budget),
            "vision_data": {
                "visible_text": limit_chars(
                    str(vision_data.get("visible_text") or ""),
                    self._reasoning_vision_visible_char_budget,
                ),
                "layout": limit_chars(
                    str(vision_data.get("layout") or ""),
                    self._reasoning_vision_layout_char_budget,
                ),
                "categories": coerce_string_list(vision_data.get("categories"), max_items=32),
                "key_elements": coerce_string_list(vision_data.get("key_elements"), max_items=48),
                "summary": limit_chars(
                    str(vision_data.get("summary") or ""),
                    self._reasoning_vision_summary_char_budget,
                ),
                "tables": vision_data.get("tables") if isinstance(vision_data.get("tables"), list) else [],
                "warnings": coerce_string_list(vision_data.get("warnings"), max_items=8),
                "errors": coerce_string_list(vision_data.get("errors"), max_items=8),
            },
            "metadata": compact_metadata(metadata_for_prompt),
        }

    def _build_retrieval_chunks(
        self,
        *,
        text_content: str,
        ocr_content: str,
        vision_bundle: dict[str, Any],
        tables: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        blocks: list[tuple[str, str]] = [
            ("text", text_content),
            ("ocr", ocr_content),
            ("vision_visible_text", str(vision_bundle.get("visible_text") or "")),
            ("vision_summary", str(vision_bundle.get("summary") or "")),
        ]

        table_lines: list[str] = []
        for idx, table in enumerate(tables):
            if not isinstance(table, dict):
                continue
            headers = table.get("headers") if isinstance(table.get("headers"), list) else []
            rows = table.get("rows") if isinstance(table.get("rows"), list) else []
            title = str(table.get("title") or table.get("caption") or "").strip()

            parts: list[str] = []
            if title:
                parts.append(f"Table {idx + 1}: {title}")
            if headers:
                parts.append("Headers: " + " | ".join(str(item or "").strip() for item in headers if str(item or "").strip()))
            for row in rows[:20]:
                if isinstance(row, list):
                    row_text = " | ".join(str(item or "").strip() for item in row if str(item or "").strip())
                    if row_text:
                        parts.append(row_text)

            combined = "\n".join(part for part in parts if part)
            if combined:
                table_lines.append(combined)

        blocks.append(("tables", "\n\n".join(table_lines)))
        return self._retriever.build_chunks(blocks, max_chunks=220)

    def _chunked_preview(self, text: str, *, max_chunks: int, max_chars: int) -> str:
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
            return limit_chars(normalized, max_chars)

        if len(chunks) <= max_chunks:
            selected = chunks
        else:
            # Preserve both leading and trailing context to reduce long-document information loss.
            head_count = max(2, max_chunks // 2)
            tail_count = max(1, max_chunks - head_count)
            selected = [*chunks[:head_count], *chunks[-tail_count:]]

        excerpt = "\n\n".join(chunk.text for chunk in selected if chunk.text.strip())
        if len(chunks) > max_chunks:
            excerpt += "\n\n[... middle chunks omitted for brevity ...]"
        return limit_chars(excerpt, max_chars)

    @staticmethod
    def _coerce_entities(value: Any) -> dict[str, list[str]]:
        return normalize_entities(value)

    @staticmethod
    def _extract_entities_fallback(
        *,
        text_content: str,
        ocr_content: str,
        vision_data: dict[str, Any],
    ) -> dict[str, list[str]]:
        vision_text = " ".join(
            part
            for part in (
                str(vision_data.get("visible_text") or ""),
                str(vision_data.get("summary") or ""),
                str(vision_data.get("layout") or ""),
            )
            if part
        )
        merged_text = "\n\n".join(
            part
            for part in (text_content, ocr_content, vision_text)
            if str(part or "").strip()
        )

        deterministic = extract_key_entities(merged_text)

        vision_entities = vision_data.get("entities") if isinstance(vision_data.get("entities"), dict) else {}
        return merge_entities(deterministic, normalize_entities(vision_entities))

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
            entities=DocumentPipeline._extract_entities_fallback(
                text_content=str(fused.get("text_content") or ""),
                ocr_content=str(fused.get("ocr_content") or ""),
                vision_data=fused.get("vision_data") if isinstance(fused.get("vision_data"), dict) else {},
            ),
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
            entities={"names": [], "dates": [], "prices": [], "companies": [], "plans": [], "features": []},
            metadata={"file_path": file_path, "error": error},
        )
