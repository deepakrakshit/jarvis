# ==============================================================================
# File: services/actions/file_controller.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Enterprise File Controller
#
#    - Structured file/folder operations with safety guardrails.
#    - Supports find, list, open, close, read, write, append, replace, move,
#      copy, remove, mkdir, and touch operations.
#    - Uses atomic writes for edit operations to reduce corruption risk.
#    - Enforces protected-path checks for destructive actions.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import os
import re
import secrets
import shutil
import string
import tempfile
import time
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileControllerPolicy:
    max_read_bytes: int = 2_000_000
    max_write_bytes: int = 3_000_000
    max_find_results: int = 120
    max_list_results: int = 300
    max_bulk_create_files: int = 500
    enforce_workspace_boundary: bool = True
    allow_symlink_escape: bool = False
    protected_roots: tuple[str, ...] = (
        "C:/Windows",
        "C:/Program Files",
        "C:/Program Files (x86)",
        "C:/ProgramData",
        "C:/Users/Default",
    )


_LOOKUP_STOPWORDS: set[str] = {
    "open",
    "the",
    "a",
    "an",
    "from",
    "in",
    "on",
    "of",
    "to",
    "please",
    "folder",
    "directory",
    "file",
    "files",
    "my",
    "me",
    "for",
    "and",
    "with",
}

_SKIP_DIR_NAMES: set[str] = {
    "$recycle.bin",
    "system volume information",
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
}

_VIDEO_EXTENSIONS: set[str] = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".webm",
    ".m4v",
}

_AUDIO_EXTENSIONS: set[str] = {
    ".mp3",
    ".wav",
    ".flac",
    ".aac",
    ".ogg",
    ".m4a",
}

_IMAGE_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".webp",
}


