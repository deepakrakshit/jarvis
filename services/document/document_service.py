"""Document Service — JARVIS integration entry point.

This is the primary interface between the JARVIS agent system and the
Document Intelligence pipeline. It handles the full lifecycle:
  file validation → pipeline execution → structured result formatting.
"""

from __future__ import annotations

import os
import hashlib
import logging
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from core.settings import AppConfig
from services.document.cache_store import DocumentCacheStore, build_default_cache_config
from services.document.file_selector import validate_file_path
from services.document.llm_client import DocumentLLMClient
from services.document.models import PipelineProgress
from services.document.pipeline import DocumentPipeline

logger = logging.getLogger(__name__)


class DocumentService:
    """Top-level document intelligence service for JARVIS.

    Usage:
        service = DocumentService(config)
        result = service.analyze(file_path)
    """

    PIPELINE_VERSION = "document_pipeline_v4_hybrid"

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._fast_model = config.groq_model
        self._deep_model = getattr(config, "document_deep_model", "llama-3.3-70b-versatile")
        self._llm_client = DocumentLLMClient(
            api_key=config.groq_api_key,
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
            logger.warning("Document validation failed: %s", error)
            return {
                "success": False,
                "error": error,
                "summary": "",
                "insights": [],
                "tables": [],
                "key_points": [],
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
                return self._format_cache_hit(memory_hit, validated_path=validated_path, tier="memory")

            request_lock = self._get_request_lock(cache_key)
            with request_lock:
                memory_hit = self._memory_cache_get(cache_key)
                if isinstance(memory_hit, dict) and memory_hit.get("success"):
                    return self._format_cache_hit(memory_hit, validated_path=validated_path, tier="memory")

                persistent_hit = self._persistent_cache_get(cache_key)
                if isinstance(persistent_hit, dict) and persistent_hit.get("success"):
                    self._memory_cache_set(cache_key, persistent_hit)
                    return self._format_cache_hit(persistent_hit, validated_path=validated_path, tier="persistent")

                result = self._compute_result(validated_path)
                if result.get("success") and file_hash and self._should_cache_result(result):
                    self._persistent_cache_set(
                        cache_key=cache_key,
                        file_path=validated_path,
                        file_hash=file_hash,
                        payload=result,
                    )
                    self._memory_cache_set(cache_key, result)
                return result

        return self._compute_result(validated_path)

    @staticmethod
    def _should_cache_result(result: dict[str, Any]) -> bool:
        """Skip cache writes for transient or environment-related degraded outputs."""
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        vision_error = str(metadata.get("vision_error") or "").strip().lower()
        if vision_error in {"openrouter_api_key_missing", "openrouter_http_429"}:
            return False

        risks = result.get("risks") if isinstance(result.get("risks"), list) else []
        normalized_risks = [str(item or "").strip().lower() for item in risks]
        if any(
            "openrouter api key is missing" in item or "openrouter_http_429" in item
            for item in normalized_risks
        ):
            return False

        summary = str(result.get("summary") or "").strip().lower()
        if "missing openrouter api key" in summary:
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
        query_fingerprint = hashlib.sha256((user_query or "").strip().lower().encode("utf-8")).hexdigest()
        cache_key = self._cache.build_cache_key(
            file_hash=file_hash,
            pipeline_version=f"{self.PIPELINE_VERSION}:{sys.version_info.major}.{sys.version_info.minor}",
            fast_model=self._fast_model,
            deep_model=self._deep_model,
            query_fingerprint=query_fingerprint,
        )
        return cache_key, file_hash

    def _compute_result(self, validated_path: str) -> dict[str, Any]:
        progress = PipelineProgress()

        logger.info("Starting document analysis: %s", validated_path)

        try:
            intelligence = self._pipeline.process(
                validated_path,
                progress=progress,
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
