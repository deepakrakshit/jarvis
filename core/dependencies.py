from __future__ import annotations


def ensure_deps() -> None:
    missing: list[str] = []

    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    try:
        try:
            from realtime_tts import PiperEngine, TextToAudioStream  # noqa: F401
        except ImportError:
            from RealtimeTTS import PiperEngine, TextToAudioStream  # noqa: F401
    except ImportError:
        missing.append("RealtimeTTS")

    if missing:
        joined = " ".join(missing)
        raise RuntimeError(
            "Missing package(s): "
            + joined
            + ". Install with: pip install "
            + joined
        )


def ensure_gui_deps() -> None:
    missing: list[str] = []

    try:
        import webview  # noqa: F401
    except ImportError:
        missing.append("pywebview")

    if missing:
        joined = " ".join(missing)
        raise RuntimeError(
            "Missing GUI package(s): "
            + joined
            + ". Install with: pip install "
            + joined
        )
