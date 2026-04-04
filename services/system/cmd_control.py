# ==============================================================================
# File: services/system/cmd_control.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Secure Command Execution Controller
#
#    - Structured command runner for cmd.exe / PowerShell execution.
#    - Safety policy blocks destructive or privilege-sensitive command families.
#    - Timeout, working-directory, and output-size guardrails.
#    - Returns structured payloads for agent synthesis and auditing.
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
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandPolicy:
    blocked_patterns: tuple[str, ...]
    max_timeout_seconds: int = 300
    max_output_chars: int = 20000
    max_command_length: int = 4096
    enforce_workspace_boundary: bool = True
    blocked_control_tokens: tuple[str, ...] = ("\n", "\r", "&&", "||", "`")


class CmdControl:
    """Enterprise-safe command execution facade."""

    DEFAULT_BLOCKED_PATTERNS: tuple[str, ...] = (
        r"\bformat\b",
        r"\bdiskpart\b",
        r"\bbcdedit\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bpoweroff\b",
        r"\bhalt\b",
        r"\bcipher\s+/w\b",
        r"\bsdelete\b",
        r"\bmkfs(?:\.|\s|$)",
        r"\bdd\s+if=",
        r"\brm\s+-rf\s+/(?:\s|$)",
        r"\bdel\s+/f\s+/s\s+/q\s+[a-zA-Z]:\\",
        r"\brd\s+/s\s+/q\s+[a-zA-Z]:\\",
        r"\breg\s+delete\s+HKLM\\",
        r"\btaskkill\b.*\b/im\b\s+(?:csrss|wininit|winlogon|lsass|services)\.exe",
        r"\bremove-item\b.*\b-recurse\b.*\b-force\b",
        r"\bset-executionpolicy\b",
        r"\binvoke-expression\b",
    )
    _ALLOWED_SHELLS: tuple[str, ...] = ("cmd", "powershell", "pwsh", "sh", "bash")
    _SENSITIVE_ENV_KEY_PATTERN = re.compile(r"(key|token|secret|password|passwd|pwd|auth)", flags=re.IGNORECASE)

    def __init__(
        self,
        *,
        workspace_root: str,
        policy: CommandPolicy | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._policy = policy or CommandPolicy(blocked_patterns=self.DEFAULT_BLOCKED_PATTERNS)

    def run(
        self,
        *,
        command: str,
        cwd: str | None = None,
        timeout_seconds: int = 90,
        shell: str = "cmd",
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        raw_command = str(command or "").strip()
        if not raw_command:
            return self._error_payload(
                error="missing_command",
                message="No command provided.",
            )

        if len(raw_command) > int(self._policy.max_command_length):
            return self._error_payload(
                error="command_too_long",
                message=f"Command exceeds maximum length ({self._policy.max_command_length}).",
            )

        shell_name = str(shell or "cmd").strip().lower() or "cmd"
        if shell_name not in self._ALLOWED_SHELLS:
            return self._error_payload(
                error="unsupported_shell",
                message=f"Unsupported shell: {shell_name}",
            )

        for token in self._policy.blocked_control_tokens:
            if token and token in raw_command:
                return self._error_payload(
                    error="blocked_command",
                    message="Command contains blocked control token.",
                    details={"token": token},
                )

        normalized_command = " ".join(raw_command.split())

        blocked, blocked_pattern = self._is_blocked(normalized_command)
        if blocked:
            return self._error_payload(
                error="blocked_command",
                message="Command blocked by safety policy.",
                details={"pattern": blocked_pattern, "command": normalized_command},
            )

        resolved_cwd = self._resolve_cwd(cwd)
        if resolved_cwd is None:
            return self._error_payload(
                error="invalid_cwd",
                message="Working directory is invalid.",
                details={"cwd": str(cwd or "")},
            )

        timeout = max(1, min(int(timeout_seconds), int(self._policy.max_timeout_seconds)))
        launch_cmd = self._build_launch_command(normalized_command, shell=shell_name)

        env_payload = os.environ.copy()
        sensitive_values: list[str] = []
        if isinstance(env, dict):
            for key, value in env.items():
                key_text = str(key or "").strip()
                if not key_text:
                    continue
                value_text = str(value or "")
                env_payload[key_text] = value_text
                if self._SENSITIVE_ENV_KEY_PATTERN.search(key_text):
                    sensitive_values.append(value_text)

        started_at = time.perf_counter()
        try:
            proc = subprocess.run(
                launch_cmd,
                cwd=str(resolved_cwd),
                env=env_payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            success = int(proc.returncode) == 0
            return {
                "status": "success" if success else "error",
                "action": "run_command",
                "success": success,
                "verified": success,
                "error": "" if success else "command_failed",
                "message": "Command executed." if success else "Command returned a non-zero exit code.",
                "command": normalized_command,
                "shell": shell_name,
                "cwd": str(resolved_cwd),
                "timeout_seconds": timeout,
                "exit_code": int(proc.returncode),
                "timed_out": False,
                "duration_ms": duration_ms,
                "stdout": self._redact_sensitive_values(self._truncate(proc.stdout), sensitive_values),
                "stderr": self._redact_sensitive_values(self._truncate(proc.stderr), sensitive_values),
            }
        except subprocess.TimeoutExpired as exc:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return {
                "status": "error",
                "action": "run_command",
                "success": False,
                "verified": False,
                "error": "command_timeout",
                "message": "Command timed out.",
                "command": normalized_command,
                "shell": shell_name,
                "cwd": str(resolved_cwd),
                "timeout_seconds": timeout,
                "exit_code": None,
                "timed_out": True,
                "duration_ms": duration_ms,
                "stdout": self._redact_sensitive_values(self._truncate(stdout), sensitive_values),
                "stderr": self._redact_sensitive_values(self._truncate(stderr), sensitive_values),
            }
        except Exception as exc:
            return self._error_payload(
                error="command_execution_error",
                message=f"Command execution failed: {exc}",
                details={"command": normalized_command, "shell": shell_name, "cwd": str(resolved_cwd)},
            )

    def _resolve_cwd(self, cwd: str | None) -> Path | None:
        candidate = Path(cwd).expanduser() if cwd else self._workspace_root
        if not candidate.is_absolute():
            candidate = (self._workspace_root / candidate).resolve()
        else:
            candidate = candidate.resolve()

        if self._policy.enforce_workspace_boundary:
            try:
                candidate.relative_to(self._workspace_root)
            except Exception:
                return None

        if not candidate.exists() or not candidate.is_dir():
            return None
        return candidate

    def _is_blocked(self, command: str) -> tuple[bool, str]:
        lowered = str(command or "").lower()
        for pattern in self._policy.blocked_patterns:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                return True, pattern
        return False, ""

    @staticmethod
    def _build_launch_command(command: str, *, shell: str) -> list[str]:
        shell_name = str(shell or "cmd").strip().lower()

        if os.name == "nt":
            if shell_name in {"powershell", "pwsh"}:
                preferred = "powershell" if shell_name == "powershell" else "pwsh"
                return [preferred, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
            return ["cmd.exe", "/d", "/s", "/c", command]

        if shell_name in {"powershell", "pwsh"}:
            return ["pwsh", "-NoProfile", "-Command", command]
        return ["/bin/sh", "-lc", command]

    def _truncate(self, text: str) -> str:
        source = str(text or "")
        max_chars = max(512, int(self._policy.max_output_chars))
        if len(source) <= max_chars:
            return source
        return source[: max_chars - 24] + "\n...[output truncated]"

    @staticmethod
    def _redact_sensitive_values(text: str, sensitive_values: list[str]) -> str:
        redacted = str(text or "")
        for value in sensitive_values:
            token = str(value or "")
            if not token:
                continue
            redacted = redacted.replace(token, "[REDACTED]")
        return redacted

    @staticmethod
    def _error_payload(*, error: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "status": "error",
            "action": "run_command",
            "success": False,
            "verified": False,
            "error": str(error or "command_error"),
            "message": str(message or "Command failed."),
            "details": details or {},
            "stdout": "",
            "stderr": "",
        }


def cmd_control_action(args: dict[str, Any], *, workspace_root: str) -> dict[str, Any]:
    """Registry adapter for command control actions."""
    command = str(args.get("command") or "").strip()
    action = str(args.get("action") or "run").strip().lower() or "run"
    if action in {"execute", "run_command", "command"}:
        action = "run"

    if action != "run":
        return {
            "status": "error",
            "action": action,
            "success": False,
            "verified": False,
            "error": "unsupported_action",
            "message": f"Unsupported cmd_control action: {action}",
        }

    controller = CmdControl(workspace_root=workspace_root)
    return controller.run(
        command=command,
        cwd=str(args.get("cwd") or "").strip() or None,
        timeout_seconds=int(args.get("timeout_seconds") or 90),
        shell=str(args.get("shell") or "cmd").strip().lower() or "cmd",
        env=args.get("env") if isinstance(args.get("env"), dict) else None,
    )
