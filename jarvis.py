from __future__ import annotations

import os
import pathlib
import sys


def _maybe_reexec_into_project_venv() -> None:
    """Ensure JARVIS runs on the project's local virtual environment interpreter."""
    if os.getenv("JARVIS_VENV_REEXECED") == "1":
        return

    project_root = pathlib.Path(__file__).resolve().parent
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
    script = project_root / "jarvis.py"
    os.execv(str(target_resolved), [str(target_resolved), str(script), *sys.argv[1:]])


_maybe_reexec_into_project_venv()

from app.main import main
from core.runtime import JarvisRuntime
from core.settings import AppConfig

__all__ = ["main", "JarvisRuntime", "AppConfig"]


if __name__ == "__main__":
    main()