class FileController:
    """High-capability file operation service with guardrails."""

    def __init__(self, *, workspace_root: str, policy: FileControllerPolicy | None = None) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._policy = policy or FileControllerPolicy()
        self._protected_roots = tuple(self._resolve_protected_roots())

    def list_entries(
        self,
        *,
        path: str = ".",
        include_hidden: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        target = self._resolve_path(path, allow_missing=False)
        if target is None or not target.exists() or not target.is_dir():
            return self._error("invalid_path", f"Directory not found: {path}")

        entries: list[dict[str, Any]] = []
        max_results = max(1, min(int(limit or self._policy.max_list_results), self._policy.max_list_results))
        truncated = False
        try:
            for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if not include_hidden and item.name.startswith("."):
                    continue
                entries.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "kind": "file" if item.is_file() else "dir",
                        "size": int(item.stat().st_size) if item.is_file() else None,
                    }
                )
                if len(entries) >= max_results:
                    truncated = True
                    break
            return self._ok(
                action="list",
                message=f"Listed {len(entries)} entries.",
                data={
                    "path": str(target),
                    "entries": entries,
                    "truncated": truncated,
                },
            )
        except Exception as exc:
            return self._error("list_failed", f"Could not list directory: {exc}")

    def find(
        self,
        *,
        query: str,
        start_path: str = ".",
        include_hidden: bool = False,
        kind: str = "both",
        limit: int | None = None,
    ) -> dict[str, Any]:
        root = self._resolve_path(start_path, allow_missing=False)
        if root is None or not root.exists() or not root.is_dir():
            return self._error("invalid_path", f"Search root not found: {start_path}")

        text = str(query or "").strip().lower()
        if not text:
            return self._error("missing_query", "Find query is empty.")

        max_results = max(1, min(int(limit or self._policy.max_find_results), self._policy.max_find_results))
        hits: list[dict[str, Any]] = []

        try:
            for current_root, dir_names, file_names in os.walk(root):
                current = Path(current_root)
                if not include_hidden:
                    dir_names[:] = [name for name in dir_names if not name.startswith(".")]

                names: list[tuple[str, str]] = []
                if kind in {"both", "dir", "folder"}:
                    names.extend(("dir", name) for name in dir_names)
                if kind in {"both", "file"}:
                    names.extend(("file", name) for name in file_names)

                for entry_kind, name in names:
                    if not include_hidden and name.startswith("."):
                        continue
                    candidate = current / name
                    if text in name.lower() or text in str(candidate).lower():
                        hits.append(
                            {
                                "name": name,
                                "path": str(candidate),
                                "kind": entry_kind,
                            }
                        )
                        if len(hits) >= max_results:
                            return self._ok(
                                action="find",
                                message=f"Found {len(hits)} matching entries.",
                                data={"query": query, "results": hits, "truncated": True},
                            )

            return self._ok(
                action="find",
                message=f"Found {len(hits)} matching entries.",
                data={"query": query, "results": hits, "truncated": False},
            )
        except Exception as exc:
            return self._error("find_failed", f"Search failed: {exc}")

    def read_text(self, *, path: str, encoding: str = "utf-8") -> dict[str, Any]:
        target = self._resolve_path(path, allow_missing=False)
        if target is None or not target.exists() or not target.is_file():
            return self._error("invalid_path", f"File not found: {path}")

        try:
            size = int(target.stat().st_size)
            if size > self._policy.max_read_bytes:
                return self._error(
                    "file_too_large",
                    f"File exceeds read limit ({self._policy.max_read_bytes} bytes).",
                )
            content = target.read_text(encoding=encoding)
            return self._ok(
                action="read",
                message="File read successfully.",
                data={"path": str(target), "content": content, "size": size},
            )
        except UnicodeDecodeError:
            return self._error("decode_error", "File is not valid text for requested encoding.")
        except Exception as exc:
            return self._error("read_failed", f"File read failed: {exc}")

    def write_text(
        self,
        *,
        path: str,
        content: str,
        append: bool = False,
        encoding: str = "utf-8",
        create_parents: bool = True,
    ) -> dict[str, Any]:
        target = self._resolve_path(path, allow_missing=True)
        if target is None:
            return self._error("invalid_path", f"Invalid file path: {path}")

        payload = str(content or "")
        if len(payload.encode(encoding, errors="ignore")) > self._policy.max_write_bytes:
            return self._error(
                "payload_too_large",
                f"Content exceeds write limit ({self._policy.max_write_bytes} bytes).",
            )

        parent = target.parent
        if create_parents:
            parent.mkdir(parents=True, exist_ok=True)
        elif not parent.exists():
            return self._error("parent_missing", f"Parent directory does not exist: {parent}")

        try:
            if append:
                with target.open("a", encoding=encoding) as handle:
                    handle.write(payload)
            else:
                self._atomic_write(target, payload, encoding=encoding)
            return self._ok(
                action="append" if append else "write",
                message="File updated successfully.",
                data={"path": str(target), "bytes_written": len(payload.encode(encoding, errors="ignore"))},
            )
        except Exception as exc:
            return self._error("write_failed", f"File write failed: {exc}")

    def replace_text(self, *, path: str, old_text: str, new_text: str, count: int = 0) -> dict[str, Any]:
        target = self._resolve_path(path, allow_missing=False)
        if target is None or not target.exists() or not target.is_file():
            return self._error("invalid_path", f"File not found: {path}")

        if old_text == "":
            return self._error("invalid_replace", "old_text cannot be empty.")

        try:
            content = target.read_text(encoding="utf-8")
            occurrences = content.count(old_text)
            if occurrences <= 0:
                return self._error("text_not_found", "Specified text was not found in file.")

            if count and count > 0:
                updated = content.replace(old_text, new_text, count)
                replaced = min(count, occurrences)
            else:
                updated = content.replace(old_text, new_text)
                replaced = occurrences

            self._atomic_write(target, updated, encoding="utf-8")
            return self._ok(
                action="replace",
                message=f"Replaced {replaced} occurrence(s).",
                data={"path": str(target), "replacements": replaced},
            )
        except Exception as exc:
            return self._error("replace_failed", f"Text replace failed: {exc}")

    def make_directory(self, *, path: str, exist_ok: bool = True) -> dict[str, Any]:
        target = self._resolve_path(path, allow_missing=True)
        if target is None:
            return self._error("invalid_path", f"Invalid directory path: {path}")

        try:
            target.mkdir(parents=True, exist_ok=bool(exist_ok))
            return self._ok(action="mkdir", message="Directory created.", data={"path": str(target)})
        except Exception as exc:
            return self._error("mkdir_failed", f"Directory create failed: {exc}")

    def touch(self, *, path: str) -> dict[str, Any]:
        target = self._resolve_path(path, allow_missing=True)
        if target is None:
            return self._error("invalid_path", f"Invalid file path: {path}")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
            return self._ok(action="touch", message="File created or updated.", data={"path": str(target)})
        except Exception as exc:
            return self._error("touch_failed", f"Touch failed: {exc}")

    def create_random_text_files(
        self,
        *,
        path: str,
        count: int,
        prefix: str = "file_",
        extension: str = ".txt",
        min_chars: int = 64,
        max_chars: int = 160,
        exact_chars: int | None = None,
        fill_to_count: bool = True,
        overwrite_existing: bool = False,
    ) -> dict[str, Any]:
        target_dir = self._resolve_path(path, allow_missing=True)
        if target_dir is None:
            return self._error("invalid_path", f"Invalid directory path: {path}")

        requested_count = int(count or 0)
        if requested_count <= 0:
            return self._error("invalid_count", "count must be greater than zero.")

        target_count = min(requested_count, int(self._policy.max_bulk_create_files))

        normalized_prefix = str(prefix or "file_").strip() or "file_"
        normalized_extension = str(extension or ".txt").strip() or ".txt"
        if not normalized_extension.startswith("."):
            normalized_extension = f".{normalized_extension}"

        max_allowed_chars = max(32, min(8192, int(self._policy.max_write_bytes)))
        if exact_chars is not None:
            exact_len = int(exact_chars)
            if exact_len <= 0:
                return self._error("invalid_exact_chars", "exact_chars must be greater than zero.")
            exact_len = min(exact_len, max_allowed_chars)
            min_len = exact_len
            max_len = exact_len
        else:
            min_len = max(8, min(int(min_chars or 64), max_allowed_chars))
            max_len = max(min_len, min(int(max_chars or 160), max_allowed_chars))

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return self._error("mkdir_failed", f"Directory create failed: {exc}")

        pattern = re.compile(
            rf"^{re.escape(normalized_prefix)}(\\d+)"
            rf"{re.escape(normalized_extension)}$",
            flags=re.IGNORECASE,
        )
        existing_indices: list[int] = []
        try:
            for item in target_dir.iterdir():
                if not item.is_file():
                    continue
                match = pattern.match(item.name)
                if not match:
                    continue
                try:
                    existing_indices.append(int(match.group(1)))
                except Exception:
                    continue
        except Exception as exc:
            return self._error("list_failed", f"Could not inspect target directory: {exc}")

        created_files: list[str] = []
        overwritten_files: list[str] = []
        skipped_existing: list[str] = []
        failures: list[dict[str, str]] = []

        if fill_to_count:
            target_indices = range(1, target_count + 1)
        else:
            start_index = (max(existing_indices) + 1) if existing_indices else 1
            target_indices = range(start_index, start_index + target_count)

        for index in target_indices:
            file_name = f"{normalized_prefix}{index:03d}{normalized_extension}"
            file_path = target_dir / file_name
            already_exists = file_path.exists()

            if already_exists and not overwrite_existing:
                skipped_existing.append(file_name)
                continue

            length = min_len
            if max_len > min_len:
                length = min_len + secrets.randbelow((max_len - min_len) + 1)
            payload = self._generate_random_text(length)

            try:
                self._atomic_write(file_path, payload, encoding="utf-8")
                if already_exists:
                    overwritten_files.append(file_name)
                else:
                    created_files.append(file_name)
            except Exception as exc:
                failures.append({"file": file_name, "error": str(exc)})

        if fill_to_count:
            total_available = 0
            for index in range(1, target_count + 1):
                expected_name = f"{normalized_prefix}{index:03d}{normalized_extension}"
                if (target_dir / expected_name).exists():
                    total_available += 1
        else:
            total_available = len(created_files) + len(overwritten_files)

        data = {
            "path": str(target_dir),
            "target_count": target_count,
            "created_count": len(created_files),
            "existing_count": len(skipped_existing),
            "overwritten_count": len(overwritten_files),
            "failed_count": len(failures),
            "total_available": total_available,
            "fill_to_count": bool(fill_to_count),
            "exact_chars": min_len if min_len == max_len else None,
            "created_files": created_files,
            "failures": failures,
        }

        if failures:
            return {
                "status": "error",
                "action": "create_random_text_files",
                "success": False,
                "verified": False,
                "error": "bulk_create_partial_failure",
                "message": (
                    "Random file generation completed with errors "
                    f"({len(failures)} failed, {len(created_files)} created)."
                ),
                "data": data,
            }

        if fill_to_count and total_available < target_count:
            return {
                "status": "error",
                "action": "create_random_text_files",
                "success": False,
                "verified": False,
                "error": "bulk_create_target_not_met",
                "message": (
                    "Random file generation completed but target count was not met "
                    f"({total_available}/{target_count})."
                ),
                "data": data,
            }

        return self._ok(
            action="create_random_text_files",
            message=(
                "Random file generation complete "
                f"({total_available}/{target_count} available, "
                f"created {len(created_files)}, existing {len(skipped_existing)})."
            ),
            data=data,
        )

    def filter_move_by_content(
        self,
        *,
        path: str,
        search_text: str,
        destination_subfolder: str = "Filtered",
        extension: str = ".txt",
        case_sensitive: bool = False,
        include_subdirs: bool = False,
    ) -> dict[str, Any]:
        source_dir = self._resolve_path(path, allow_missing=False)
        if source_dir is None or not source_dir.exists() or not source_dir.is_dir():
            return self._error("invalid_path", f"Directory not found: {path}")

        needle = str(search_text or "")
        if not needle:
            return self._error("missing_query", "search_text cannot be empty.")

        subfolder_text = str(destination_subfolder or "Filtered").strip().strip("\\/") or "Filtered"
        if Path(subfolder_text).is_absolute() or ".." in Path(subfolder_text).parts:
            return self._error("invalid_destination", "destination_subfolder must be a relative folder name.")

        destination_dir = (source_dir / subfolder_text).resolve()
        try:
            destination_dir.relative_to(source_dir.resolve())
        except Exception:
            return self._error("invalid_destination", "destination_subfolder must stay under source directory.")

        ext = str(extension or "").strip().lower()
        if ext and not ext.startswith("."):
            ext = f".{ext}"

        iterator = source_dir.rglob("*") if include_subdirs else source_dir.glob("*")
        moved_files: list[str] = []
        matched_files: list[str] = []
        failures: list[dict[str, str]] = []
        scanned = 0

        source_cmp = source_dir.resolve()
        destination_cmp = destination_dir
        needle_cmp = needle if case_sensitive else needle.lower()

        for candidate in iterator:
            try:
                if not candidate.is_file():
                    continue
                if destination_cmp in candidate.resolve().parents:
                    continue
                if ext and candidate.suffix.lower() != ext:
                    continue
            except Exception:
                continue

            scanned += 1
            try:
                raw = candidate.read_text(encoding="utf-8")
            except Exception:
                continue

            haystack = raw if case_sensitive else raw.lower()
            if needle_cmp not in haystack:
                continue

            matched_files.append(str(candidate))
            try:
                destination_dir.mkdir(parents=True, exist_ok=True)
                target = destination_dir / candidate.name
                if target.exists():
                    stem = target.stem
                    suffix = target.suffix
                    idx = 1
                    while True:
                        alt = destination_dir / f"{stem}_{idx:03d}{suffix}"
                        if not alt.exists():
                            target = alt
                            break
                        idx += 1
                shutil.move(str(candidate), str(target))
                moved_files.append(str(target))
            except Exception as exc:
                failures.append({"file": str(candidate), "error": str(exc)})

        success = not failures
        status = "success" if success else "error"
        message = (
            f"Moved {len(moved_files)} file(s) containing '{search_text}' to {destination_dir}."
            if success
            else f"Moved {len(moved_files)} file(s) but {len(failures)} move(s) failed."
        )
        return {
            "status": status,
            "action": "filter_move_by_content",
            "success": success,
            "verified": success,
            "error": "" if success else "partial_move_failed",
            "message": message,
            "data": {
                "path": str(source_cmp),
                "destination": str(destination_dir),
                "search_text": search_text,
                "scanned_files": scanned,
                "matched_count": len(matched_files),
                "moved_count": len(moved_files),
                "moved_files": moved_files,
                "failures": failures,
            },
        }

    def move(self, *, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
        src = self._resolve_path(source, allow_missing=False)
        dst = self._resolve_path(destination, allow_missing=True)
        if src is None or not src.exists():
            return self._error("invalid_source", f"Source not found: {source}")
        if dst is None:
            return self._error("invalid_destination", f"Invalid destination: {destination}")

        if dst.exists() and not overwrite:
            return self._error("destination_exists", f"Destination already exists: {dst}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return self._ok(
                action="move",
                message="Move completed.",
                data={"source": str(src), "destination": str(dst)},
            )
        except Exception as exc:
            return self._error("move_failed", f"Move failed: {exc}")

    def copy(self, *, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
        src = self._resolve_path(source, allow_missing=False)
        dst = self._resolve_path(destination, allow_missing=True)
        if src is None or not src.exists():
            return self._error("invalid_source", f"Source not found: {source}")
        if dst is None:
            return self._error("invalid_destination", f"Invalid destination: {destination}")

        if dst.exists() and not overwrite:
            return self._error("destination_exists", f"Destination already exists: {dst}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                if dst.exists() and overwrite:
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return self._ok(
                action="copy",
                message="Copy completed.",
                data={"source": str(src), "destination": str(dst)},
            )
        except Exception as exc:
            return self._error("copy_failed", f"Copy failed: {exc}")

    def remove(self, *, path: str, recursive: bool = False) -> dict[str, Any]:
        target = self._resolve_path(path, allow_missing=False)
        if target is None or not target.exists():
            return self._error("invalid_path", f"Path not found: {path}")

        if self._is_protected_for_delete(target):
            return self._error("protected_path", "Deletion blocked by safety policy.", details={"path": str(target)})

        try:
            if target.is_dir():
                if not recursive:
                    return self._error("requires_recursive", "Directory delete requires recursive=true.")
                shutil.rmtree(target)
            else:
                target.unlink()
            return self._ok(action="delete", message="Path removed.", data={"path": str(target)})
        except Exception as exc:
            return self._error("delete_failed", f"Delete failed: {exc}")

    def open_path(self, *, path: str, query: str = "") -> dict[str, Any]:
        raw_path = str(path or "").strip()
        raw_query = str(query or "").strip()

        direct_target = self._resolve_path(raw_path, allow_missing=False, allow_external=True)
        if direct_target is not None and direct_target.exists():
            if direct_target.is_dir() and raw_query:
                if not self._request_is_folder_only(raw_query):
                    best, suggestions = self._find_best_open_target(raw_query, roots=[direct_target])
                    if best is not None and best[1] >= 0.78:
                        return self._dispatch_open(
                            best[0],
                            message=f"Opened best match '{best[0].name}' from {direct_target}.",
                            data_extra={
                                "matched_query": raw_query,
                                "matched_path": str(best[0]),
                                "match_score": round(best[1], 3),
                                "search_root": str(direct_target),
                            },
                        )
                    if suggestions:
                        return self._suggest_open_candidate(raw_query, suggestions)

            return self._dispatch_open(direct_target, message="Open command sent.")

        request_text = self._extract_open_search_query(raw_path, raw_query)
        if not request_text:
            return self._open_error("invalid_path", f"Path not found: {path}")

        hinted_folder = self._resolve_named_folder_from_text(request_text)
        if hinted_folder is not None and hinted_folder.exists() and hinted_folder.is_dir() and self._request_is_folder_only(request_text):
            return self._dispatch_open(hinted_folder, message="Open command sent.")

        search_roots = self._candidate_search_roots(request_text)
        best_match, suggestions = self._find_best_open_target(request_text, roots=search_roots)
        if best_match is not None and best_match[1] >= 0.78:
            return self._dispatch_open(
                best_match[0],
                message=f"Opened best match for '{request_text}': {best_match[0].name}.",
                data_extra={
                    "matched_query": request_text,
                    "matched_path": str(best_match[0]),
                    "match_score": round(best_match[1], 3),
                    "search_roots": [str(root) for root in search_roots],
                },
            )

        if suggestions:
            return self._suggest_open_candidate(request_text, suggestions)

        return self._open_error(
            "invalid_path",
            f"I could not find a matching file for '{request_text}'.",
            data={"query": request_text, "search_roots": [str(root) for root in search_roots]},
        )

    def _dispatch_open(self, target: Path, *, message: str, data_extra: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            if os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif shutil.which("xdg-open"):
                import subprocess

                subprocess.Popen(["xdg-open", str(target)])
            elif shutil.which("open"):
                import subprocess

                subprocess.Popen(["open", str(target)])
            else:
                return self._open_error("open_unavailable", "No platform open command is available.")

            payload = {"path": str(target)}
            if isinstance(data_extra, dict):
                payload.update(data_extra)
            return self._ok(action="open", message=message, data=payload)
        except Exception as exc:
            return self._open_error("open_failed", f"Open failed: {exc}")

    def _candidate_search_roots(self, request_text: str) -> list[Path]:
        roots: list[Path] = []
        seen: set[str] = set()

        def _push(candidate: Path | None) -> None:
            if candidate is None:
                return
            try:
                resolved = candidate.expanduser().resolve(strict=False)
            except Exception:
                return
            if not resolved.exists() or not resolved.is_dir():
                return
            key = os.path.normcase(os.path.abspath(str(resolved)))
            if key in seen:
                return
            seen.add(key)
            roots.append(resolved)

        hinted = self._resolve_named_folder_from_text(request_text)
        _push(hinted)

        home = Path.home()
        _push(home / "Downloads")
        _push(home / "Desktop")
        _push(home / "Documents")
        _push(home / "Videos")
        _push(home / "Music")
        _push(self._workspace_root)

        return roots

    def _find_best_open_target(
        self,
        request_text: str,
        *,
        roots: list[Path],
        limit: int = 5,
        max_scan_files: int = 12000,
    ) -> tuple[tuple[Path, float] | None, list[tuple[Path, float]]]:
        query_tokens = self._tokenize_lookup_text(request_text)
        if not query_tokens:
            return None, []

        query_norm = " ".join(query_tokens)
        preferred_exts = self._infer_preferred_extensions(request_text)
        lowered_request = str(request_text or "").lower()

        scanned = 0
        ranked: list[tuple[Path, float]] = []
        for root in roots:
            if scanned >= max_scan_files:
                break
            try:
                for current_root, dir_names, file_names in os.walk(root):
                    dir_names[:] = [
                        name
                        for name in dir_names
                        if not name.startswith(".") and name.strip().lower() not in _SKIP_DIR_NAMES
                    ]

                    for file_name in file_names:
                        if scanned >= max_scan_files:
                            break
                        scanned += 1

                        candidate = Path(current_root) / file_name
                        suffix = candidate.suffix.lower()
                        if preferred_exts and suffix not in preferred_exts:
                            continue

                        score = self._score_open_candidate(
                            candidate,
                            query_tokens=query_tokens,
                            query_norm=query_norm,
                            preferred_exts=preferred_exts,
                            lowered_request=lowered_request,
                        )
                        if score < 0.34:
                            continue

                        ranked.append((candidate, score))
                        if len(ranked) > (limit * 15):
                            ranked = sorted(ranked, key=lambda item: item[1], reverse=True)[: limit * 15]
            except Exception:
                continue

        if not ranked:
            return None, []

        deduped: list[tuple[Path, float]] = []
        seen_paths: set[str] = set()
        for candidate, score in sorted(ranked, key=lambda item: item[1], reverse=True):
            key = os.path.normcase(os.path.abspath(str(candidate)))
            if key in seen_paths:
                continue
            seen_paths.add(key)
            deduped.append((candidate, score))
            if len(deduped) >= limit:
                break

        if not deduped:
            return None, []
        return deduped[0], deduped

    def _score_open_candidate(
        self,
        candidate: Path,
        *,
        query_tokens: list[str],
        query_norm: str,
        preferred_exts: set[str],
        lowered_request: str,
    ) -> float:
        candidate_tokens = self._tokenize_lookup_text(candidate.stem)
        if not candidate_tokens:
            return 0.0

        candidate_norm = " ".join(candidate_tokens)
        token_matches: list[float] = []
        for token in query_tokens:
            best = 0.0
            for cand in candidate_tokens:
                ratio = SequenceMatcher(None, token, cand).ratio()
                if ratio > best:
                    best = ratio
            token_matches.append(best)

        token_score = sum(token_matches) / max(1, len(token_matches))
        phrase_score = SequenceMatcher(None, query_norm, candidate_norm).ratio()
        substring_bonus = 0.12 if any(token in candidate_norm for token in query_tokens) else 0.0

        extension_bonus = 0.0
        if preferred_exts and candidate.suffix.lower() in preferred_exts:
            extension_bonus += 0.12

        location_bonus = 0.0
        candidate_path_text = str(candidate).lower()
        if "downloads" in lowered_request and "downloads" in candidate_path_text:
            location_bonus += 0.08
        if "desktop" in lowered_request and "desktop" in candidate_path_text:
            location_bonus += 0.06
        if "documents" in lowered_request and "documents" in candidate_path_text:
            location_bonus += 0.06
        if "videos" in lowered_request and "videos" in candidate_path_text:
            location_bonus += 0.06

        score = (0.58 * token_score) + (0.28 * phrase_score) + substring_bonus + extension_bonus + location_bonus
        return max(0.0, min(1.0, score))

    @staticmethod
    def _tokenize_lookup_text(text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
        return [token for token in tokens if token not in _LOOKUP_STOPWORDS and len(token) > 1]

    @staticmethod
    def _extract_open_search_query(path_text: str, query_text: str) -> str:
        query = str(query_text or "").strip()
        if query:
            return query
        return str(path_text or "").strip()

    @staticmethod
    def _resolve_named_folder_from_text(text: str) -> Path | None:
        lowered = str(text or "").lower()
        home = Path.home()
        if re.search(r"\bdownloads?\b", lowered):
            return home / "Downloads"
        if re.search(r"\bdesktop\b", lowered):
            return home / "Desktop"
        if re.search(r"\b(my\s+documents?|documents?)\b", lowered):
            return home / "Documents"
        if re.search(r"\bvideos?\b", lowered):
            return home / "Videos"
        if re.search(r"\bmusic\b", lowered):
            return home / "Music"
        if re.search(r"\b(pictures?|photos?)\b", lowered):
            return home / "Pictures"
        return None

    @staticmethod
    def _request_is_folder_only(text: str) -> bool:
        lowered = str(text or "").lower()
        if not lowered:
            return False
        if re.search(r"\.[a-z0-9]{2,6}\b", lowered):
            return False

        has_folder_target = bool(re.search(r"\b(downloads?|desktop|documents?|videos?|music|pictures?|photos?)\b", lowered))
        has_file_hint = bool(
            re.search(
                r"\b(movie|film|video|song|audio|presentation|ppt|pptx|pdf|doc|docx|xlsx|xls|txt|image|photo|picture|named|called)\b",
                lowered,
            )
        )
        return has_folder_target and not has_file_hint

    @staticmethod
    def _infer_preferred_extensions(text: str) -> set[str]:
        lowered = str(text or "").lower()
        if re.search(r"\b(movie|film|video|web[-\s]?dl|mkv|mp4)\b", lowered):
            return set(_VIDEO_EXTENSIONS)
        if re.search(r"\b(song|audio|music|mp3|wav|flac)\b", lowered):
            return set(_AUDIO_EXTENSIONS)
        if re.search(r"\b(image|photo|picture|jpg|jpeg|png|webp)\b", lowered):
            return set(_IMAGE_EXTENSIONS)
        if re.search(r"\b(presentation|slides|ppt|pptx)\b", lowered):
            return {".ppt", ".pptx"}
        if re.search(r"\b(pdf)\b", lowered):
            return {".pdf"}
        if re.search(r"\b(doc|docx|word)\b", lowered):
            return {".doc", ".docx"}
        if re.search(r"\b(xls|xlsx|excel|sheet|spreadsheet)\b", lowered):
            return {".xls", ".xlsx"}
        return set()

    def _suggest_open_candidate(self, query: str, suggestions: list[tuple[Path, float]]) -> dict[str, Any]:
        best_path, best_score = suggestions[0]
        top = [
            {
                "name": path.name,
                "path": str(path),
                "score": round(score, 3),
            }
            for path, score in suggestions[:5]
        ]
        message = (
            f"I could not find an exact file for '{query}'. Most related file is '{best_path.name}'. "
            f"If you want it, say: open \"{best_path}\"."
        )
        return self._open_error(
            "not_found_with_suggestion",
            message,
            data={
                "query": query,
                "best_match": str(best_path),
                "best_score": round(best_score, 3),
                "suggestions": top,
            },
        )

    @staticmethod
    def _open_error(error: str, message: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "status": "error",
            "action": "open",
            "success": False,
            "verified": False,
            "error": str(error or "open_failed"),
            "message": str(message or "Open request failed."),
            "data": data or {},
        }

    def close_path(self, *, path: str, app_control_service: Any | None = None) -> dict[str, Any]:
        if app_control_service is None or not hasattr(app_control_service, "control"):
            return self._error("close_unavailable", "close_path requires AppControlService integration.")

        target = self._resolve_path(path, allow_missing=True)
        app_name = target.stem if target is not None else Path(path).stem
        app_name = re.sub(r"\s+", " ", str(app_name or "").strip())
        if not app_name:
            return self._error("invalid_path", "Could not infer app name from path.")

        try:
            result = app_control_service.control(action="close", app_name=app_name)
            if isinstance(result, dict):
                success = str(result.get("status") or "").lower() == "success"
                return {
                    "status": "success" if success else "error",
                    "action": "close",
                    "success": success,
                    "verified": bool(result.get("verified", False)),
                    "error": "" if success else str(result.get("reason") or "close_failed"),
                    "message": str(result.get("message") or ("Close command sent." if success else "Close failed.")),
                    "data": {"path": path, "app_name": app_name, "result": result},
                }
            return self._error("close_failed", "App control returned an invalid payload.")
        except Exception as exc:
            return self._error("close_failed", f"Close failed: {exc}")

    def _resolve_path(self, raw_path: str, *, allow_missing: bool, allow_external: bool = False) -> Path | None:
        text = str(raw_path or "").strip()
        if not text:
            return None
        if "\x00" in text:
            return None

        try:
            candidate = Path(text).expanduser()
            if not candidate.is_absolute():
                candidate = (self._workspace_root / candidate).resolve(strict=False)
            else:
                candidate = candidate.resolve(strict=False)

            if self._policy.enforce_workspace_boundary and (not allow_external) and not self._is_under_workspace(candidate):
                return None

            if (
                not self._policy.allow_symlink_escape
                and candidate.exists()
                and candidate.is_symlink()
                and self._policy.enforce_workspace_boundary
                and (not allow_external)
            ):
                resolved_target = candidate.resolve(strict=False)
                if not self._is_under_workspace(resolved_target):
                    return None

            if not allow_missing and not candidate.exists():
                return None
            return candidate
        except Exception:
            return None

    def _is_under_workspace(self, candidate: Path) -> bool:
        try:
            candidate.resolve(strict=False).relative_to(self._workspace_root)
            return True
        except Exception:
            return False

    def _resolve_protected_roots(self) -> list[Path]:
        roots: list[Path] = []
        for item in self._policy.protected_roots:
            try:
                roots.append(Path(item).resolve(strict=False))
            except Exception:
                continue

        try:
            roots.append(Path(self._workspace_root.anchor or "/").resolve(strict=False))
        except Exception:
            pass
        return roots

    def _is_protected_for_delete(self, target: Path) -> bool:
        target_norm = target.resolve(strict=False)

        # Never allow deleting workspace root itself.
        if target_norm == self._workspace_root:
            return True

        # Block deletes on protected system paths and drive roots.
        for protected in self._protected_roots:
            try:
                if target_norm == protected:
                    return True
                target_norm.relative_to(protected)
                return True
            except ValueError:
                continue
            except Exception:
                continue

        return False

    @staticmethod
    def _atomic_write(path: Path, content: str, *, encoding: str) -> None:
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)

        last_error: Exception | None = None
        max_attempts = 4

        for attempt in range(max_attempts):
            temp_name = ""
            try:
                with tempfile.NamedTemporaryFile("w", delete=False, dir=str(parent), encoding=encoding) as temp_file:
                    temp_file.write(content)
                    temp_name = temp_file.name

                os.replace(temp_name, str(path))
                return
            except PermissionError as exc:
                last_error = exc

                # Some Windows handles block rename/delete but still permit in-place writes.
                try:
                    with path.open("w", encoding=encoding) as handle:
                        handle.write(content)
                    return
                except Exception as fallback_exc:
                    last_error = fallback_exc
            except OSError as exc:
                last_error = exc
                if getattr(exc, "winerror", None) not in {32, 33}:
                    raise
            finally:
                if temp_name and os.path.exists(temp_name):
                    try:
                        os.remove(temp_name)
                    except Exception:
                        pass

            if attempt < (max_attempts - 1):
                time.sleep(0.08 * (attempt + 1))

        if last_error is not None:
            raise last_error
        raise OSError("Atomic write failed")

    @staticmethod
    def _generate_random_text(length: int) -> str:
        alphabet = string.ascii_letters + string.digits
        size = max(1, int(length or 1))
        return "".join(secrets.choice(alphabet) for _ in range(size))

    @staticmethod
    def _ok(*, action: str, message: str, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "success",
            "action": action,
            "success": True,
            "verified": True,
            "error": "",
            "message": message,
            "data": data,
        }

    @staticmethod
    def _error(error: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "status": "error",
            "action": "file_control",
            "success": False,
            "verified": False,
            "error": error,
            "message": message,
            "details": details or {},
        }


def file_control_action(
    args: dict[str, Any],
    *,
    workspace_root: str,
    app_control_service: Any | None = None,
) -> dict[str, Any]:
    """Tool-registry adapter for enterprise file operations."""

    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value != 0
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return int(default)

    controller = FileController(workspace_root=workspace_root)

    action = str(args.get("action") or "").strip().lower()
    if not action:
        return controller._error("missing_action", "file_control requires an action.")

    if action in {"list", "ls", "dir"}:
        return controller.list_entries(
            path=str(args.get("path") or "."),
            include_hidden=_as_bool(args.get("include_hidden", False), False),
            limit=_as_int(args.get("limit"), controller._policy.max_list_results),
        )

    if action in {"find", "search"}:
        return controller.find(
            query=str(args.get("query") or args.get("name") or ""),
            start_path=str(args.get("path") or "."),
            include_hidden=_as_bool(args.get("include_hidden", False), False),
            kind=str(args.get("kind") or "both").lower() or "both",
            limit=_as_int(args.get("limit"), controller._policy.max_find_results),
        )

    if action == "read":
        return controller.read_text(path=str(args.get("path") or ""))

    if action in {"write", "create_file", "edit"}:
        return controller.write_text(
            path=str(args.get("path") or ""),
            content=str(args.get("content") or ""),
            append=False,
            create_parents=_as_bool(args.get("create_parents", True), True),
        )

    if action in {"append"}:
        return controller.write_text(
            path=str(args.get("path") or ""),
            content=str(args.get("content") or ""),
            append=True,
            create_parents=True,
        )

    if action in {"replace", "replace_text"}:
        return controller.replace_text(
            path=str(args.get("path") or ""),
            old_text=str(args.get("old_text") or ""),
            new_text=str(args.get("new_text") or ""),
            count=_as_int(args.get("count"), 0),
        )

    if action in {"move", "rename"}:
        return controller.move(
            source=str(args.get("source") or args.get("path") or ""),
            destination=str(args.get("destination") or args.get("target") or ""),
            overwrite=_as_bool(args.get("overwrite", False), False),
        )

    if action == "copy":
        return controller.copy(
            source=str(args.get("source") or args.get("path") or ""),
            destination=str(args.get("destination") or args.get("target") or ""),
            overwrite=_as_bool(args.get("overwrite", False), False),
        )

    if action in {"delete", "remove", "rm"}:
        return controller.remove(
            path=str(args.get("path") or ""),
            recursive=_as_bool(args.get("recursive", False), False),
        )

    if action in {"mkdir", "create_dir", "create_folder"}:
        return controller.make_directory(path=str(args.get("path") or ""), exist_ok=True)

    if action in {"touch"}:
        return controller.touch(path=str(args.get("path") or ""))

    if action in {"create_random_text_files", "bulk_create_text", "generate_text_files"}:
        return controller.create_random_text_files(
            path=str(args.get("path") or args.get("directory") or ""),
            count=_as_int(args.get("count"), 0),
            prefix=str(args.get("prefix") or "file_"),
            extension=str(args.get("extension") or ".txt"),
            min_chars=_as_int(args.get("min_chars"), 64),
            max_chars=_as_int(args.get("max_chars"), 160),
            exact_chars=(None if args.get("exact_chars") is None else _as_int(args.get("exact_chars"), 0)),
            fill_to_count=_as_bool(args.get("fill_to_count", True), True),
            overwrite_existing=_as_bool(args.get("overwrite_existing", False), False),
        )

    if action in {"filter_move_by_content", "move_files_containing", "filter_move_contains"}:
        return controller.filter_move_by_content(
            path=str(args.get("path") or args.get("directory") or ""),
            search_text=str(args.get("search_text") or args.get("query") or ""),
            destination_subfolder=str(args.get("destination_subfolder") or args.get("destination") or "Filtered"),
            extension=str(args.get("extension") or ".txt"),
            case_sensitive=_as_bool(args.get("case_sensitive", False), False),
            include_subdirs=_as_bool(args.get("include_subdirs", False), False),
        )

    if action in {"open"}:
        return controller.open_path(
            path=str(args.get("path") or ""),
            query=str(args.get("query") or args.get("text") or ""),
        )

    if action in {"close"}:
        return controller.close_path(path=str(args.get("path") or ""), app_control_service=app_control_service)

    return controller._error("unsupported_action", f"Unsupported file_control action: {action}")
