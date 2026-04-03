"""
services/actions/screen_processor.py
Production-grade screen and camera processing with local frame analysis,
cross-frame memory, lightweight object tracking, and optional Gemini live
enrichment.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import cv2

    _CV2_OK = True
except Exception:
    cv2 = None  # type: ignore[assignment]
    _CV2_OK = False

try:
    import numpy as np

    _NP_OK = True
except Exception:
    np = None  # type: ignore[assignment]
    _NP_OK = False

try:
    import mss
    import mss.tools

    _MSS_OK = True
except Exception:
    mss = None  # type: ignore[assignment]
    _MSS_OK = False

try:
    import pyaudio

    _PYAUDIO_OK = True
except Exception:
    pyaudio = None  # type: ignore[assignment]
    _PYAUDIO_OK = False

try:
    from google import genai
    from google.genai import types

    _GENAI_OK = True
except Exception:
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    _GENAI_OK = False

from core.settings import AppConfig

try:
    import PIL.Image
    try:
        from PIL import ImageGrab
    except Exception:
        ImageGrab = None  # type: ignore[assignment]

    _PIL_OK = True
except Exception:
    _PIL_OK = False
    ImageGrab = None  # type: ignore[assignment]


LIVE_MODEL = os.getenv("SCREEN_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
FORMAT = pyaudio.paInt16 if _PYAUDIO_OK else 0
CHANNELS = 1
RECEIVE_SAMPLE_RATE = 24000
IMG_MAX_W = 640
IMG_MAX_H = 360
JPEG_Q = 55
FRAME_HISTORY_LIMIT = max(4, min(64, int(os.getenv("SCREEN_FRAME_HISTORY", "12"))))
TRACK_MAX_STALE_FRAMES = max(2, min(40, int(os.getenv("SCREEN_TRACK_MAX_STALE_FRAMES", "8"))))
TRACK_IOU_THRESHOLD = 0.20
SCREEN_CACHE_DIR = Path(os.getenv("SCREEN_CACHE_DIR", "data/screen_cache"))

SYSTEM_PROMPT = (
    "You are JARVIS. Analyze visual input with precision. "
    "Be concise and practical. Keep response under two short sentences."
)


@dataclass(frozen=True)
class FrameSnapshot:
    frame_id: int
    mode: str
    mime_type: str
    captured_at: float
    captured_at_iso: str
    width: int
    height: int
    brightness: float
    entropy: float
    motion_score: float
    objects: list[dict[str, Any]]
    summary: str
    image_path: str


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _get_api_key() -> str:
    config = AppConfig.from_env(".env")
    key = str(config.gemini_api_key or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing")
    return key


def _to_jpeg(img_bytes: bytes) -> bytes:
    if not _PIL_OK:
        return img_bytes

    image = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
    image.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
    return buf.getvalue()


def _capture_screenshot() -> bytes:
    if _MSS_OK:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            png_bytes = mss.tools.to_png(shot.rgb, shot.size)
        return _to_jpeg(png_bytes)

    if _PIL_OK and ImageGrab is not None:
        shot = ImageGrab.grab(all_screens=True).convert("RGB")
        shot.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
        buf = io.BytesIO()
        shot.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
        return buf.getvalue()

    raise RuntimeError("Screenshot capture backend unavailable (mss/ImageGrab missing)")


def _capture_camera() -> bytes:
    if not _CV2_OK:
        raise RuntimeError("OpenCV camera backend unavailable")

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError("Camera could not be opened")

    for _ in range(6):
        cap.read()

    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError("Could not capture camera frame")

    if _PIL_OK:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = PIL.Image.fromarray(rgb)
        image.thumbnail([IMG_MAX_W, IMG_MAX_H], PIL.Image.BILINEAR)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=JPEG_Q, optimize=False)
        return buf.getvalue()

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    if not ok:
        raise RuntimeError("Could not encode camera frame")
    return buf.tobytes()


def _normalize_mode(raw_mode: str, user_text: str) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode in {"camera", "cam", "webcam"}:
        return "camera"
    if mode in {"screen", "display", "monitor", "desktop"}:
        return "screen"

    lowered = (user_text or "").strip().lower()
    if re.search(r"\b(camera|webcam|front camera|back camera)\b", lowered):
        return "camera"
    return "screen"


def _resolve_action(parameters: dict[str, Any], user_text: str) -> str:
    explicit = str(parameters.get("action") or "").strip().lower()
    normalized = {
        "view": "view_now",
        "show": "view_now",
        "analyze": "analyze",
        "inspect": "analyze",
        "latest": "view_latest",
        "recall": "view_latest",
    }.get(explicit, explicit)
    if normalized in {"view_now", "view_latest", "analyze"}:
        return normalized

    lowered = (user_text or "").strip().lower()
    if re.search(r"\b(latest|last|previous|recent)\b.*\b(screen|camera|frame|capture)\b", lowered):
        return "view_latest"

    if re.search(
        r"\b(view|show|see|watch|analyze|inspect)\b.*\b(screen|display|monitor|camera|webcam)\b|"
        r"\bwhat(?:'s| is)\s+on\s+my\s+(screen|display|camera)\b",
        lowered,
    ):
        return "view_now"

    return "analyze"


def _resolve_live_enrichment(parameters: dict[str, Any], action: str) -> bool:
    for key in ("live_enrichment", "enrich", "live"):
        if key not in parameters:
            continue
        value = parameters.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False

    if action == "view_latest":
        return False
    return True


def _default_prompt(mode: str, action: str) -> str:
    if action == "view_latest":
        return f"Recall the latest {mode} frame summary."
    if action == "view_now":
        return f"Describe what is visible in this {mode} frame."
    return f"Analyze this {mode} frame and summarize key details."


class _ObjectTracker:
    def __init__(self, *, iou_threshold: float = TRACK_IOU_THRESHOLD, max_stale_frames: int = TRACK_MAX_STALE_FRAMES) -> None:
        self._iou_threshold = iou_threshold
        self._max_stale_frames = max_stale_frames
        self._next_track_id = 1
        self._tracks: dict[int, dict[str, Any]] = {}

    @staticmethod
    def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax1, ay1, aw, ah = a
        bx1, by1, bw, bh = b
        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h
        if inter_area <= 0:
            return 0.0

        area_a = max(1, aw * ah)
        area_b = max(1, bw * bh)
        union = area_a + area_b - inter_area
        if union <= 0:
            return 0.0
        return float(inter_area / union)

    def update(self, detections: list[dict[str, Any]], frame_id: int) -> list[dict[str, Any]]:
        assigned: set[int] = set()
        tracked_objects: list[dict[str, Any]] = []

        for detection in detections:
            bbox = detection.get("bbox")
            if not isinstance(bbox, tuple) or len(bbox) != 4:
                continue

            best_track_id: int | None = None
            best_score = 0.0
            for track_id, track in self._tracks.items():
                if track_id in assigned:
                    continue
                score = self._iou(bbox, track.get("bbox", (0, 0, 0, 0)))
                if score > best_score:
                    best_score = score
                    best_track_id = track_id

            if best_track_id is not None and best_score >= self._iou_threshold:
                track = self._tracks[best_track_id]
                track["bbox"] = bbox
                track["last_frame"] = frame_id
                track["seen"] = int(track.get("seen", 1)) + 1
                track["confidence"] = max(float(detection.get("confidence") or 0.4), float(track.get("confidence") or 0.4) * 0.85)
                assigned.add(best_track_id)
                tracked_objects.append(self._serialize_track(best_track_id, track, detection))
                continue

            track_id = self._next_track_id
            self._next_track_id += 1
            track = {
                "bbox": bbox,
                "last_frame": frame_id,
                "seen": 1,
                "confidence": float(detection.get("confidence") or 0.4),
            }
            self._tracks[track_id] = track
            assigned.add(track_id)
            tracked_objects.append(self._serialize_track(track_id, track, detection))

        stale_ids = [
            track_id
            for track_id, track in self._tracks.items()
            if frame_id - int(track.get("last_frame", frame_id)) > self._max_stale_frames
        ]
        for track_id in stale_ids:
            self._tracks.pop(track_id, None)

        return tracked_objects[:8]

    @staticmethod
    def _serialize_track(track_id: int, track: dict[str, Any], detection: dict[str, Any]) -> dict[str, Any]:
        x, y, w, h = track.get("bbox", (0, 0, 0, 0))
        return {
            "track_id": int(track_id),
            "label": "visual_region",
            "bbox": {
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
            },
            "area_ratio": round(float(detection.get("area_ratio") or 0.0), 4),
            "confidence": round(float(track.get("confidence") or 0.4), 3),
            "age_frames": int(track.get("seen") or 1),
        }


class _FrameMemory:
    def __init__(self, *, history_limit: int, cache_dir: Path) -> None:
        self._history_limit = max(1, history_limit)
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._frames: deque[FrameSnapshot] = deque(maxlen=self._history_limit)
        self._tracker = _ObjectTracker()
        self._previous_gray_by_mode: dict[str, Any] = {}
        self._next_frame_id = 1

    def reset(self) -> None:
        with self._lock:
            self._frames.clear()
            self._tracker = _ObjectTracker()
            self._previous_gray_by_mode.clear()
            self._next_frame_id = 1

    def latest(self, mode: str | None = None) -> FrameSnapshot | None:
        with self._lock:
            for frame in reversed(self._frames):
                if mode is None or frame.mode == mode:
                    return frame
        return None

    def frame_count(self) -> int:
        with self._lock:
            return len(self._frames)

    def history_context(self, snapshot: FrameSnapshot) -> dict[str, Any]:
        with self._lock:
            previous: FrameSnapshot | None = None
            for frame in reversed(self._frames):
                if frame.frame_id == snapshot.frame_id:
                    continue
                if frame.mode == snapshot.mode:
                    previous = frame
                    break

            previous_age_ms = None
            if previous is not None:
                previous_age_ms = max(0, int((snapshot.captured_at - previous.captured_at) * 1000))

            return {
                "frames_stored": len(self._frames),
                "history_limit": self._history_limit,
                "previous_frame_age_ms": previous_age_ms,
            }

    def record(
        self,
        *,
        mode: str,
        mime_type: str,
        image_bytes: bytes,
    ) -> FrameSnapshot:
        with self._lock:
            frame_id = self._next_frame_id
            self._next_frame_id += 1

            prev_gray = self._previous_gray_by_mode.get(mode)
            width, height, brightness, entropy, motion_score, detections, gray = self._analyze_frame(image_bytes, prev_gray)
            if gray is not None:
                self._previous_gray_by_mode[mode] = gray

            objects = self._tracker.update(detections, frame_id)

            ts = time.time()
            image_path = self._persist_image(mode=mode, mime_type=mime_type, image_bytes=image_bytes, captured_at=ts)
            summary = self._build_summary(
                mode=mode,
                width=width,
                height=height,
                brightness=brightness,
                motion_score=motion_score,
                object_count=len(objects),
            )

            snapshot = FrameSnapshot(
                frame_id=frame_id,
                mode=mode,
                mime_type=mime_type,
                captured_at=ts,
                captured_at_iso=_iso_utc(ts),
                width=width,
                height=height,
                brightness=round(brightness, 2),
                entropy=round(entropy, 3),
                motion_score=round(motion_score, 4),
                objects=objects,
                summary=summary,
                image_path=image_path,
            )
            self._frames.append(snapshot)
            return snapshot

    @staticmethod
    def _build_summary(
        *,
        mode: str,
        width: int,
        height: int,
        brightness: float,
        motion_score: float,
        object_count: int,
    ) -> str:
        if brightness >= 160:
            lighting = "bright"
        elif brightness <= 85:
            lighting = "dim"
        else:
            lighting = "balanced"

        motion_desc = "motion detected" if motion_score >= 0.08 else "scene mostly static"
        if object_count <= 0:
            object_desc = "no stable object regions"
        elif object_count == 1:
            object_desc = "1 tracked region"
        else:
            object_desc = f"{object_count} tracked regions"

        shape = f"{width}x{height}" if width > 0 and height > 0 else "unknown resolution"
        return f"{mode.capitalize()} frame {shape}, {lighting} lighting, {object_desc}; {motion_desc}."

    def _persist_image(self, *, mode: str, mime_type: str, image_bytes: bytes, captured_at: float) -> str:
        ext = ".jpg" if "jpeg" in (mime_type or "").lower() else ".png"
        safe_mode = "camera" if mode == "camera" else "screen"
        latest_path = self._cache_dir / f"latest_{safe_mode}{ext}"
        stamped_path = self._cache_dir / f"{safe_mode}_{int(captured_at * 1000)}{ext}"

        try:
            latest_path.write_bytes(image_bytes)
            stamped_path.write_bytes(image_bytes)
            return str(latest_path)
        except Exception:
            return ""

    @staticmethod
    def _entropy_from_hist(hist: list[int]) -> float:
        total = float(sum(hist))
        if total <= 0:
            return 0.0

        entropy = 0.0
        for count in hist:
            if count <= 0:
                continue
            p = float(count) / total
            entropy -= p * math.log2(p)
        return entropy

    @staticmethod
    def _detect_regions(gray: Any, width: int, height: int) -> list[dict[str, Any]]:
        if not (_CV2_OK and _NP_OK):
            return []

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 60, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)

        contour_result = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = contour_result[0] if len(contour_result) == 2 else contour_result[1]

        detections: list[dict[str, Any]] = []
        frame_area = max(1, width * height)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w <= 6 or h <= 6:
                continue

            area_ratio = float((w * h) / frame_area)
            if area_ratio < 0.015 or area_ratio > 0.80:
                continue

            aspect_ratio = float(w) / max(float(h), 1.0)
            confidence = 0.35 + min(0.55, area_ratio * 2.0)
            if 0.3 <= aspect_ratio <= 3.5:
                confidence += 0.05

            detections.append(
                {
                    "bbox": (int(x), int(y), int(w), int(h)),
                    "area_ratio": round(area_ratio, 4),
                    "confidence": min(0.95, confidence),
                }
            )

        detections.sort(key=lambda item: float(item.get("area_ratio") or 0.0), reverse=True)
        return detections[:8]

    def _analyze_frame(
        self,
        image_bytes: bytes,
        previous_gray: Any,
    ) -> tuple[int, int, float, float, float, list[dict[str, Any]], Any]:
        if _CV2_OK and _NP_OK:
            try:
                frame_array = np.frombuffer(image_bytes, dtype=np.uint8)
                frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                if frame is not None:
                    height, width = frame.shape[:2]
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    brightness = float(gray.mean())

                    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
                    hist_vals = [int(x) for x in hist.flatten().tolist()]
                    entropy = self._entropy_from_hist(hist_vals)

                    motion_score = 0.0
                    if previous_gray is not None and getattr(previous_gray, "shape", None) == gray.shape:
                        diff = cv2.absdiff(gray, previous_gray)
                        motion_score = float(diff.mean() / 255.0)

                    detections = self._detect_regions(gray, width, height)
                    return width, height, brightness, entropy, motion_score, detections, gray
            except Exception:
                pass

        if _PIL_OK:
            try:
                image = PIL.Image.open(io.BytesIO(image_bytes)).convert("L")
                width, height = image.size
                hist = image.histogram()
                total = float(sum(hist))
                brightness = 0.0
                if total > 0:
                    brightness = sum(level * count for level, count in enumerate(hist[:256])) / total
                entropy = self._entropy_from_hist([int(v) for v in hist[:256]])
                return width, height, float(brightness), float(entropy), 0.0, [], None
            except Exception:
                pass

        return 0, 0, 0.0, 0.0, 0.0, [], None


class _LiveSession:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any = None
        self._out_queue: asyncio.Queue[tuple[bytes, str, str]] | None = None
        self._audio_in: asyncio.Queue[bytes] | None = None
        self._ready = threading.Event()
        self._start_guard = threading.Lock()
        self._player: Any = None
        self._pya = pyaudio.PyAudio() if _PYAUDIO_OK else None

    def start(self, player: Any = None, *, wait_timeout: float = 0.0) -> None:
        if not _GENAI_OK:
            raise RuntimeError("google-genai dependency unavailable")

        with self._start_guard:
            if self._thread and self._thread.is_alive():
                if player is not None:
                    self._player = player
            else:
                self._player = player
                self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ScreenProcessSession")
                self._thread.start()

        if wait_timeout > 0 and not self._ready.wait(timeout=wait_timeout):
            raise RuntimeError(f"Screen processor live session did not start within {wait_timeout:.1f}s")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        self._out_queue = asyncio.Queue(maxsize=24)
        self._audio_in = asyncio.Queue()

        if not _GENAI_OK:
            self._ready.clear()
            return

        client = genai.Client(api_key=_get_api_key(), http_options={"api_version": "v1beta"})

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            system_instruction=SYSTEM_PROMPT,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                )
            ),
        )

        while True:
            try:
                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    self._session = session
                    self._ready.set()
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._send_loop())
                        tg.create_task(self._recv_loop())
                        tg.create_task(self._play_loop())
            except Exception:
                await asyncio.sleep(1.2)
            finally:
                self._session = None
                self._ready.clear()

    async def _send_loop(self) -> None:
        assert self._out_queue is not None
        while True:
            image_bytes, mime_type, user_text = await self._out_queue.get()
            if not self._session:
                continue

            try:
                encoded = base64.b64encode(image_bytes).decode("utf-8")
                await self._session.send_client_content(
                    turns={
                        "parts": [
                            {"inline_data": {"mime_type": mime_type, "data": encoded}},
                            {"text": user_text},
                        ]
                    },
                    turn_complete=True,
                )
            except Exception:
                continue

    async def _recv_loop(self) -> None:
        assert self._audio_in is not None
        transcript_chunks: list[str] = []

        try:
            assert self._session is not None
            async for response in self._session.receive():
                if response.data:
                    await self._audio_in.put(response.data)

                server_content = response.server_content
                if not server_content:
                    continue

                if server_content.output_transcription and server_content.output_transcription.text:
                    chunk = server_content.output_transcription.text.strip()
                    if chunk:
                        transcript_chunks.append(chunk)

                if server_content.turn_complete:
                    if transcript_chunks and self._player is not None and hasattr(self._player, "write_log"):
                        full = re.sub(r"\s+", " ", " ".join(transcript_chunks)).strip()
                        if full:
                            self._player.write_log(f"Jarvis: {full}")
                    transcript_chunks = []
        except Exception:
            transcript_chunks = []
            await asyncio.sleep(0.3)

    async def _play_loop(self) -> None:
        assert self._audio_in is not None

        if self._pya is None:
            while True:
                await self._audio_in.get()

        try:
            stream = await asyncio.to_thread(
                self._pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=RECEIVE_SAMPLE_RATE,
                output=True,
            )
        except Exception:
            while True:
                await self._audio_in.get()

        try:
            while True:
                chunk = await self._audio_in.get()
                await asyncio.to_thread(stream.write, chunk)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def analyze(self, image_bytes: bytes, mime_type: str, user_text: str) -> bool:
        if not self._loop or not self._out_queue:
            return False

        future = asyncio.run_coroutine_threadsafe(self._out_queue.put((image_bytes, mime_type, user_text)), self._loop)
        try:
            future.result(timeout=0.35)
            return True
        except Exception:
            return False

    def is_ready(self) -> bool:
        return self._session is not None


_live = _LiveSession()
_frame_memory = _FrameMemory(history_limit=FRAME_HISTORY_LIMIT, cache_dir=SCREEN_CACHE_DIR)
_started = False
_start_lock = threading.Lock()


def _ensure_started(player: Any = None, *, wait_timeout: float = 0.0) -> None:
    global _started
    with _start_lock:
        if not _started:
            _live.start(player=player, wait_timeout=wait_timeout)
            _started = True
        elif player is not None:
            _live._player = player


def _build_error_payload(*, mode: str, action: str, request_text: str, error_code: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "action": "screen_process",
        "success": False,
        "verified": False,
        "message": message,
        "error": error_code,
        "source": "screen_processor",
        "mode": mode,
        "request": {
            "action": action,
            "text": request_text,
        },
        "analysis": {
            "summary": "",
            "objects": [],
            "history": {
                "frames_stored": _frame_memory.frame_count(),
                "history_limit": FRAME_HISTORY_LIMIT,
                "previous_frame_age_ms": None,
            },
            "from_cache": False,
            "latency_ms": 0,
        },
        "view": {
            "available": False,
            "image_path": "",
        },
        "live_session": {
            "requested": False,
            "queued": False,
            "session_ready": _live.is_ready(),
            "model": LIVE_MODEL,
            "enrichment": "unavailable",
            "error": "",
        },
    }


def _build_success_payload(
    *,
    snapshot: FrameSnapshot,
    action: str,
    request_text: str,
    from_cache: bool,
    fallback_capture: bool,
    live_info: dict[str, Any],
    latency_ms: int,
) -> dict[str, Any]:
    if from_cache:
        message = f"Showing latest cached {snapshot.mode} frame analysis."
    elif fallback_capture:
        message = f"No cached {snapshot.mode} frame was available, captured a new frame for analysis."
    else:
        message = f"Captured {snapshot.mode} frame and generated local analysis."

    if bool(live_info.get("queued")):
        message += " Live enrichment queued."
    elif bool(live_info.get("requested")) and str(live_info.get("enrichment") or "") in {"session_not_ready", "unavailable"}:
        message += " Live enrichment is temporarily unavailable, but local analysis is ready."

    history = _frame_memory.history_context(snapshot)

    return {
        "status": "success",
        "action": "screen_process",
        "success": True,
        "verified": True,
        "message": message,
        "error": "",
        "source": "screen_processor",
        "mode": snapshot.mode,
        "request": {
            "action": action,
            "text": request_text,
        },
        "analysis": {
            "frame_id": snapshot.frame_id,
            "captured_at": snapshot.captured_at_iso,
            "summary": snapshot.summary,
            "metrics": {
                "width": snapshot.width,
                "height": snapshot.height,
                "brightness": snapshot.brightness,
                "entropy": snapshot.entropy,
                "motion_score": snapshot.motion_score,
            },
            "objects": list(snapshot.objects),
            "history": history,
            "from_cache": from_cache,
            "latency_ms": latency_ms,
        },
        "view": {
            "available": bool(snapshot.image_path),
            "image_path": snapshot.image_path,
            "frame_id": snapshot.frame_id,
            "captured_at": snapshot.captured_at_iso,
        },
        "live_session": live_info,
    }


def screen_process(
    parameters: dict[str, Any],
    response: str | None = None,
    player: Any = None,
    session_memory: Any = None,
) -> dict[str, Any]:
    del response
    del session_memory

    params = parameters or {}
    request_start = time.perf_counter()

    raw_text = str(params.get("text") or params.get("user_text") or "").strip()
    action = _resolve_action(params, raw_text)
    mode = _normalize_mode(str(params.get("angle") or params.get("mode") or "screen"), raw_text)
    user_text = raw_text or _default_prompt(mode, action)

    if action == "view_latest":
        latest = _frame_memory.latest(mode=mode)
        if latest is not None:
            elapsed = max(0, int((time.perf_counter() - request_start) * 1000))
            live_info = {
                "requested": False,
                "queued": False,
                "session_ready": _live.is_ready(),
                "model": LIVE_MODEL,
                "enrichment": "skipped",
                "error": "",
            }
            return _build_success_payload(
                snapshot=latest,
                action=action,
                request_text=user_text,
                from_cache=True,
                fallback_capture=False,
                live_info=live_info,
                latency_ms=elapsed,
            )

    capture_error = ""
    image_bytes = b""
    mime_type = "image/jpeg"

    try:
        if mode == "camera":
            image_bytes = _capture_camera()
            mime_type = "image/jpeg"
        else:
            image_bytes = _capture_screenshot()
            mime_type = "image/jpeg" if _PIL_OK else "image/png"
    except Exception as exc:
        capture_error = str(exc)

    if not image_bytes:
        return _build_error_payload(
            mode=mode,
            action=action,
            request_text=user_text,
            error_code="capture_failed",
            message=f"Could not capture {mode} frame: {capture_error or 'unknown_capture_error'}",
        )

    snapshot = _frame_memory.record(mode=mode, mime_type=mime_type, image_bytes=image_bytes)

    live_requested = _resolve_live_enrichment(params, action)
    live_info: dict[str, Any] = {
        "requested": live_requested,
        "queued": False,
        "session_ready": _live.is_ready(),
        "model": LIVE_MODEL,
        "enrichment": "skipped" if not live_requested else "deferred",
        "error": "",
    }

    if live_requested:
        try:
            _ensure_started(player=player, wait_timeout=0.0)
            live_info["session_ready"] = _live.is_ready()
            queued = _live.analyze(image_bytes, mime_type, user_text)
            live_info["queued"] = queued
            if queued:
                live_info["enrichment"] = "queued"
            else:
                live_info["enrichment"] = "session_not_ready"
                live_info["error"] = "live_session_not_ready"
        except Exception as exc:
            live_info["enrichment"] = "unavailable"
            live_info["error"] = str(exc)

    elapsed = max(0, int((time.perf_counter() - request_start) * 1000))
    return _build_success_payload(
        snapshot=snapshot,
        action=action,
        request_text=user_text,
        from_cache=False,
        fallback_capture=action == "view_latest",
        live_info=live_info,
        latency_ms=elapsed,
    )


def warmup_session(player: Any = None, *, wait_timeout: float = 8.0) -> None:
    try:
        _ensure_started(player=player, wait_timeout=wait_timeout)
    except Exception:
        pass


def view_latest_snapshot(*, mode: str = "screen") -> dict[str, Any]:
    """Return cached frame analysis without forcing a new capture."""
    return screen_process(
        {
            "angle": mode,
            "action": "view_latest",
            "live_enrichment": False,
        }
    )


def _reset_state_for_tests() -> None:
    """Test-only helper to reset frame memory without restarting process."""
    _frame_memory.reset()


if __name__ == "__main__":
    print("screen_processor standalone test")
    mode = input("screen/camera (default screen): ").strip().lower() or "screen"
    request = input("Question: ").strip() or "What do you see?"

    warmup_session()
    print("Session ready")
    result = screen_process({"angle": mode, "text": request}, player=None)
    print(f"Result: {result.get('status')} | {result.get('message')}")
    time.sleep(8)