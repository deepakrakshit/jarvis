# ==============================================================================
# File: services/document/document_service.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Document Intelligence Service — Analysis, Q&A, Comparison
#
#    - Top-level orchestrator with multi-tier caching architecture.
#    - L1 cache: in-memory OrderedDict with TTL-based expiration.
#    - L2 cache: SQLite-backed persistent storage with content-hash keys.
#    - Concurrent request deduplication: per-cache-key threading.Lock prevents
#      duplicate expensive processing for the same document.
#    - analyze(): full pipeline execution with structured intelligence output
#      (summary, insights, tables, key_points, entities, risks).
#    - answer_question(): retrieval-augmented Q&A over analyzed documents.
#    - compare_documents(): cross-document comparison for pricing, plans, risks.
#    - Active document registry: tracks up to 8 recent analyses for follow-up Q&A.
#    - File hash caching: avoids re-hashing unchanged files via (path, mtime, size).
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import os
import hashlib
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from pathlib import Path
from typing import Any

from core.settings import AppConfig
from services.document.cache_store import DocumentCacheStore, build_default_cache_config
from services.document.file_selector import validate_file_path
from services.document.llm_client import DocumentLLMClient
from services.document.models import PipelineProgress
from services.document.pipeline import DocumentPipeline
from services.document.processors.entities import normalize_entities
from services.document.processors.retriever import SemanticRetriever
from services.document.qa_engine import DocumentQAEngine

logger = logging.getLogger(__name__)


