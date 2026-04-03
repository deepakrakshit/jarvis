from __future__ import annotations

import argparse
import os
import pathlib
import threading
import sys


def _maybe_reexec_into_project_venv() -> None:
    """Ensure direct app/main.py launches use the project's local venv."""
    if os.getenv("JARVIS_VENV_REEXECED") == "1":
        return

    project_root = pathlib.Path(__file__).resolve().parents[1]
    candidates = (
        project_root / "venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "Scripts" / "python.exe",
    )
    target = next((path for path in candidates if path.is_file()), None)
    if target is None:
        return

    current = pathlib.Path(sys.executable).resolve()
    target_resolved = target.resolve()
    if current == target_resolved:
        return

    os.environ["JARVIS_VENV_REEXECED"] = "1"
    script = pathlib.Path(__file__).resolve()
    os.execv(str(target_resolved), [str(target_resolved), str(script), *sys.argv[1:]])


_maybe_reexec_into_project_venv()

import requests

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.cli import main as cli_main, run_cli
from app.desktop import main as desktop_main, run_desktop
from core.dependencies import ensure_deps, ensure_gui_deps
from core.runtime import JarvisRuntime
from core.settings import AppConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="JARVIS launcher (GUI, CLI, or both together)",
    )
    parser.add_argument(
        "--mode",
        choices=["gui", "cli", "both"],
        default="both",
        help="Launch mode (default: both)",
    )
    parser.add_argument("--gui", action="store_true", help="Shortcut for --mode gui")
    parser.add_argument("--cli", action="store_true", help="Shortcut for --mode cli")
    parser.add_argument("--both", action="store_true", help="Shortcut for --mode both")
    return parser


def _run_both_connected() -> None:
    config = AppConfig.from_env(".env")
    if not config.primary_llm_api_key():
        raise RuntimeError(f"Missing {config.required_primary_llm_key_name()}")

    ensure_deps()
    ensure_gui_deps()
    runtime = JarvisRuntime(config)

    cli_thread = threading.Thread(
        target=run_cli,
        kwargs={
            "config": config,
            "runtime": runtime,
            "greet": True,
            "close_runtime": False,
        },
        name="jarvis-cli-thread",
        daemon=True,
    )
    cli_thread.start()

    try:
        run_desktop(
            config,
            runtime=runtime,
            greet_on_ready=False,
            stream_to_stdout=True,
            close_runtime_on_exit=False,
        )
    finally:
        runtime.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    mode = args.mode
    if args.gui:
        mode = "gui"
    if args.cli:
        mode = "cli"
    if args.both:
        mode = "both"

    if mode == "cli":
        cli_main()
        return

    if mode == "gui":
        desktop_main()
        return

    try:
        _run_both_connected()
    except requests.HTTPError as http_error:
        print(f"JARVIS API ERROR: {http_error}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as runtime_error:
        print(f"JARVIS SETUP ERROR: {runtime_error}", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        print(f"JARVIS ERROR: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
