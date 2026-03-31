from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

try:
    from rapidfuzz import fuzz, process
except Exception:  # pragma: no cover - dependency handled at runtime
    fuzz = None  # type: ignore[assignment]
    process = None  # type: ignore[assignment]

try:
    import psutil
except Exception:  # pragma: no cover - dependency handled at runtime
    psutil = None  # type: ignore[assignment]


ResolverStatus = Literal["resolved", "ambiguous", "not_found"]


@dataclass(frozen=True)
class AppRecord:
    name: str
    app_id: str
    process_hints: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class ResolvedApp:
    app: str
    app_id: str
    confidence: float
    process_hints: tuple[str, ...]


@dataclass(frozen=True)
class ResolverDecision:
    status: ResolverStatus
    confidence: float
    match: ResolvedApp | None
    candidates: tuple[dict[str, Any], ...]


class AppResolver:
    """Resolve user app names using alias mapping, app index, fuzzy ranking, and thresholds."""

    _DEFAULT_ALIAS_MAP: dict[str, str] = {
        "browser": "chrome",
        "web browser": "chrome",
        "google chrome": "chrome",
        "chrome": "chrome",
        "coding": "code",
        "code": "code",
        "vscode": "code",
        "vs code": "code",
        "visual studio code": "code",
        "terminal": "wt",
        "windows terminal": "wt",
        "music": "spotify",
        "file manager": "explorer",
        "file explorer": "explorer",
        "windows explorer": "explorer",
        "explorer": "explorer",
    }

    _CANONICAL_PROCESS_HINTS: dict[str, tuple[str, ...]] = {
        "chrome": ("chrome",),
        "code": ("code",),
        "wt": ("wt", "windowsterminal"),
        "msedge": ("msedge",),
        "explorer": ("explorer", "fileexplorer"),
        "notepad": ("notepad",),
        "calc": ("calculator", "calc"),
        "spotify": ("spotify",),
    }
    _GENERIC_HINT_TOKENS: set[str] = {
        "app",
        "application",
        "apps",
        "windows",
        "microsoft",
        "file",
        "manager",
        "base",
        "launcher",
        "open",
    }

    def __init__(
        self,
        *,
        alias_map: dict[str, str] | None = None,
        registry_ttl_seconds: float = 300.0,
        now_fn: Callable[[], float] | None = None,
        start_apps_loader: Callable[[], list[AppRecord]] | None = None,
    ) -> None:
        self._alias_map = {
            self._normalize_text(key): self._normalize_text(value)
            for key, value in (alias_map or self._DEFAULT_ALIAS_MAP).items()
            if self._normalize_text(key) and self._normalize_text(value)
        }
        self._registry_ttl_seconds = max(30.0, float(registry_ttl_seconds))
        self._now_fn = now_fn or time.time
        self._start_apps_loader = start_apps_loader or self._load_start_apps_from_powershell

        self._cache_lock = threading.Lock()
        self._cached_records: list[AppRecord] = []
        self._cache_loaded_at: float = 0.0

    @property
    def fuzzy_available(self) -> bool:
        return bool(process is not None and fuzz is not None)

    def resolve(self, app_name: str) -> ResolverDecision:
        query = self._normalize_text(app_name)
        if not query:
            return ResolverDecision(status="not_found", confidence=0.0, match=None, candidates=())

        alias_target = self._alias_map.get(query, query)
        records = self._build_resolver_records()

        if self.fuzzy_available:
            scored_candidates = self._score_candidates(alias_target, records)
        else:
            scored_candidates = self._score_candidates_without_fuzzy(alias_target, records)
        return self._decide(alias_target, scored_candidates)

    def _score_candidates_without_fuzzy(self, query: str, records: list[AppRecord]) -> list[tuple[float, AppRecord]]:
        query_norm = self._normalize_text(query)
        query_compact = re.sub(r"[^a-z0-9]+", "", query_norm)
        ranked: list[tuple[float, AppRecord]] = []

        for record in records:
            name = self._normalize_text(record.name)
            app_id = self._normalize_text(record.app_id)
            name_compact = re.sub(r"[^a-z0-9]+", "", name)
            app_id_compact = re.sub(r"[^a-z0-9]+", "", app_id)

            score = 0.0
            if query_norm and (query_norm == name or query_norm == app_id):
                score = 100.0
            elif query_compact and (query_compact == name_compact or query_compact == app_id_compact):
                score = 95.0
            elif query_norm and (name.startswith(query_norm) or app_id.startswith(query_norm)):
                score = 88.0
            elif query_norm and (query_norm in name or query_norm in app_id):
                score = 78.0
            elif query_compact and (query_compact in name_compact or query_compact in app_id_compact):
                score = 74.0

            if score > 0:
                ranked.append((score, record))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[:5]

    def _build_resolver_records(self) -> list[AppRecord]:
        records = list(self._get_registry_records())

        # Add virtual canonical records so common aliases still work when
        # an app is absent from Start Menu indexing on a particular machine.
        existing_keys = {
            (self._normalize_text(record.name), self._normalize_text(record.app_id))
            for record in records
        }
        for canonical, hints in self._CANONICAL_PROCESS_HINTS.items():
            key = (self._normalize_text(canonical), "")
            if key in existing_keys:
                continue
            records.append(
                AppRecord(
                    name=canonical,
                    app_id="",
                    process_hints=tuple(hints),
                    source="canonical",
                )
            )
        return records

    def _get_registry_records(self) -> list[AppRecord]:
        now = float(self._now_fn())
        with self._cache_lock:
            if self._cached_records and (now - self._cache_loaded_at) < self._registry_ttl_seconds:
                return list(self._cached_records)

        loaded = self._safe_load_registry()
        with self._cache_lock:
            self._cached_records = loaded
            self._cache_loaded_at = now
            return list(self._cached_records)

    def _safe_load_registry(self) -> list[AppRecord]:
        try:
            loaded = self._start_apps_loader()
        except Exception:
            loaded = []

        deduped: list[AppRecord] = []
        seen: set[tuple[str, str]] = set()
        for item in loaded:
            key = (self._normalize_text(item.name), self._normalize_text(item.app_id))
            if not key[0] and not key[1]:
                continue
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _score_candidates(self, query: str, records: list[AppRecord]) -> list[tuple[float, AppRecord]]:
        if not self.fuzzy_available:
            return []

        choice_to_record: dict[str, AppRecord] = {}
        for record in records:
            name = self._normalize_text(record.name)
            app_id = self._normalize_text(record.app_id)
            if name:
                choice_to_record[f"name::{name}"] = record
            if app_id:
                choice_to_record[f"id::{app_id}"] = record

        if not choice_to_record:
            return []

        extracted = process.extract(  # type: ignore[union-attr]
            query,
            list(choice_to_record.keys()),
            scorer=fuzz.WRatio,  # type: ignore[union-attr]
            limit=10,
        )

        best_by_record: dict[tuple[str, str], float] = {}
        for candidate_text, score, _ in extracted:
            record = choice_to_record.get(str(candidate_text) or "")
            if record is None:
                continue
            key = (self._normalize_text(record.name), self._normalize_text(record.app_id))
            best_by_record[key] = max(float(score), best_by_record.get(key, 0.0))

        ranked: list[tuple[float, AppRecord]] = []
        lookup = {
            (self._normalize_text(record.name), self._normalize_text(record.app_id)): record
            for record in records
        }
        for key, score in best_by_record.items():
            record = lookup.get(key)
            if record is None:
                continue
            ranked.append((float(score), record))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[:5]

    def _decide(self, query: str, ranked: list[tuple[float, AppRecord]]) -> ResolverDecision:
        if not ranked:
            return ResolverDecision(status="not_found", confidence=0.0, match=None, candidates=())

        top_score, top_record = ranked[0]
        candidates = tuple(
            {
                "app": record.name,
                "confidence": round(float(score), 2),
                "app_id": record.app_id,
            }
            for score, record in ranked[:5]
        )

        if top_score > 85.0:
            enriched_hints = self._merge_process_hints(top_record.process_hints, query)
            return ResolverDecision(
                status="resolved",
                confidence=float(top_score),
                match=ResolvedApp(
                    app=top_record.name,
                    app_id=top_record.app_id,
                    confidence=float(top_score),
                    process_hints=enriched_hints,
                ),
                candidates=candidates,
            )

        if top_score >= 70.0:
            return ResolverDecision(
                status="ambiguous",
                confidence=float(top_score),
                match=None,
                candidates=candidates,
            )

        return ResolverDecision(status="not_found", confidence=float(top_score), match=None, candidates=candidates)

    def _merge_process_hints(self, base_hints: tuple[str, ...], query: str) -> tuple[str, ...]:
        seeds: list[str] = [*base_hints]
        normalized_query = self._normalize_text(query)
        if normalized_query:
            seeds.append(normalized_query)
            seeds.extend(re.split(r"[^a-z0-9]+", normalized_query))

        for canonical, canonical_hints in self._CANONICAL_PROCESS_HINTS.items():
            if canonical in normalized_query:
                seeds.extend(canonical_hints)

        merged: list[str] = []
        seen: set[str] = set()
        for hint in seeds:
            normalized = self._normalize_text(hint).replace(".exe", "")
            if not normalized:
                continue

            variants = [normalized]
            compact = re.sub(r"[^a-z0-9]+", "", normalized)
            if compact:
                variants.append(compact)

            for variant in variants:
                if not self._is_useful_hint(variant):
                    continue
                if variant in seen:
                    continue
                seen.add(variant)
                merged.append(variant)
                if len(merged) >= 8:
                    return tuple(merged)

        return tuple(merged)

    def _load_start_apps_from_powershell(self) -> list[AppRecord]:
        if os.name != "nt":
            return []

        payload: Any | None = None
        for shell in self._candidate_shells():
            command = [
                shell,
                "-NoProfile",
                "-Command",
                "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Depth 3",
            ]
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
            except Exception:
                continue

            if int(proc.returncode) != 0:
                continue

            payload = self._parse_json(proc.stdout)
            if payload is not None:
                break

        if payload is None:
            return []

        rows: list[dict[str, Any]]
        if isinstance(payload, dict):
            rows = [payload]
        elif isinstance(payload, list):
            rows = [item for item in payload if isinstance(item, dict)]
        else:
            rows = []

        records: list[AppRecord] = []
        for item in rows:
            name = str(item.get("Name") or item.get("name") or "").strip()
            app_id = str(item.get("AppID") or item.get("AppId") or item.get("app_id") or "").strip()
            if not name and not app_id:
                continue
            process_hints = self._derive_process_hints(name=name, app_id=app_id)
            records.append(
                AppRecord(
                    name=name or app_id,
                    app_id=app_id,
                    process_hints=process_hints,
                    source="start_apps",
                )
            )
        return records

    @staticmethod
    def _parse_json(raw: str) -> Any | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    def _derive_process_hints(self, *, name: str, app_id: str) -> tuple[str, ...]:
        hints: list[str] = []

        name_tokens = re.findall(r"[a-z0-9]+", self._normalize_text(name))
        if name_tokens:
            hints.append("".join(name_tokens))
            hints.extend(name_tokens[:4])

        app_id_clean = self._normalize_text(app_id)
        if app_id_clean:
            app_id_base = app_id_clean.split("!", maxsplit=1)[0]
            app_id_base = app_id_base.split("_", maxsplit=1)[0]
            app_id_parts = [part for part in re.split(r"[^a-z0-9]+", app_id_base) if part]
            if app_id_parts:
                hints.append(app_id_parts[-1])
            if app_id_base:
                hints.append(app_id_base)

        normalized_name = self._normalize_text(name)
        normalized_app_id = self._normalize_text(app_id)
        compact_blob = re.sub(r"[^a-z0-9]+", "", f"{normalized_name} {normalized_app_id}")
        for canonical, canonical_hints in self._CANONICAL_PROCESS_HINTS.items():
            if canonical in normalized_name or canonical in normalized_app_id or canonical in compact_blob:
                hints.extend(canonical_hints)

        deduped: list[str] = []
        seen: set[str] = set()
        for hint in hints:
            normalized = self._normalize_text(hint).replace(".exe", "")
            if not self._is_useful_hint(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
            if len(deduped) >= 5:
                break
        return tuple(deduped)

    @classmethod
    def _is_useful_hint(cls, hint: str) -> bool:
        normalized = cls._normalize_text(hint)
        if len(normalized) < 3:
            return False
        if normalized in cls._GENERIC_HINT_TOKENS:
            return False
        return True

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    @staticmethod
    def _candidate_shells() -> tuple[str, ...]:
        shells: list[str] = []
        for name in ("powershell", "pwsh"):
            if shutil.which(name):
                shells.append(name)
        if not shells:
            shells.append("powershell")
        return tuple(shells)


class AppExecutor:
    """Execute open/close actions and verify process-level truth."""

    def __init__(
        self,
        resolver: AppResolver,
        *,
        verify_timeout_seconds: float = 15.0,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._resolver = resolver
        self._verify_timeout_seconds = max(2.0, float(verify_timeout_seconds))
        self._poll_interval_seconds = max(0.2, float(poll_interval_seconds))

    def execute(self, *, action: str, app_name: str) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"open", "close"}:
            return self._error_payload("execution_failed")

        decision = self._resolver.resolve(app_name)
        if decision.status == "ambiguous":
            return {
                "status": "ambiguous",
                "candidates": list(decision.candidates),
            }
        if decision.status != "resolved" or decision.match is None:
            return self._error_payload("not_found")

        if os.name != "nt":
            return self._error_payload("execution_failed")
        if psutil is None:
            return self._error_payload("execution_failed")

        if normalized_action == "open":
            return self._open_app(decision.match)
        return self._close_app(decision.match)

    def _open_app(self, match: ResolvedApp) -> dict[str, Any]:
        baseline = self._snapshot_matching_pids(match.process_hints)
        if not self._launch_app(match):
            return self._error_payload("execution_failed")

        verified = self._wait_for_open_verification(match.process_hints, baseline)
        if not verified:
            return self._error_payload("execution_failed")

        return {
            "status": "success",
            "action": "open",
            "app": match.app,
            "verified": True,
            "confidence": round(float(match.confidence), 2),
        }

    def _close_app(self, match: ResolvedApp) -> dict[str, Any]:
        targets = self._find_matching_processes(match.process_hints)

        # Already not running is still a valid closed state after verification.
        if not targets:
            if self._wait_for_closed_verification(match.process_hints):
                return {
                    "status": "success",
                    "action": "close",
                    "app": match.app,
                    "verified": True,
                    "confidence": round(float(match.confidence), 2),
                }
            return self._error_payload("execution_failed")

        for proc in targets:
            try:
                if int(proc.pid) == int(os.getpid()):
                    continue
                proc.terminate()
            except Exception:
                continue

        _, alive = psutil.wait_procs(targets, timeout=3)  # type: ignore[union-attr]
        for proc in alive:
            try:
                proc.kill()
            except Exception:
                continue

        if not self._wait_for_closed_verification(match.process_hints):
            return self._error_payload("execution_failed")

        return {
            "status": "success",
            "action": "close",
            "app": match.app,
            "verified": True,
            "confidence": round(float(match.confidence), 2),
        }

    def _launch_app(self, match: ResolvedApp) -> bool:
        commands = self._build_launch_commands(match)
        for cmd in commands:
            try:
                completed = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if int(completed.returncode) == 0:
                    return True
            except Exception:
                continue
        return False

    def _build_launch_commands(self, match: ResolvedApp) -> list[list[str]]:
        commands: list[list[str]] = []
        escaped_name = self._pwsh_escape(match.app)
        shell = self._preferred_shell()

        if match.app_id:
            escaped_id = self._pwsh_escape(match.app_id)
            commands.append(
                [
                    shell,
                    "-NoProfile",
                    "-Command",
                    (
                        f"$appId='{escaped_id}';"
                        "Start-Process explorer.exe ('shell:AppsFolder\\' + $appId)"
                    ),
                ]
            )

        commands.append(
            [
                shell,
                "-NoProfile",
                "-Command",
                f"Start-Process -FilePath '{escaped_name}'",
            ]
        )

        # Last fallback: execute by first process hint (useful for common apps).
        if match.process_hints:
            escaped_hint = self._pwsh_escape(match.process_hints[0])
            commands.append(
                [
                    shell,
                    "-NoProfile",
                    "-Command",
                    f"Start-Process -FilePath '{escaped_hint}'",
                ]
            )

        return commands

    def _wait_for_open_verification(self, hints: tuple[str, ...], baseline: set[int]) -> bool:
        deadline = time.time() + self._verify_timeout_seconds
        while time.time() < deadline:
            current = self._snapshot_matching_pids(hints)
            if current:
                # Either a new process appeared or one already existed and still exists.
                if current.difference(baseline) or current:
                    return True
            time.sleep(self._poll_interval_seconds)
        return False

    def _wait_for_closed_verification(self, hints: tuple[str, ...]) -> bool:
        deadline = time.time() + self._verify_timeout_seconds
        while time.time() < deadline:
            if not self._snapshot_matching_pids(hints):
                return True
            time.sleep(self._poll_interval_seconds)
        return False

    def _snapshot_matching_pids(self, hints: tuple[str, ...]) -> set[int]:
        return {int(proc.pid) for proc in self._find_matching_processes(hints)}

    def _find_matching_processes(self, hints: tuple[str, ...]) -> list[Any]:
        if psutil is None:
            return []

        normalized_hints = {
            self._normalize_process_name(hint)
            for hint in hints
            if self._normalize_process_name(hint)
        }
        if not normalized_hints:
            return []

        matches: list[Any] = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):  # type: ignore[union-attr]
            try:
                proc_name = self._normalize_process_name(str(proc.info.get("name") or ""))
                proc_exe = self._normalize_process_name(Path(str(proc.info.get("exe") or "")).name)
                if self._matches_any_hint(proc_name, normalized_hints) or self._matches_any_hint(proc_exe, normalized_hints):
                    matches.append(proc)
            except Exception:
                continue
        return matches

    @staticmethod
    def _matches_any_hint(process_name: str, hints: set[str]) -> bool:
        if not process_name:
            return False
        compact_process = re.sub(r"[^a-z0-9]+", "", process_name)
        for hint in hints:
            compact_hint = re.sub(r"[^a-z0-9]+", "", hint)

            if process_name == hint:
                return True
            if compact_hint and compact_process == compact_hint:
                return True

            if process_name.startswith(hint):
                return True
            if compact_hint and compact_process.startswith(compact_hint):
                return True

            # Restrict broad substring matching for short hints to reduce
            # accidental matches when closing processes.
            if len(hint) >= 6 and hint in process_name:
                return True
            if compact_hint and len(compact_hint) >= 6 and compact_hint in compact_process:
                return True
        return False

    @staticmethod
    def _normalize_process_name(value: str) -> str:
        lowered = str(value or "").strip().lower()
        if lowered.endswith(".exe"):
            lowered = lowered[:-4]
        return lowered

    @staticmethod
    def _pwsh_escape(value: str) -> str:
        return str(value or "").replace("'", "''")

    @staticmethod
    def _error_payload(reason: Literal["not_found", "execution_failed"]) -> dict[str, Any]:
        return {
            "status": "error",
            "reason": reason,
        }

    @staticmethod
    def _preferred_shell() -> str:
        if shutil.which("powershell"):
            return "powershell"
        if shutil.which("pwsh"):
            return "pwsh"
        return "powershell"


