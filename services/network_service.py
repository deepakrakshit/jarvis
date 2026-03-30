from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass

from core.personality import PersonalityEngine
from core.settings import AppConfig, VERSION
from services.utils.http_client import HttpClient
from services.utils.location_utils import LocationInfo, resolve_ip_location

try:
    import psutil  # type: ignore
except Exception:
    psutil = None


@dataclass(frozen=True)
class SpeedtestResult:
    download_mbps: float
    upload_mbps: float
    ping_ms: float
    timestamp: float
    server_name: str = ""
    server_host: str = ""
    server_country: str = ""
    server_sponsor: str = ""


class NetworkService:
    """Network diagnostics and local machine status capabilities."""

    def __init__(self, config: AppConfig, personality: PersonalityEngine) -> None:
        self.config = config
        self.personality = personality
        self.http = HttpClient(timeout=8.0)

        self._speedtest_lock = threading.Lock()
        self._speedtest_thread: threading.Thread | None = None
        self._speedtest_running = False
        self._last_speedtest: SpeedtestResult | None = None
        self._last_speedtest_error: str | None = None
        self._min_sync_speedtest_seconds = 3.4

        self._boot_time = time.time()
        if psutil is not None:
            try:
                self._boot_time = float(psutil.boot_time())
                psutil.cpu_percent(interval=None)
            except Exception:
                self._boot_time = time.time()

    @staticmethod
    def _format_uptime(total_seconds: int) -> str:
        days, remainder = divmod(max(0, int(total_seconds)), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m {seconds}s"
        return f"{hours}h {minutes}m {seconds}s"

    @staticmethod
    def _speed_benchmark(country: str | None) -> tuple[float, float, str]:
        normalized = (country or "").strip().lower()
        if normalized == "india":
            return 40.0, 100.0, "India"
        if normalized in {"united states", "usa", "us"}:
            return 100.0, 200.0, "United States"
        return 50.0, 150.0, (country or "your region")

    @staticmethod
    def _speed_quality_message(download_mbps: float, upload_mbps: float) -> str:
        if download_mbps >= 100 and upload_mbps >= 20:
            return "Your connection looks excellent for streaming, calls, and large file transfers."
        if download_mbps >= 50 and upload_mbps >= 10:
            return "Your connection looks good for everyday use, meetings, and HD streaming."
        if download_mbps >= 25 and upload_mbps >= 5:
            return "Your connection is usable, but heavier workloads may feel slower at times."
        return "Your connection is currently on the slower side; uploads and high-quality streaming may lag."

    def _render_speedtest_result(self, result: SpeedtestResult) -> str:
        quality = self._speed_quality_message(result.download_mbps, result.upload_mbps)
        message = (
            "Internet speed test results:\n"
            f"Download Speed: {result.download_mbps:.2f} Mbps\n"
            f"Upload Speed: {result.upload_mbps:.2f} Mbps\n\n"
            f"{quality}"
        )
        return self.personality.finalize(message)

    def _execute_speedtest_once(self) -> tuple[SpeedtestResult | None, str | None]:
        try:
            import speedtest  # type: ignore

            tester = speedtest.Speedtest(secure=True)
            server = tester.get_best_server() or {}
            download_bps = float(tester.download(threads=4))
            upload_bps = float(tester.upload(threads=4, pre_allocate=False))
            ping_ms = float(tester.results.ping)
            result = SpeedtestResult(
                download_mbps=download_bps / 1_000_000.0,
                upload_mbps=upload_bps / 1_000_000.0,
                ping_ms=ping_ms,
                timestamp=time.time(),
                server_name=str(server.get("name") or ""),
                server_host=str(server.get("host") or ""),
                server_country=str(server.get("country") or ""),
                server_sponsor=str(server.get("sponsor") or ""),
            )
            return result, None
        except ModuleNotFoundError:
            return None, "missing_speedtest_module"
        except Exception as exc:
            return None, str(exc)

    def get_public_ip(self) -> str | None:
        payload = self.http.get_json("https://api.ipify.org", params={"format": "json"})
        if payload and payload.get("ip"):
            return str(payload["ip"]).strip()

        text_ip = self.http.get_text("https://ifconfig.me/ip")
        if text_ip:
            return text_ip.strip()

        return None

    def get_location_from_ip(self, ip: str | None = None) -> LocationInfo | None:
        return resolve_ip_location(self.http, ip)

    def describe_public_ip(self) -> str:
        ip = self.get_public_ip()
        if not ip:
            return self.personality.finalize(
                "I could not fetch your public IP right now. Network diagnostics are temporarily unavailable."
            )
        return self.personality.finalize(f"Public IP: {ip}.")

    def describe_ip_location(self) -> str:
        location = self.get_location_from_ip()
        if not location:
            return self.personality.finalize("I could not resolve your network location right now.")

        tz = f" ({location.timezone})" if location.timezone else ""
        message = (
            f"Network location: {location.label}{tz}. "
            f"Coordinates {location.latitude:.4f}, {location.longitude:.4f}."
        )
        return self.personality.finalize(message)

    def get_system_status_snapshot(self) -> str:
        now = datetime.datetime.now().astimezone()
        cpu = "unavailable"
        ram = "unavailable"

        if psutil is not None:
            try:
                cpu = f"{psutil.cpu_percent(interval=None):.1f}%"
            except Exception:
                pass

            try:
                ram = f"{psutil.virtual_memory().percent:.1f}%"
            except Exception:
                pass

        uptime = self._format_uptime(int(time.time() - self._boot_time))
        message = (
            f"System status snapshot: Date {now.strftime('%Y-%m-%d')}, "
            f"Time {now.strftime('%H:%M:%S')} ({now.tzname() or 'local'}), "
            f"CPU {cpu}, RAM {ram}, Uptime {uptime}."
        )
        return self.personality.finalize(message)

    def get_temporal_snapshot(self) -> str:
        now = datetime.datetime.now().astimezone()
        message = (
            f"Local time is {now.strftime('%I:%M %p')}, "
            f"and today is {now.strftime('%A, %B %d, %Y')} "
            f"in {now.tzname() or 'local time'}."
        )
        return self.personality.finalize(message)

    def get_update_status(self) -> str:
        message = (
            f"System update status: JARVIS version {VERSION}. "
            "Automatic software update tracking is not configured in this build, "
            "so I cannot provide last or next scheduled update details yet."
        )
        return self.personality.finalize(message)

    def _run_speedtest_worker(self) -> None:
        result, error = self._execute_speedtest_once()

        with self._speedtest_lock:
            self._speedtest_running = False
            self._last_speedtest = result
            self._last_speedtest_error = error

    def run_speedtest_now(self) -> str:
        with self._speedtest_lock:
            if self._speedtest_running:
                return self.personality.finalize("Speed test is already running. Ask for the result in a few seconds.")

            self._speedtest_running = True
            self._last_speedtest_error = None

        result: SpeedtestResult | None = None
        error: str | None = None
        started_at = time.perf_counter()
        try:
            result, error = self._execute_speedtest_once()
            if result is not None:
                elapsed = time.perf_counter() - started_at
                if elapsed < self._min_sync_speedtest_seconds:
                    time.sleep(self._min_sync_speedtest_seconds - elapsed)
        finally:
            with self._speedtest_lock:
                self._speedtest_running = False
                self._last_speedtest = result
                self._last_speedtest_error = error

        if result is None:
            if error == "missing_speedtest_module" or (error and "No module named 'speedtest'" in error):
                return self.personality.finalize("Speed test couldn't run because required module is missing.")
            return self.personality.finalize(
                "I couldn't confirm your speed yet because the speed test failed. Please try again."
            )

        return self._render_speedtest_result(result)

    def start_speedtest(self) -> str:
        with self._speedtest_lock:
            if self._speedtest_running:
                return self.personality.finalize("Speed test is already running. Ask for the result in a few seconds.")

            self._speedtest_running = True
            self._last_speedtest_error = None
            self._speedtest_thread = threading.Thread(
                target=self._run_speedtest_worker,
                name="jarvis-speedtest-worker",
                daemon=True,
            )
            self._speedtest_thread.start()

        return self.personality.finalize("Speed test started in the background. Ask for the result shortly.")

    def get_last_speedtest_snapshot(self) -> dict[str, float | str] | None:
        with self._speedtest_lock:
            if self._last_speedtest is None:
                return None
            res = self._last_speedtest

        return {
            "download_mbps": round(res.download_mbps, 3),
            "upload_mbps": round(res.upload_mbps, 3),
            "ping_ms": round(res.ping_ms, 3),
            "timestamp": round(res.timestamp, 3),
            "server_name": str(res.server_name or ""),
            "server_host": str(res.server_host or ""),
            "server_country": str(res.server_country or ""),
            "server_sponsor": str(res.server_sponsor or ""),
        }

    def get_last_speedtest_error(self) -> str | None:
        with self._speedtest_lock:
            return self._last_speedtest_error

    def is_speedtest_running(self) -> bool:
        with self._speedtest_lock:
            return self._speedtest_running

    def get_speedtest_result(self) -> str:
        with self._speedtest_lock:
            if self._speedtest_running:
                return self.personality.finalize("Speed test is still running. Give it a moment.")

            if self._last_speedtest is None:
                if self._last_speedtest_error:
                    if self._last_speedtest_error == "missing_speedtest_module" or "No module named 'speedtest'" in self._last_speedtest_error:
                        return self.personality.finalize(
                            "Speed test couldn't run because required module is missing."
                        )
                    return self.personality.finalize(
                        "I couldn't confirm your speed yet because the speed test failed. Let's run it again."
                    )
                return self.personality.finalize("I couldn't confirm your speed yet. Let's run a speed test.")

            res = self._last_speedtest

        return self._render_speedtest_result(res)

    def get_speedtest_assessment(self) -> str:
        with self._speedtest_lock:
            if self._speedtest_running:
                return self.personality.finalize("Speed test is still running. Give it a moment before assessment.")
            if self._last_speedtest is None:
                if self._last_speedtest_error == "missing_speedtest_module" or (
                    self._last_speedtest_error and "No module named 'speedtest'" in self._last_speedtest_error
                ):
                    return self.personality.finalize(
                        "Speed test couldn't run because required module is missing."
                    )
                return self.personality.finalize("I couldn't confirm your speed yet. Let's run it again.")
            res = self._last_speedtest

        location = self.get_location_from_ip()
        avg_low, avg_high, country_label = self._speed_benchmark(location.country if location else None)

        if res.download_mbps < avg_low:
            guidance = (
                "You can improve this by testing on Ethernet, reducing peak-time congestion, "
                "optimizing router placement, and checking for a higher ISP plan tier."
            )
            verdict = "below typical"
        elif res.download_mbps <= avg_high:
            guidance = "This is serviceable for regular work and streaming."
            verdict = "within typical"
        else:
            guidance = "This is strong performance for most heavy-use scenarios."
            verdict = "above typical"

        message = (
            f"Your measured download speed is {res.download_mbps:.1f} Mbps, which is {verdict} "
            f"for common {country_label} ranges ({avg_low:.0f}-{avg_high:.0f} Mbps). {guidance}"
        )
        return self.personality.finalize(message)

    def handle_speedtest_query(self, text: str) -> str:
        query = (text or "").lower()

        if any(word in query for word in ("background", "in background", "run in background", "start in background")):
            return self.start_speedtest()

        if any(word in query for word in ("average", "fast", "slow", "good", "better", "improve", "upgrade")):
            return self.get_speedtest_assessment()

        if any(word in query for word in ("result", "status", "report", "latest", "show", "check", "again")):
            if not self.is_speedtest_running() and self.get_last_speedtest_snapshot() is None:
                return self.run_speedtest_now()
            return self.get_speedtest_result()

        return self.run_speedtest_now()

    def close(self) -> None:
        with self._speedtest_lock:
            thread = self._speedtest_thread

        if thread and thread.is_alive():
            thread.join(timeout=0.2)
