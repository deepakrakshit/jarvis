"""Cross-platform file selector for the Document Intelligence pipeline.

The LLM NEVER triggers the file picker — only the system/UI layer does.
Supports tkinter (GUI) and fallback to CLI path input.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
}

_FILE_TYPE_FILTERS = [
    ("All Supported", "*.pdf *.docx *.doc *.png *.jpg *.jpeg *.tiff *.tif *.bmp *.webp"),
    ("PDF Files", "*.pdf"),
    ("Word Documents", "*.docx *.doc"),
    ("Images", "*.png *.jpg *.jpeg *.tiff *.tif *.bmp *.webp"),
    ("All Files", "*.*"),
]


def is_supported_file(file_path: str) -> bool:
    """Check if a file path has a supported extension."""
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_EXTENSIONS


def validate_file_path(file_path: str) -> tuple[str, str]:
    """Validate a file path and return (normalized_path, error).

    Returns:
        Tuple of (absolute_path, error_message).
        If error_message is empty, the path is valid.
    """
    if not file_path or not file_path.strip():
        return "", "No file path provided."

    path = Path(file_path.strip()).resolve()

    if not path.exists():
        return "", f"File not found: {path}"

    if not path.is_file():
        return "", f"Not a file: {path}"

    if not is_supported_file(str(path)):
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        return "", f"Unsupported file type '{path.suffix}'. Supported: {supported}"

    # Check file size (max 100MB)
    size_bytes = path.stat().st_size
    max_size = 100 * 1024 * 1024
    if size_bytes > max_size:
        return "", f"File too large ({size_bytes / (1024*1024):.1f}MB). Maximum is 100MB."

    if size_bytes == 0:
        return "", "File is empty (0 bytes)."

    return str(path), ""


def select_file_gui(*, allow_multiple: bool = False) -> list[str] | None:
    """Open a native file dialog using tkinter.

    Returns selected absolute paths, or None if cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()

        if allow_multiple:
            selected = filedialog.askopenfilenames(
                title="Select documents",
                filetypes=_FILE_TYPE_FILTERS,
                parent=root,
            )
        else:
            selected = filedialog.askopenfilename(
                title="Select a document to analyze",
                filetypes=_FILE_TYPE_FILTERS,
                parent=root,
            )

        root.destroy()

        if allow_multiple:
            paths = [str(Path(item).resolve()) for item in selected if str(item).strip()]
            return paths or None

        file_path = str(selected or "").strip()
        if file_path:
            return [str(Path(file_path).resolve())]
        return None

    except ImportError:
        logger.warning("tkinter not available for file dialog")
        return None
    except Exception as exc:
        logger.error("File dialog failed: %s", exc)
        return None


def select_file_cli(*, allow_multiple: bool = False) -> list[str] | None:
    """Prompt user for one or many file paths via CLI input."""
    try:
        print("\n📄 Document Analysis")
        print(f"   Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        if allow_multiple:
            user_input = input("   Enter file paths separated by commas (or 'cancel'): ").strip()
        else:
            user_input = input("   Enter file path (or 'cancel'): ").strip()

        if not user_input or user_input.lower() in {"cancel", "c", "quit", "q", "exit"}:
            return None

        # Remove surrounding quotes
        if (user_input.startswith('"') and user_input.endswith('"')) or (
            user_input.startswith("'") and user_input.endswith("'")
        ):
            user_input = user_input[1:-1]

        if not allow_multiple:
            return [str(Path(user_input).resolve())]

        raw_parts = [part.strip() for part in user_input.split(",") if part.strip()]
        paths = [str(Path(part).resolve()) for part in raw_parts]
        return paths or None

    except (EOFError, KeyboardInterrupt):
        return None


def select_files(
    *,
    prefer_gui: bool = True,
    allow_multiple: bool = False,
    allow_cli_fallback: bool = True,
) -> list[str] | None:
    """Select files using the best available method.

    Args:
        prefer_gui: If True, try tkinter dialog first, fall back to CLI.
        allow_multiple: If True, allow selecting multiple files.
        allow_cli_fallback: If False, never prompt for terminal input.
    """
    if prefer_gui:
        result = select_file_gui(allow_multiple=allow_multiple)
        if result is not None:
            return result
        if not allow_cli_fallback:
            logger.info("GUI file dialog unavailable or cancelled; CLI fallback disabled")
            return None
        logger.info("GUI file dialog unavailable or cancelled, falling back to CLI")

    if not allow_cli_fallback:
        return None

    return select_file_cli(allow_multiple=allow_multiple)


def select_file(*, prefer_gui: bool = True, allow_cli_fallback: bool = True) -> str | None:
    """Backward-compatible single-file selector."""
    selected = select_files(
        prefer_gui=prefer_gui,
        allow_multiple=False,
        allow_cli_fallback=allow_cli_fallback,
    )
    if not selected:
        return None
    return selected[0]