class AppControlService:
    """Deterministic facade exposed to tool registry."""

    _MEMORY_KEY = "last_opened_app"
    _PRONOUNS = {
        "it",
        "that",
        "this",
        "that app",
        "this app",
        "the app",
        "same app",
    }

    def __init__(
        self,
        *,
        memory_store: Any | None = None,
        resolver: AppResolver | None = None,
        executor: AppExecutor | None = None,
    ) -> None:
        self._memory = memory_store
        self._in_memory_last_app = ""
        self._resolver = resolver or AppResolver()
        self._executor = executor or AppExecutor(self._resolver)

    def control(self, *, action: str, app_name: str) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"open", "close"}:
            return {"status": "error", "reason": "execution_failed"}

        requested_app = str(app_name or "").strip()
        target_app = requested_app

        if normalized_action == "close" and (not requested_app or self._is_pronoun(requested_app)):
            remembered = self._get_last_opened_app()
            if not remembered:
                return {"status": "error", "reason": "not_found"}
            target_app = remembered
        elif normalized_action == "open" and not requested_app:
            return {"status": "error", "reason": "not_found"}

        outcome = self._executor.execute(action=normalized_action, app_name=target_app)

        if outcome.get("status") == "success" and bool(outcome.get("verified")):
            final_app = str(outcome.get("app") or target_app).strip()
            if normalized_action == "open" and final_app:
                self._set_last_opened_app(final_app)
            if normalized_action == "close":
                remembered = self._get_last_opened_app()
                if remembered and self._normalize_text(remembered) == self._normalize_text(final_app):
                    self._clear_last_opened_app()

        return outcome

    def _get_last_opened_app(self) -> str:
        if self._memory is not None and hasattr(self._memory, "get"):
            try:
                value = str(self._memory.get(self._MEMORY_KEY) or "").strip()
                if value:
                    return value
            except Exception:
                pass
        return self._in_memory_last_app

    def _set_last_opened_app(self, app: str) -> None:
        self._in_memory_last_app = str(app or "").strip()
        if self._memory is not None and hasattr(self._memory, "set"):
            try:
                self._memory.set(self._MEMORY_KEY, self._in_memory_last_app)
            except Exception:
                pass

    def _clear_last_opened_app(self) -> None:
        self._in_memory_last_app = ""
        if self._memory is not None and hasattr(self._memory, "delete"):
            try:
                self._memory.delete(self._MEMORY_KEY)
                return
            except Exception:
                pass
        if self._memory is not None and hasattr(self._memory, "set"):
            try:
                self._memory.set(self._MEMORY_KEY, "")
            except Exception:
                pass

    @classmethod
    def _is_pronoun(cls, value: str) -> bool:
        normalized = cls._normalize_text(value)
        return normalized in cls._PRONOUNS

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())