class DocumentService:
    """Top-level document intelligence service for JARVIS.

    Usage:
        service = DocumentService(config)
        result = service.analyze(file_path)
    """

    PIPELINE_VERSION = "document_pipeline_v5_intelligence"

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._fast_model = config.primary_llm_model()
        self._deep_model = getattr(config, "document_deep_model", "gemini-2.5-flash")
        self._llm_client = DocumentLLMClient(
            config=config,
            fast_model=self._fast_model,
            deep_model=self._deep_model,
        )
        self._pipeline = DocumentPipeline(self._llm_client, config)
        cache_config = build_default_cache_config(
            enabled=config.document_cache_enabled,
            db_path=config.document_cache_db_path,
            ttl_seconds=config.document_cache_ttl_seconds,
            max_entries=config.document_cache_max_entries,
        )
        self._cache = DocumentCacheStore(cache_config)

        # L1 hot cache (in-memory) backed by persistent SQLite cache.
        self._memory_cache_lock = threading.Lock()
        self._memory_cache: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()
        self._memory_cache_ttl_seconds = max(30, min(int(config.document_cache_ttl_seconds), 900))
        self._memory_cache_max_entries = max(64, min(4096, int(config.document_cache_max_entries) * 4))

        # Prevent duplicate expensive processing for the same cache key under concurrency.
        self._request_locks_lock = threading.Lock()
        self._request_locks: OrderedDict[str, threading.Lock] = OrderedDict()
        self._request_locks_max_entries = 2048

        # Cache file hashes by (path, mtime_ns, size) to avoid re-hashing unchanged files.
        self._file_hash_cache_lock = threading.Lock()
        self._file_hash_cache: OrderedDict[str, tuple[int, int, str]] = OrderedDict()
        self._file_hash_cache_max_entries = 512

        # Retrieval-first question answering state.
        self._retriever = SemanticRetriever(max_chunk_chars=720, overlap_chars=120)
        self._qa_engine = DocumentQAEngine(self._llm_client, self._retriever)
        self._active_documents_lock = threading.Lock()
        self._active_documents: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._active_documents_max_entries = 8

    def analyze(self, file_path: str, *, user_query: str = "") -> dict[str, Any]:
        """Analyze a document and return structured intelligence.

        Args:
            file_path: Path to the document file.
            user_query: Original user query for context.

        Returns:
            Structured dict with summary, insights, tables, key_points, etc.
        """
        # Validate file
        validated_path, error = validate_file_path(file_path)
        if error:
            logger.info("Document validation failed: %s", error)
            return {
                "success": False,
                "error": error,
                "summary": "",
                "insights": [],
                "tables": [],
                "key_points": [],
                "entities": self._empty_entities(),
            }

        cache_key: str | None = None
        file_hash: str | None = None
        try:
            cache_key, file_hash = self._build_cache_identity(validated_path, user_query=user_query)
        except Exception as exc:
            logger.warning("Document cache identity build failed; continuing uncached: %s", exc)

        if cache_key:
            memory_hit = self._memory_cache_get(cache_key)
            if isinstance(memory_hit, dict) and memory_hit.get("success"):
                cached_result = self._format_cache_hit(memory_hit, validated_path=validated_path, tier="memory")
                self._register_active_document(validated_path, cached_result, file_hash=file_hash)
                return cached_result

            request_lock = self._get_request_lock(cache_key)
            with request_lock:
                memory_hit = self._memory_cache_get(cache_key)
                if isinstance(memory_hit, dict) and memory_hit.get("success"):
                    cached_result = self._format_cache_hit(memory_hit, validated_path=validated_path, tier="memory")
                    self._register_active_document(validated_path, cached_result, file_hash=file_hash)
                    return cached_result

                persistent_hit = self._persistent_cache_get(cache_key)
                if isinstance(persistent_hit, dict) and persistent_hit.get("success"):
                    self._memory_cache_set(cache_key, persistent_hit)
                    cached_result = self._format_cache_hit(persistent_hit, validated_path=validated_path, tier="persistent")
                    self._register_active_document(validated_path, cached_result, file_hash=file_hash)
                    return cached_result

                result = self._compute_result(validated_path, user_query=user_query)
                if result.get("success") and file_hash and self._should_cache_result(result):
                    self._persistent_cache_set(
                        cache_key=cache_key,
                        file_path=validated_path,
                        file_hash=file_hash,
                        payload=result,
                    )
                    self._memory_cache_set(cache_key, result)
                if result.get("success"):
                    self._register_active_document(validated_path, result, file_hash=file_hash)
                return result

        result = self._compute_result(validated_path, user_query=user_query)
        if result.get("success"):
            self._register_active_document(validated_path, result, file_hash=None)
        return result

    def has_active_documents(self) -> bool:
        with self._active_documents_lock:
            return bool(self._active_documents)

    def active_document_names(self) -> list[str]:
        with self._active_documents_lock:
            return [str(item.get("file_name") or "Document") for item in self._active_documents.values()]

    def answer_question(
        self,
        question: str,
        *,
        file_paths: list[str] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        clean_question = " ".join(str(question or "").split())
        if not clean_question:
            return {
                "success": False,
                "error": "Question is empty.",
                "answer": "",
                "entities": self._empty_entities(),
                "citations": [],
            }

        records, errors = self._resolve_target_records(clean_question, file_paths=file_paths)
        if errors and not records:
            return {
                "success": False,
                "error": " | ".join(errors[:3]),
                "answer": "",
                "entities": self._empty_entities(),
                "citations": [],
            }

        if not records:
            return {
                "success": False,
                "error": "No active document context. Analyze a document first.",
                "answer": "",
                "entities": self._empty_entities(),
                "citations": [],
            }

        compare_mode = self._qa_engine.looks_like_compare_question(clean_question) or bool(file_paths and len(records) > 1)
        if compare_mode:
            return self._answer_multi_document_question(clean_question, records, top_k=top_k)

        target_record = records[-1]
        return self._answer_single_document_question(clean_question, target_record, top_k=top_k)

    def answer_question_for_display(
        self,
        question: str,
        *,
        file_paths: list[str] | None = None,
    ) -> str:
        payload = self.answer_question(question, file_paths=file_paths)
        if not payload.get("success"):
            detail = str(payload.get("error") or "No answer available.").strip()
            return f"I could not answer that from document context. {detail}"

        answer = self._compact_text(str(payload.get("answer") or ""), max_chars=360)
        points = self._compact_list(payload.get("supporting_points"), max_items=3, max_chars=140)
        citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
        entities = normalize_entities(payload.get("entities"))

        lines: list[str] = [answer or "Answer generated from document evidence."]

        if points:
            lines.append("")
            lines.append("Evidence Highlights:")
            for item in points:
                lines.append(f"- {item}")

        if citations:
            refs = []
            for item in citations[:3]:
                if not isinstance(item, dict):
                    continue
                source = str(item.get("source") or item.get("file") or "chunk").strip()
                chunk_id = str(item.get("chunk_id") or "").strip()
                ref = f"{source} ({chunk_id})" if chunk_id else source
                if ref:
                    refs.append(ref)
            if refs:
                lines.append("")
                lines.append("Sources: " + "; ".join(refs))

        entity_line = self._format_entities_compact(entities)
        if entity_line:
            lines.append("")
            lines.append("Entities: " + entity_line)

        return "\n".join(lines).strip()

    def compare_documents(
        self,
        file_paths: list[str],
        *,
        user_query: str = "",
    ) -> dict[str, Any]:
        compare_prompt = user_query.strip() or "Compare these documents for pricing, plans, risks, and key differences."
        return self.answer_question(compare_prompt, file_paths=file_paths, top_k=8)

    def compare_documents_for_display(
        self,
        file_paths: list[str],
        *,
        user_query: str = "",
    ) -> str:
        payload = self.compare_documents(file_paths, user_query=user_query)
        if not payload.get("success"):
            detail = str(payload.get("error") or "Comparison failed.").strip()
            return f"I could not compare those documents. {detail}"

        summary = self._compact_text(str(payload.get("summary") or payload.get("answer") or ""), max_chars=420)
        comparisons = self._compact_list(payload.get("comparisons"), max_items=4, max_chars=160)
        risks = self._compact_list(payload.get("risks"), max_items=3, max_chars=120)
        recommendation = self._compact_text(str(payload.get("recommendation") or ""), max_chars=180)

        lines: list[str] = [summary or "Cross-document comparison generated."]

        if comparisons:
            lines.append("")
            lines.append("Key Differences:")
            for item in comparisons:
                lines.append(f"- {item}")

        if risks:
            lines.append("")
            lines.append("Risk Notes: " + "; ".join(risks))

        if recommendation:
            lines.append("")
            lines.append("Recommendation: " + recommendation)

        entity_line = self._format_entities_compact(normalize_entities(payload.get("entities")))
        if entity_line:
            lines.append("")
            lines.append("Entities: " + entity_line)

        return "\n".join(lines).strip()

    def _resolve_target_records(
        self,
        question: str,
        *,
        file_paths: list[str] | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        errors: list[str] = []
        records: list[dict[str, Any]] = []

        if file_paths:
            validated_paths: list[str] = []
            seen_paths: set[str] = set()

            for raw_path in file_paths:
                validated_path, error = validate_file_path(str(raw_path or ""))
                if error:
                    errors.append(error)
                    continue

                normalized = os.path.normcase(os.path.abspath(validated_path))
                if normalized in seen_paths:
                    continue
                seen_paths.add(normalized)
                validated_paths.append(validated_path)

            records_by_path: dict[str, dict[str, Any]] = {}
            pending_paths: list[str] = []

            for validated_path in validated_paths:
                active_record = self._get_active_document_record(validated_path)
                if active_record is not None:
                    records_by_path[validated_path] = active_record
                    continue
                pending_paths.append(validated_path)

            if pending_paths:
                max_workers = max(1, min(4, len(pending_paths)))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(self.analyze, path, user_query=question): path
                        for path in pending_paths
                    }

                    for future in as_completed(futures):
                        validated_path = futures[future]
                        try:
                            analysis = future.result()
                        except Exception as exc:
                            errors.append(f"{Path(validated_path).name}: analysis failed ({exc})")
                            continue

                        if not analysis.get("success"):
                            errors.append(
                                f"{Path(validated_path).name}: {str(analysis.get('error') or 'analysis failed')}"
                            )
                            continue

                        record = self._get_active_document_record(validated_path)
                        if record is not None:
                            records_by_path[validated_path] = record

            for validated_path in validated_paths:
                record = records_by_path.get(validated_path)
                if record is not None:
                    records.append(record)

            return records, errors

        with self._active_documents_lock:
            records = list(self._active_documents.values())

        return records, errors

    def _answer_single_document_question(
        self,
        question: str,
        record: dict[str, Any],
        *,
        top_k: int,
    ) -> dict[str, Any]:
        return self._qa_engine.answer_single_document_question(
            question,
            record,
            top_k=top_k,
        )

    def _answer_multi_document_question(
        self,
        question: str,
        records: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> dict[str, Any]:
        return self._qa_engine.answer_multi_document_question(
            question,
            records,
            top_k=top_k,
        )

    def _register_active_document(self, validated_path: str, result: dict[str, Any], *, file_hash: str | None) -> None:
        if not result.get("success"):
            return

        normalized_path = os.path.normcase(os.path.abspath(validated_path))
        chunks = self._extract_retrieval_chunks(result)
        if not chunks:
            return

        record = {
            "file_path": validated_path,
            "file_name": str(result.get("file_name") or Path(validated_path).name),
            "file_hash": file_hash or str(result.get("file_hash") or ""),
            "summary": str(result.get("summary") or ""),
            "key_points": result.get("key_points") if isinstance(result.get("key_points"), list) else [],
            "risks": result.get("risks") if isinstance(result.get("risks"), list) else [],
            "entities": normalize_entities(result.get("entities")),
            "chunks": chunks,
            "indexed_at": int(time.time()),
        }

        with self._active_documents_lock:
            self._active_documents[normalized_path] = record
            self._active_documents.move_to_end(normalized_path)
            while len(self._active_documents) > self._active_documents_max_entries:
                self._active_documents.popitem(last=False)

    def _get_active_document_record(self, validated_path: str) -> dict[str, Any] | None:
        normalized_path = os.path.normcase(os.path.abspath(validated_path))
        with self._active_documents_lock:
            record = self._active_documents.get(normalized_path)
            if record is None:
                return None
            self._active_documents.move_to_end(normalized_path)
            return dict(record)

    def _extract_retrieval_chunks(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        retrieval_chunks = metadata.get("retrieval_chunks") if isinstance(metadata.get("retrieval_chunks"), list) else []
        normalized_chunks: list[dict[str, Any]] = []

        for item in retrieval_chunks:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get("text") or "").split())
            if not text:
                continue
            normalized_chunks.append(
                {
                    "id": str(item.get("id") or f"chunk-{len(normalized_chunks)}"),
                    "source": str(item.get("source") or "chunk"),
                    "text": text,
                }
            )

        if normalized_chunks:
            return normalized_chunks[:260]

        blocks: list[tuple[str, str]] = [
            ("summary", str(result.get("summary") or "")),
            ("key_points", "\n".join(str(item or "") for item in (result.get("key_points") or []))),
            ("insights", "\n".join(str(item or "") for item in (result.get("insights") or []))),
        ]

        tables = result.get("tables") if isinstance(result.get("tables"), list) else []
        table_lines: list[str] = []
        for table in tables:
            if not isinstance(table, dict):
                continue
            headers = table.get("headers") if isinstance(table.get("headers"), list) else []
            rows = table.get("rows") if isinstance(table.get("rows"), list) else []
            if headers:
                table_lines.append(" | ".join(str(item or "").strip() for item in headers if str(item or "").strip()))
            for row in rows[:20]:
                if isinstance(row, list):
                    row_text = " | ".join(str(item or "").strip() for item in row if str(item or "").strip())
                    if row_text:
                        table_lines.append(row_text)
        blocks.append(("tables", "\n".join(table_lines)))

        return self._retriever.build_chunks(blocks, max_chunks=220)

    @staticmethod
    def _empty_entities() -> dict[str, list[str]]:
        return {
            "names": [],
            "dates": [],
            "prices": [],
            "companies": [],
            "plans": [],
            "features": [],
        }

    @staticmethod
    def _format_entities_compact(entities: dict[str, list[str]]) -> str:
        labels = (
            ("prices", "prices"),
            ("plans", "plans"),
            ("companies", "companies"),
            ("dates", "dates"),
            ("names", "names"),
            ("features", "features"),
        )
        parts: list[str] = []
        normalized = normalize_entities(entities)
        for key, label in labels:
            values = normalized.get(key) or []
            if not values:
                continue
            sample = ", ".join(values[:3])
            parts.append(f"{label}: {sample}")
            if len(parts) >= 2:
                break
        return " | ".join(parts)

    @staticmethod
    def _should_cache_result(result: dict[str, Any]) -> bool:
        """Skip cache writes for transient or environment-related degraded outputs."""
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        vision_error = str(metadata.get("vision_error") or "").strip().lower()
        if vision_error in {"vision_api_key_missing", "vision_http_429"}:
            return False

        risks = result.get("risks") if isinstance(result.get("risks"), list) else []
        normalized_risks = [str(item or "").strip().lower() for item in risks]
        if any(
            "gemini_api_key is missing" in item or "vision_http_429" in item
            for item in normalized_risks
        ):
            return False

        summary = str(result.get("summary") or "").strip().lower()
        if "missing gemini_api_key" in summary:
            return False

        return True

    def _build_cache_identity(
        self,
        validated_path: str,
        *,
        user_query: str,
    ) -> tuple[str | None, str | None]:
        """Build cache key using file content and processing fingerprint."""
        if not self._cache.enabled:
            return None, None

        file_hash = self._compute_file_hash_cached(validated_path)
        # Processing output is document-content driven; keep identity stable across
        # follow-up questions so Q&A can reuse the same analyzed artifact.
        query_fingerprint = ""
        cache_key = self._cache.build_cache_key(
            file_hash=file_hash,
            pipeline_version=f"{self.PIPELINE_VERSION}:{sys.version_info.major}.{sys.version_info.minor}",
            fast_model=self._fast_model,
            deep_model=self._deep_model,
            query_fingerprint=query_fingerprint,
        )
        return cache_key, file_hash

    def _compute_result(self, validated_path: str, *, user_query: str = "") -> dict[str, Any]:
        progress = PipelineProgress()

        logger.info("Starting document analysis: %s", validated_path)

        try:
            intelligence = self._pipeline.process(
                validated_path,
                progress=progress,
                user_query=user_query,
            )
        except Exception as exc:
            logger.exception("Document analysis failed: %s", exc)
            return {
                "success": False,
                "error": f"Analysis failed: {exc}",
                "summary": "",
                "insights": [],
                "tables": [],
                "key_points": [],
                "entities": self._empty_entities(),
                "cache_hit": False,
            }

        result = intelligence.to_dict()
        pipeline_error = str((intelligence.metadata or {}).get("error") or "").strip()
        is_success = not pipeline_error

        result["success"] = is_success
        result["error"] = pipeline_error
        result["file_name"] = Path(validated_path).name
        result["file_path"] = validated_path
        result["cache_hit"] = False

        logger.info(
            "Document analysis complete: %s (%d insights, %d key points)",
            Path(validated_path).name,
            len(intelligence.insights),
            len(intelligence.key_points),
        )

        return result

    def _persistent_cache_get(self, cache_key: str) -> dict[str, Any] | None:
        try:
            return self._cache.get(cache_key)
        except Exception as exc:
            logger.warning("Document cache read failed; continuing uncached: %s", exc)
            return None

    def _persistent_cache_set(
        self,
        *,
        cache_key: str,
        file_path: str,
        file_hash: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            self._cache.set(
                cache_key=cache_key,
                file_path=file_path,
                file_hash=file_hash,
                payload=payload,
            )
        except Exception as exc:
            logger.warning("Document cache write failed; returning fresh result: %s", exc)

    def _memory_cache_get(self, cache_key: str) -> dict[str, Any] | None:
        now = int(time.time())
        with self._memory_cache_lock:
            entry = self._memory_cache.get(cache_key)
            if entry is None:
                return None

            expires_at, payload = entry
            if expires_at <= now:
                self._memory_cache.pop(cache_key, None)
                return None

            self._memory_cache.move_to_end(cache_key)
            return dict(payload)

    def _memory_cache_set(self, cache_key: str, payload: dict[str, Any]) -> None:
        expires_at = int(time.time()) + self._memory_cache_ttl_seconds
        with self._memory_cache_lock:
            self._memory_cache[cache_key] = (expires_at, dict(payload))
            self._memory_cache.move_to_end(cache_key)
            while len(self._memory_cache) > self._memory_cache_max_entries:
                self._memory_cache.popitem(last=False)

    def _get_request_lock(self, cache_key: str) -> threading.Lock:
        with self._request_locks_lock:
            lock = self._request_locks.get(cache_key)
            if lock is None:
                lock = threading.Lock()
                self._request_locks[cache_key] = lock
            else:
                self._request_locks.move_to_end(cache_key)

            while len(self._request_locks) > self._request_locks_max_entries:
                oldest_key, oldest_lock = next(iter(self._request_locks.items()))
                if oldest_lock.locked():
                    self._request_locks.move_to_end(oldest_key)
                    break
                self._request_locks.popitem(last=False)

            return lock

    def _compute_file_hash_cached(self, validated_path: str) -> str:
        normalized_path = os.path.normcase(os.path.abspath(validated_path))
        stat = os.stat(validated_path)
        mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
        size = int(stat.st_size)

        with self._file_hash_cache_lock:
            cached = self._file_hash_cache.get(normalized_path)
            if cached is not None:
                cached_mtime_ns, cached_size, cached_hash = cached
                if cached_mtime_ns == mtime_ns and cached_size == size:
                    self._file_hash_cache.move_to_end(normalized_path)
                    return cached_hash

        file_hash = self._cache.compute_file_hash(validated_path)

        with self._file_hash_cache_lock:
            self._file_hash_cache[normalized_path] = (mtime_ns, size, file_hash)
            self._file_hash_cache.move_to_end(normalized_path)
            while len(self._file_hash_cache) > self._file_hash_cache_max_entries:
                self._file_hash_cache.popitem(last=False)

        return file_hash

    @staticmethod
    def _format_cache_hit(
        payload: dict[str, Any],
        *,
        validated_path: str,
        tier: str,
    ) -> dict[str, Any]:
        result = dict(payload)
        result["cache_hit"] = True
        result["cache_tier"] = tier
        result["file_path"] = validated_path
        result["file_name"] = Path(validated_path).name
        return result

    def analyze_for_display(self, file_path: str, *, user_query: str = "") -> str:
        """Analyze a document and return a human-readable summary string.

        Used by the runtime for direct speech/text output.
        """
        result = self.analyze(file_path, user_query=user_query)

        if not result.get("success"):
            detail = str(result.get("error") or result.get("summary") or "Unknown error").strip()
            return f"I could not analyze that document. {detail}."

        file_name = self._compact_text(str(result.get("file_name") or "Document"), max_chars=120)
        summary = self._compact_text(str(result.get("summary") or ""), max_chars=320)
        key_points = self._compact_list(result.get("key_points"), max_items=3, max_chars=140)
        insights = self._compact_list(result.get("insights"), max_items=2, max_chars=140)
        risks = self._compact_list(result.get("risks"), max_items=2, max_chars=120)
        entities = normalize_entities(result.get("entities"))
        tables = result.get("tables") if isinstance(result.get("tables"), list) else []

        lines: list[str] = [f"{file_name} — brief summary"]

        if summary:
            lines.append(summary)

        highlights = key_points or insights
        if highlights:
            lines.append("")
            lines.append("Highlights:")
            for item in highlights:
                lines.append(f"- {item}")

        if risks:
            lines.append("")
            lines.append(f"Caveats: {'; '.join(risks)}")

        entity_line = self._format_entities_compact(entities)
        if entity_line:
            lines.append("")
            lines.append("Entities: " + entity_line)

        if tables:
            lines.append("")
            lines.append(f"Tables extracted: {len(tables)}")

        return "\n".join(lines)

    @staticmethod
    def _compact_text(value: str, *, max_chars: int) -> str:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            return ""
        if len(cleaned) <= max_chars:
            return cleaned
        truncated = cleaned[:max_chars].rstrip(" ,.;:-")
        return truncated + "..."

    @classmethod
    def _compact_list(cls, value: Any, *, max_items: int, max_chars: int) -> list[str]:
        if not isinstance(value, list):
            return []

        output: list[str] = []
        seen: set[str] = set()
        for item in value:
            compact = cls._compact_text(str(item or ""), max_chars=max_chars)
            key = compact.lower()
            if not compact or key in seen:
                continue
            seen.add(key)
            output.append(compact)
            if len(output) >= max_items:
                break

        return output
