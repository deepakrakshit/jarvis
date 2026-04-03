from __future__ import annotations

import datetime
from difflib import SequenceMatcher
import json
import math
import os
import queue
import re
import socket
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
    VOICE_BLOCK_MODES = {"processing", "speaking"}
    VOICE_POST_SPEAKING_COOLDOWN_SECONDS = 2.2
    ASSISTANT_ECHO_WINDOW_SECONDS = 9.0
    ASSISTANT_ECHO_MIN_CHARS = 12
    ASSISTANT_ECHO_SIMILARITY_THRESHOLD = 0.78
    ASSISTANT_ECHO_SHORT_TEXT_BLOCK_SECONDS = 2.8
    MAX_ASSISTANT_TEXT_CHARS = 2200

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
        self._voice_gate_lock = threading.Lock()
        self._mode = "listening"
        self._voice_gate_until = 0.0
        self._assistant_text_live = ""
        self._assistant_text_norm = ""
        self._assistant_text_ts = 0.0
        self._assistant_echo_guard_until = 0.0
        self._boot_time = time.time()

        if psutil is not None:
            try:
                self._boot_time = float(psutil.boot_time())
            except Exception:
                self._boot_time = time.time()

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

    @staticmethod
    def _safe_number(value: Any) -> float | None:
        try:
            parsed = float(value)
        except Exception:
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

    @staticmethod
    def _safe_percent(value: Any) -> float | None:
        parsed = JarvisBridge._safe_number(value)
        if parsed is None:
            return None
        return max(0.0, min(100.0, parsed))

    @staticmethod
    def _safe_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        return None

    @staticmethod
    def _pick_temperature_celsius(temps: Any) -> float | None:
        if not isinstance(temps, dict) or not temps:
            return None

        for readings in temps.values():
            for entry in readings or ():
                current = JarvisBridge._safe_number(getattr(entry, "current", None))
                if current is None:
                    continue
                return max(-50.0, min(150.0, current))
        return None

    @staticmethod
    def _measure_connect_latency_ms(*, host: str = "1.1.1.1", port: int = 443, timeout: float = 0.35) -> float | None:
        started = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except Exception:
            return None

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not math.isfinite(elapsed_ms):
            return None
        return max(0.0, elapsed_ms)

    @staticmethod
    def _normalize_for_compare(text: str) -> str:
        lowered = (text or "").lower()
        collapsed = re.sub(r"[^a-z0-9\s]", " ", lowered)
        collapsed = re.sub(r"\s+", " ", collapsed)
        return collapsed.strip()

    @classmethod
    def _looks_like_assistant_echo(cls, user_norm: str, assistant_norm: str) -> bool:
        if not user_norm or not assistant_norm:
            return False

        if len(user_norm) < cls.ASSISTANT_ECHO_MIN_CHARS:
            return False

        if user_norm in assistant_norm:
            return True

        user_tokens = [token for token in user_norm.split() if len(token) > 2]
        assistant_tokens = {token for token in assistant_norm.split() if len(token) > 2}
        if len(user_tokens) >= 4:
            overlap = sum(1 for token in user_tokens if token in assistant_tokens) / len(user_tokens)
            if overlap >= 0.85:
                return True

        candidate_window = max(len(user_norm) + 28, 96)
        candidate_window = min(candidate_window, len(assistant_norm))

        if candidate_window <= 0:
            return False

        if len(assistant_norm) <= candidate_window:
            similarity = SequenceMatcher(None, user_norm, assistant_norm).ratio()
            return similarity >= cls.ASSISTANT_ECHO_SIMILARITY_THRESHOLD

        step = max(8, len(user_norm) // 3)
        for start in range(0, len(assistant_norm) - candidate_window + 1, step):
            segment = assistant_norm[start : start + candidate_window]
            similarity = SequenceMatcher(None, user_norm, segment).ratio()
            if similarity >= cls.ASSISTANT_ECHO_SIMILARITY_THRESHOLD:
                return True

        return False

    def _on_mode_change(self, mode: str) -> None:
        now = time.time()
        with self._voice_gate_lock:
            previous_mode = self._mode
            self._mode = mode

            if mode == "processing":
                self._assistant_text_live = ""
                self._assistant_text_norm = ""

            if mode == "speaking":
                self._voice_gate_until = max(
                    self._voice_gate_until,
                    now + self.VOICE_POST_SPEAKING_COOLDOWN_SECONDS,
                )
                self._assistant_echo_guard_until = max(
                    self._assistant_echo_guard_until,
                    now + self.ASSISTANT_ECHO_WINDOW_SECONDS,
                )
            elif mode == "listening" and previous_mode == "speaking":
                self._voice_gate_until = max(
                    self._voice_gate_until,
                    now + self.VOICE_POST_SPEAKING_COOLDOWN_SECONDS,
                )
                self._assistant_echo_guard_until = max(
                    self._assistant_echo_guard_until,
                    now + self.ASSISTANT_ECHO_WINDOW_SECONDS,
                )

        self._call_js("window.jarvis.setMode", mode)

    def _on_text_delta(self, delta: str) -> None:
        now = time.time()
        with self._voice_gate_lock:
            self._assistant_text_live += delta or ""
            if len(self._assistant_text_live) > self.MAX_ASSISTANT_TEXT_CHARS:
                self._assistant_text_live = self._assistant_text_live[-self.MAX_ASSISTANT_TEXT_CHARS :]
            self._assistant_text_norm = self._normalize_for_compare(self._assistant_text_live)
            self._assistant_text_ts = now

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

        clean_norm = self._normalize_for_compare(clean)
        if len(clean_norm) < 2:
            return {"accepted": False}

        now = time.time()
        with self._voice_gate_lock:
            mode = self._mode
            voice_gate_until = self._voice_gate_until
            assistant_norm = self._assistant_text_norm
            assistant_text_ts = self._assistant_text_ts
            assistant_echo_guard_until = self._assistant_echo_guard_until

        if mode in self.VOICE_BLOCK_MODES:
            return {"accepted": False}

        if now < voice_gate_until:
            return {"accepted": False}

        echo_window_active = now < assistant_echo_guard_until or (now - assistant_text_ts) < 2.0
        if now < assistant_echo_guard_until and len(clean_norm.split()) <= 3:
            return {"accepted": False}

        if clean_norm.startswith("system status snapshot"):
            return {"accepted": False}

        if echo_window_active and self._looks_like_assistant_echo(clean_norm, assistant_norm):
            return {"accepted": False}

        if (now - assistant_text_ts) < self.ASSISTANT_ECHO_SHORT_TEXT_BLOCK_SECONDS and assistant_norm:
            tail = assistant_norm[-max(160, len(clean_norm) + 40) :]
            sim = SequenceMatcher(None, clean_norm, tail).ratio()
            if sim >= 0.72:
                return {"accepted": False}

        if clean.lower() == self._last_voice.lower() and (now - self._last_voice_ts) < 1.5:
            return {"accepted": False}

        self._last_voice = clean
        self._last_voice_ts = now

        if self._stream_to_stdout:
            try:
                print(f"you > {clean}")
            except Exception:
                pass

        self._call_js("window.jarvis.onUserTranscript", clean)
        self._input_queue.put(clean)
        return {"accepted": True}

    def skip_current_reply(self) -> dict[str, bool]:
        try:
            result = self.runtime.skip_current_reply()
            return {"ok": bool(result.get("skipped"))}
        except Exception:
            return {"ok": False}

    def _voice_worker(self) -> None:
        while not self._stop.is_set():
            try:
                utterance = self._input_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                if utterance == "__greet__":
                    self.runtime.greet(stream_to_stdout=self._stream_to_stdout)
                else:
                    self.runtime.ask(utterance, stream_to_stdout=self._stream_to_stdout)
            except Exception:
                self._on_mode_change("listening")

    def _metrics_worker(self) -> None:
        host_name = socket.gethostname() or "UNKNOWN"
        root_path = os.path.abspath(os.sep)
        proc = None
        prev_net = None
        prev_net_ts = time.time()
        last_latency_check_at = 0.0
        last_latency_ms: float | None = None

        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

            try:
                proc = psutil.Process(os.getpid())
            except Exception:
                proc = None

        while not self._stop.is_set():
            payload: dict[str, Any] = {
                "cpuPercent": None,
                "ramPercent": None,
                "ramUsedGb": None,
                "ramTotalGb": None,
                "diskPercent": None,
                "diskUsedGb": None,
                "diskTotalGb": None,
                "temperatureC": None,
                "threads": None,
                "netDownMBps": None,
                "netUpMBps": None,
                "netPacketsTotal": None,
                "latencyMs": None,
                "batteryPercent": None,
                "batteryCharging": None,
                "batteryPlugged": None,
                "batterySecsLeft": None,
                "hostname": host_name,
                "systemTime": "--:--:--",
                "systemDate": "----/--/--",
                "uptimeSeconds": 0,
            }

            now_ts = time.time()

            if psutil is not None:
                try:
                    cpu_percent = self._safe_percent(psutil.cpu_percent(interval=None))
                    if cpu_percent is not None:
                        payload["cpuPercent"] = cpu_percent

                    virtual_mem = psutil.virtual_memory()
                    payload["ramPercent"] = self._safe_percent(getattr(virtual_mem, "percent", None))

                    vm_used = self._safe_number(getattr(virtual_mem, "used", None))
                    vm_total = self._safe_number(getattr(virtual_mem, "total", None))
                    if vm_used is not None:
                        payload["ramUsedGb"] = vm_used / (1024.0 ** 3)
                    if vm_total is not None:
                        payload["ramTotalGb"] = vm_total / (1024.0 ** 3)

                    disk = psutil.disk_usage(root_path)
                    payload["diskPercent"] = self._safe_percent(getattr(disk, "percent", None))
                    disk_used = self._safe_number(getattr(disk, "used", None))
                    disk_total = self._safe_number(getattr(disk, "total", None))
                    if disk_used is not None:
                        payload["diskUsedGb"] = disk_used / (1024.0 ** 3)
                    if disk_total is not None:
                        payload["diskTotalGb"] = disk_total / (1024.0 ** 3)

                    if proc is not None:
                        payload["threads"] = int(proc.num_threads())

                    net = psutil.net_io_counters()
                    if prev_net is not None and now_ts > prev_net_ts:
                        dt = max(0.001, now_ts - prev_net_ts)
                        recv_delta = float(net.bytes_recv - prev_net.bytes_recv)
                        sent_delta = float(net.bytes_sent - prev_net.bytes_sent)
                        payload["netDownMBps"] = max(0.0, recv_delta / dt / (1024.0 ** 2))
                        payload["netUpMBps"] = max(0.0, sent_delta / dt / (1024.0 ** 2))

                    payload["netPacketsTotal"] = float(net.packets_recv + net.packets_sent)
                    prev_net = net
                    prev_net_ts = now_ts

                    battery = psutil.sensors_battery()
                    if battery is not None:
                        payload["batteryPercent"] = self._safe_percent(getattr(battery, "percent", None))
                        plugged = self._safe_bool(getattr(battery, "power_plugged", None))
                        payload["batteryCharging"] = plugged
                        payload["batteryPlugged"] = plugged

                        secs_left = self._safe_number(getattr(battery, "secsleft", None))
                        unknown_markers = {
                            float(getattr(psutil, "POWER_TIME_UNLIMITED", -2)),
                            float(getattr(psutil, "POWER_TIME_UNKNOWN", -1)),
                        }
                        if secs_left is not None and secs_left >= 0 and secs_left not in unknown_markers:
                            payload["batterySecsLeft"] = secs_left

                    try:
                        temps = psutil.sensors_temperatures(fahrenheit=False)
                    except Exception:
                        temps = None
                    payload["temperatureC"] = self._pick_temperature_celsius(temps)
                except Exception:
                    pass

            if (now_ts - last_latency_check_at) >= 5.0:
                last_latency_ms = self._measure_connect_latency_ms()
                last_latency_check_at = now_ts

            payload["latencyMs"] = last_latency_ms

            now = datetime.datetime.now().astimezone()
            payload["systemTime"] = now.strftime("%H:%M:%S")
            payload["systemDate"] = now.strftime("%Y-%m-%d")
            payload["uptimeSeconds"] = max(0, int(time.time() - self._boot_time))

            self._call_js("window.jarvis.setSystemMetrics", payload)
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

    def skip_current_reply(self) -> dict[str, bool]:
        return self._bridge.skip_current_reply()
