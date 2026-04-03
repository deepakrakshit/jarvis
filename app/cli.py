# ==============================================================================
# File: app/cli.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Command-Line Interface REPL Module
#
#    - Interactive console interface running a read-eval-print loop (REPL).
#    - Accepts an optional pre-initialized JarvisRuntime for shared mode.
#    - Displays an animated boot sequence with ANSI-colored loading lines.
#    - Issues runtime.greet() on startup for personalized user greetings.
#    - Custom input_with_cursor() provides character-by-character input
#      rendering with visual cursor on Windows via msvcrt.
#    - Gracefully handles KeyboardInterrupt and EOFError for clean exits.
#    - Supports 'exit' and 'quit' commands for session termination.
#    - Configurable runtime ownership — can close or preserve the runtime.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import logging
import sys

import requests

from core.dependencies import ensure_deps
from core.runtime import JarvisRuntime
from core.settings import AppConfig
from interface.cli_ui import clear_screen, input_with_cursor, print_boot_sequence


def run_cli(
    config: AppConfig,
    *,
    runtime: JarvisRuntime | None = None,
    greet: bool = True,
    close_runtime: bool = True,
) -> None:
    ensure_deps()
    owns_runtime = runtime is None
    active_runtime = runtime or JarvisRuntime(config)

    clear_screen()
    print_boot_sequence()

    try:
        if greet:
            active_runtime.greet()

        while True:
            try:
                user_input = input_with_cursor()
            except (KeyboardInterrupt, EOFError):
                print("\nJARVIS: Session terminated safely.")
                break

            clean = user_input.strip()
            if not clean:
                continue

            if clean.lower() in {"exit", "quit"}:
                break

            print(f"you > {clean}")
            active_runtime.ask(clean)
    finally:
        if close_runtime and owns_runtime:
            active_runtime.close()


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)

    config = AppConfig.from_env(".env")
    if not config.primary_llm_api_key():
        raise RuntimeError(f"Missing {config.required_primary_llm_key_name()}")

    try:
        run_cli(config)
    except requests.HTTPError as http_error:
        print(f"JARVIS API ERROR: {http_error}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as runtime_error:
        print(f"JARVIS SETUP ERROR: {runtime_error}", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        print(f"JARVIS ERROR: {err}", file=sys.stderr)
        sys.exit(1)
