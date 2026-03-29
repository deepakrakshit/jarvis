"""SQLite-backed cache for document intelligence results.

Design goals:
- Fast deterministic lookups keyed by file content hash + pipeline fingerprint.
- Safe operation in desktop/runtime environments (thread lock + atomic commits).
- Bounded growth using TTL cleanup and max-entry pruning.
- Fail-open behavior: cache failures must never break document analysis.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS document_cache (
    cache_key TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_cache_expires_at
ON document_cache(expires_at);

CREATE INDEX IF NOT EXISTS idx_document_cache_created_at
ON document_cache(created_at);
"""


@dataclass(frozen=True)
class DocumentCacheConfig:
    enabled: bool
    db_path: str
    ttl_seconds: int
    max_entries: int


class DocumentCacheStore:
    """Production-oriented cache store for document intelligence payloads."""

    def __init__(self, config: DocumentCacheConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._initialized = False
        self._thread_local = threading.local()

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    def build_cache_key(
        self,
        *,
        file_hash: str,
        pipeline_version: str,
        fast_model: str,
        deep_model: str,
        query_fingerprint: str = "",
    ) -> str:
        """Create deterministic cache key for a file and processing fingerprint."""
        raw = "|".join(
            [
                file_hash,
                pipeline_version,
                fast_model,
                deep_model,
                query_fingerprint,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """Compute a stable sha256 hash from file bytes."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                block = f.read(1024 * 1024)
                if not block:
                    break
                h.update(block)
        return h.hexdigest()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Fetch cached payload by key if present and not expired."""
        if not self.enabled:
            return None

        self._ensure_initialized()

        now = int(time.time())
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT expires_at, payload_json FROM document_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if row is None:
                    return None

                expires_at, payload_json = int(row[0]), str(row[1])
                if expires_at <= now:
                    conn.execute(
                        "DELETE FROM document_cache WHERE cache_key = ?",
                        (cache_key,),
                    )
                    conn.commit()
                    return None

                parsed = json.loads(payload_json)
                if isinstance(parsed, dict):
                    return parsed
                return None

    def set(
        self,
        *,
        cache_key: str,
        file_path: str,
        file_hash: str,
        payload: dict[str, Any],
    ) -> None:
        """Store payload and prune old entries to keep cache bounded."""
        if not self.enabled:
            return

        self._ensure_initialized()

        now = int(time.time())
        expires_at = now + max(1, int(self._config.ttl_seconds))
        payload_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO document_cache
                    (cache_key, created_at, expires_at, file_path, file_hash, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at,
                        file_path = excluded.file_path,
                        file_hash = excluded.file_hash,
                        payload_json = excluded.payload_json
                    """,
                    (
                        cache_key,
                        now,
                        expires_at,
                        file_path,
                        file_hash,
                        payload_json,
                    ),
                )

                # Remove expired rows first, then bound row count.
                conn.execute("DELETE FROM document_cache WHERE expires_at <= ?", (now,))
                self._prune_if_needed(conn)
                conn.commit()

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return
            db_path = Path(self._config.db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            with self._connect() as conn:
                conn.executescript(_SCHEMA_SQL)
                conn.commit()

            self._initialized = True

    def _prune_if_needed(self, conn: sqlite3.Connection) -> None:
        max_entries = max(1, int(self._config.max_entries))
        row = conn.execute("SELECT COUNT(1) FROM document_cache").fetchone()
        count = int(row[0]) if row else 0
        if count <= max_entries:
            return

        to_delete = count - max_entries
        conn.execute(
            """
            DELETE FROM document_cache
            WHERE cache_key IN (
                SELECT cache_key FROM document_cache
                ORDER BY created_at ASC
                LIMIT ?
            )
            """,
            (to_delete,),
        )

    def _connect(self) -> sqlite3.Connection:
        # Keep one connection per thread to reduce open/close overhead on hot cache paths.
        conn = getattr(self._thread_local, "conn", None)
        if isinstance(conn, sqlite3.Connection):
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                try:
                    conn.close()
                except Exception:
                    pass

        # check_same_thread=False to permit service calls across worker threads.
        conn = sqlite3.connect(self._config.db_path, timeout=10.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._thread_local.conn = conn
        return conn


def build_default_cache_config(
    *,
    enabled: bool,
    db_path: str,
    ttl_seconds: int,
    max_entries: int,
) -> DocumentCacheConfig:
    """Normalize default cache config values."""
    resolved = os.path.abspath(db_path)
    return DocumentCacheConfig(
        enabled=enabled,
        db_path=resolved,
        ttl_seconds=max(60, int(ttl_seconds)),
        max_entries=max(16, int(max_entries)),
    )
