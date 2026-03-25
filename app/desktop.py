from __future__ import annotations

import logging
import os
import sys

import requests

from core.dependencies import ensure_deps, ensure_gui_deps
from core.runtime import JarvisRuntime
from core.settings import AppConfig
from interface.api_bridge import JarvisApi, JarvisBridge, start_static_server


def run_desktop(
    config: AppConfig,
    *,
    runtime: JarvisRuntime | None = None,
    greet_on_ready: bool = True,
    stream_to_stdout: bool = False,
    close_runtime_on_exit: bool = True,
) -> None:
    ensure_deps()
    ensure_gui_deps()

    import webview

    logging.getLogger("pywebview").setLevel(logging.ERROR)

    active_runtime = runtime or JarvisRuntime(config)
    bridge = JarvisBridge(
        active_runtime,
        greet_on_ready=greet_on_ready,
        stream_to_stdout=stream_to_stdout,
    )
    api = JarvisApi(bridge)

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    web_root = os.path.join(project_root, "frontend")
    if not os.path.isdir(web_root):
        raise RuntimeError("Frontend directory not found at ./frontend")

    server, port = start_static_server(web_root)
    url = f"http://127.0.0.1:{port}/index.html"

    window = webview.create_window(
        "J.A.R.V.I.S - Core Engine",
        url=url,
        js_api=api,
        width=1360,
        height=860,
        min_size=(1024, 640),
    )

    def on_closed() -> None:
        bridge.shutdown(close_runtime=close_runtime_on_exit)
        server.shutdown()
        server.server_close()

    window.events.closed += on_closed

    try:
        webview.start(debug=False, http_server=False, gui="edgechromium")
    except Exception:
        webview.start(debug=False, http_server=False)


def main() -> None:
    config = AppConfig.from_env(".env")
    if not config.groq_api_key:
        raise RuntimeError("Missing GROQ_API_KEY")

    try:
        run_desktop(config)
    except requests.HTTPError as http_error:
        print(f"JARVIS API ERROR: {http_error}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as runtime_error:
        print(f"JARVIS SETUP ERROR: {runtime_error}", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        print(f"JARVIS ERROR: {err}", file=sys.stderr)
        sys.exit(1)
