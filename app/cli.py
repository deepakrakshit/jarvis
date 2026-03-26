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
            active_runtime.ask_groq(clean)
    finally:
        if close_runtime and owns_runtime:
            active_runtime.close()


def main() -> None:
    logging.getLogger().setLevel(logging.ERROR)

    config = AppConfig.from_env(".env")
    if not config.groq_api_key:
        raise RuntimeError("Missing GROQ_API_KEY")

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
