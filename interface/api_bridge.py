from __future__ import annotations

import json
import queue
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from core.runtime import JarvisRuntime

try:
    import psutil  # type: ignore
except Exception:
    psutil = None


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


def start_static_server(web_root: str) -> tuple[ThreadingHTTPServer, int]:
    handler = partial(QuietStaticHandler, directory=web_root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, int(server.server_address[1])


class JarvisBridge:
    def __init__(
        self,
        runtime: JarvisRuntime,
        *,
        greet_on_ready: bool = True,
        stream_to_stdout: bool = False,
    ) -> None:
        self.runtime = runtime
        self._greet_on_ready = greet_on_ready
        self._stream_to_stdout = stream_to_stdout
        self._input_queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._last_voice = ""
        self._last_voice_ts = 0.0

        self.runtime.set_event_callbacks(
            on_mode_change=self._on_mode_change,
            on_text_delta=self._on_text_delta,
            on_api_activity=self._on_api_activity,
        )

        self._worker_thread = threading.Thread(
            target=self._voice_worker,
            name="jarvis-voice-worker",
            daemon=True,
        )
        self._metrics_thread = threading.Thread(
            target=self._metrics_worker,
            name="jarvis-metrics-worker",
            daemon=True,
        )
        self._worker_thread.start()
        self._metrics_thread.start()

    def _eval_js(self, script: str) -> None:
        try:
            import webview

            if not webview.windows:
                return
            webview.windows[0].evaluate_js(script)
        except Exception:
            pass

    def _call_js(self, fn_name: str, *args: Any) -> None:
        js_args = ", ".join(json.dumps(arg) for arg in args)
        self._eval_js(f"{fn_name}({js_args});")

    def _on_mode_change(self, mode: str) -> None:
        self._call_js("window.jarvis.setMode", mode)

    def _on_text_delta(self, delta: str) -> None:
        self._call_js("window.jarvis.onAssistantDelta", delta)

    def _on_api_activity(self, active: bool) -> None:
        self._call_js("window.jarvis.setApiActivity", active)

    def ui_ready(self) -> dict[str, bool]:
        self._on_mode_change("listening")
        if self._greet_on_ready:
            self._input_queue.put("__greet__")
        return {"ok": True}

    def submit_voice(self, text: str) -> dict[str, bool]:
        clean = (text or "").strip()
        if not clean:
            return {"accepted": False}

        now = time.time()
        if clean.lower() == self._last_voice.lower() and (now - self._last_voice_ts) < 1.5:
            return {"accepted": False}

        self._last_voice = clean
        self._last_voice_ts = now

        self._call_js("window.jarvis.onUserTranscript", clean)
        self._input_queue.put(clean)
        return {"accepted": True}

    def _voice_worker(self) -> None:
        while not self._stop.is_set():
            try:
                utterance = self._input_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if utterance == "__greet__":
                    self.runtime.ask_groq(
                        "Deliver a concise system-ready greeting to the authorized user in one line.",
                        persist_user=False,
                        stream_to_stdout=self._stream_to_stdout,
                    )
                else:
                    self.runtime.ask_groq(utterance, stream_to_stdout=self._stream_to_stdout)
            except Exception:
                self._on_mode_change("listening")

    def _metrics_worker(self) -> None:
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

        while not self._stop.is_set():
            cpu = 0.0
            ram = 0.0

            if psutil is not None:
                try:
                    cpu = max(0.0, min(1.0, psutil.cpu_percent(interval=None) / 100.0))
                    ram = max(0.0, min(1.0, psutil.virtual_memory().percent / 100.0))
                except Exception:
                    cpu = 0.0
                    ram = 0.0

            self._call_js("window.jarvis.setSystemMetrics", cpu, ram)
            time.sleep(0.9)

    def shutdown(self, *, close_runtime: bool = True) -> None:
        self._stop.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        if self._metrics_thread.is_alive():
            self._metrics_thread.join(timeout=1.0)
        if close_runtime:
            self.runtime.close()


class JarvisApi:
    __slots__ = ("_bridge",)

    def __init__(self, bridge: JarvisBridge) -> None:
        self._bridge = bridge

    def ui_ready(self) -> dict[str, bool]:
        return self._bridge.ui_ready()

    def submit_voice(self, text: str) -> dict[str, bool]:
        return self._bridge.submit_voice(text)
