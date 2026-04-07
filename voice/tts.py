# ==============================================================================
# File: voice/tts.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Edge TTS Engine - Turn-Based Voice Synthesis
#
#    - Turn-based TTS engine using Microsoft Edge neural voices.
#    - Fixed default voice: en-GB-RyanNeural (configurable via env).
#    - Turn management: interrupt() increments turn ID, clears speech queue,
#      and stops active playback. Old-turn chunks are dropped safely.
#    - _prepare_for_tts(): strips markdown, list markers, normalizes punctuation.
#    - Threaded worker: _tts_worker processes queued chunks with turn validation.
#    - Low-latency mode: streams raw PCM chunks directly from edge-tts to PyAudio.
#    - Low-latency fallback: if raw PCM is unavailable, stream compressed edge-tts
#      audio through ffmpeg decode pipe and play PCM in real time.
#    - Buffered fallback: synthesizes full payload and plays WAV/MP3 only when
#      no streaming path is available.
#    - Windows fallback: if non-WAV output is returned, playback uses MCI.
#    - on_speaking_start/stop callbacks keep UI mode in sync with speech state.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import asyncio
import io
import inspect
import logging
import os
import queue
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any, Callable

from core.settings import AppConfig

logger = logging.getLogger(__name__)


class EdgeNeuralTTS:
    """edge-tts backend with turn-based interruption safety."""

    def __init__(
        self,
        config: AppConfig,
        *,
        on_speaking_start: Callable[[], None] | None = None,
        on_speaking_stop: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self._on_speaking_start = on_speaking_start
        self._on_speaking_stop = on_speaking_stop

        self._speech_queue: queue.Queue[tuple[int, list[str]]] = queue.Queue()
        self._audio_queue: queue.Queue[tuple[int, bytes | None, bool]] = queue.Queue(maxsize=96)
        self._stop_worker = threading.Event()
        self._playback_stop = threading.Event()
        self._turn_lock = threading.Lock()
        self._tts_lock = threading.Lock()

        self._turn_id = 0
        self._pending_chunks = 0
        self._pcm_turn_events: dict[int, threading.Event] = {}
        self._is_speaking = False

        self._stream: Any | None = None
        self._audio_interface: Any | None = None
        self._playback_stream: Any | None = None
        self._playback_audio_interface: Any | None = None
        self._supports_edge_output_format: bool | None = None
        self._supports_transcoded_stream: bool | None = None
        self._ffmpeg_binary: str | None = None
        self._warmup_started = False
        self._warmup_lock = threading.Lock()
        self._edge_session: Any | None = None
        self._edge_websocket: Any | None = None
        self._edge_session_format: str | None = None
        self._edge_loop: asyncio.AbstractEventLoop | None = None

        self._playback_thread = threading.Thread(
            target=self._playback_worker,
            name="jarvis-edge-tts-playback",
            daemon=True,
        )
        self._playback_thread.start()
        self._speaker_thread = threading.Thread(
            target=self._tts_worker,
            name="jarvis-edge-tts-worker",
            daemon=True,
        )
        self._speaker_thread.start()
        self._start_background_warmup()

    def _start_background_warmup(self) -> None:
        with self._warmup_lock:
            if self._warmup_started:
                return
            self._warmup_started = True

        threading.Thread(
            target=self._warm_edge_backend,
            name="jarvis-edge-tts-warmup",
            daemon=True,
        ).start()

    def _warm_edge_backend(self) -> None:
        # Resolve local capability checks eagerly; the persistent websocket session
        # is warmed inside the worker thread where the asyncio loop lives.
        try:
            self._edge_supports_output_format()
            self._resolve_ffmpeg_binary()
        except Exception as exc:
            logger.debug("Edge TTS warmup skipped: %s", exc)

    def _handle_speaking_start(self) -> None:
        if self._on_speaking_start:
            try:
                self._on_speaking_start()
            except Exception:
                pass

    def _handle_speaking_stop(self) -> None:
        if self._on_speaking_stop:
            try:
                self._on_speaking_stop()
            except Exception:
                pass

    def _clear_speech_queue(self) -> None:
        while True:
            try:
                self._speech_queue.get_nowait()
            except queue.Empty:
                break

    def _clear_audio_queue(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def _release_active_audio(self) -> None:
        stream: Any | None = None
        audio_interface: Any | None = None

        with self._tts_lock:
            stream = self._stream
            audio_interface = self._audio_interface
            self._stream = None
            self._audio_interface = None
            self._is_speaking = False

        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

        if audio_interface is not None:
            try:
                audio_interface.terminate()
            except Exception:
                pass

    def _release_persistent_playback(self) -> None:
        stream: Any | None = None
        audio_interface: Any | None = None

        with self._tts_lock:
            stream = self._playback_stream
            audio_interface = self._playback_audio_interface
            self._playback_stream = None
            self._playback_audio_interface = None
            self._is_speaking = False

        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

        if audio_interface is not None:
            try:
                audio_interface.terminate()
            except Exception:
                pass

    def interrupt(self) -> int:
        pending_pcm_events: list[threading.Event] = []
        should_reset_stream = False
        with self._turn_lock:
            self._turn_id += 1
            should_reset_stream = self._pending_chunks > 0
            self._pending_chunks = 0
            pending_pcm_events = list(self._pcm_turn_events.values())
            self._pcm_turn_events.clear()
            active_turn = self._turn_id

        with self._tts_lock:
            should_reset_stream = bool(
                should_reset_stream
                or self._is_speaking
                or self._stream is not None
            )

        self._playback_stop.set()
        self._clear_speech_queue()
        self._clear_audio_queue()
        for event in pending_pcm_events:
            event.set()
        if should_reset_stream:
            self._request_edge_stream_reset()
        self._release_active_audio()
        return active_turn

    def _request_edge_stream_reset(self) -> None:
        loop = self._edge_loop
        if loop is None or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._reset_edge_stream_session_async(), loop)
        except Exception:
            pass

    async def _reset_edge_stream_session_async(self) -> None:
        await self._close_edge_stream_session_async()
        if self._stop_worker.is_set():
            return
        if self._can_stream_transcoded():
            try:
                await self._ensure_edge_stream_session_async(
                    output_format=self._preferred_edge_stream_format()
                )
            except Exception:
                pass

    @staticmethod
    def _prepare_for_tts(text: str) -> str:
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        cleaned = cleaned.replace("**", " ").replace("__", " ")
        cleaned = cleaned.translate(
            str.maketrans(
                {
                    "*": " ",
                    "_": " ",
                    "`": " ",
                    "#": " ",
                    "|": " ",
                    "~": " ",
                    "<": " ",
                    ">": " ",
                }
            )
        )
        cleaned = cleaned.replace("&", " and ")
        cleaned = cleaned.replace("%", " percent")
        cleaned = cleaned.replace("@", " at ")
        cleaned = re.sub(r"\s*[;:]\s*", ", ", cleaned)
        cleaned = re.sub(r"\s*[\u2013\u2014-]\s+", ", ", cleaned)
        cleaned = re.sub(r"\bvs\.?($|\s)", r"versus\1", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bjarvis\b", "Jarvis", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(
            r"\b([A-Z]{2,6})\b",
            lambda match: " ".join(match.group(1)) if match.group(1) not in {"AM", "PM"} else match.group(1),
            cleaned,
        )
        cleaned = re.sub(r"^\s*[-+]\s+", "", cleaned)
        cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned)
        cleaned = re.sub(r"\s*([,;:.!?])\s*", r"\1 ", cleaned)
        cleaned = re.sub(r"([,;:.!?]){2,}", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip()
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned

    def enqueue_text(self, chunk: str, turn_id: int) -> bool:
        text = " ".join(str(chunk or "").strip().split())
        text = text.strip('"')
        text = self._prepare_for_tts(text)
        if not text:
            return False

        segments = self._split_for_buffered_mode(text)
        if not segments:
            return False

        with self._turn_lock:
            if turn_id != self._turn_id:
                return False
            self._pending_chunks += 1

        self._speech_queue.put((turn_id, segments))
        return True

    def _split_for_buffered_mode(self, text: str) -> list[str]:
        if not text:
            return []

        if self._raw_pcm_sample_rate() is not None:
            return [text]

        if self._can_stream_transcoded():
            return self._split_for_streaming_mode(text)

        if len(text) < 120:
            return [text]

        max_probe = min(len(text), 180)
        min_probe = 55
        probe_text = text[:max_probe]

        boundary = -1
        for marker in (". ", "? ", "! ", "; ", ": ", ", "):
            idx = probe_text.rfind(marker)
            if idx >= min_probe:
                boundary = max(boundary, idx + len(marker))

        if boundary < min_probe:
            boundary = probe_text.rfind(" ")
            if boundary < min_probe:
                return [text]

        first = text[:boundary].strip()
        rest = text[boundary:].strip()

        if not first or not rest:
            return [text]

        return [first, rest]

    def _split_for_streaming_mode(self, text: str) -> list[str]:
        cleaned = str(text or "").strip()
        if not cleaned:
            return []

        if len(cleaned) < 140:
            return [cleaned]

        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
        if len(sentences) <= 1:
            sentences = [cleaned]

        chunks: list[str] = []
        current = ""
        min_chars = max(80, int(self.config.tts_chunk_chars) * 2)
        target_chars = max(min_chars, 90)

        def _split_long_sentence(sentence: str) -> list[str]:
            remaining = sentence.strip()
            parts: list[str] = []
            while len(remaining) > target_chars:
                probe_limit = min(len(remaining), target_chars + 30)
                boundary = -1
                for marker in (", ", "; ", ": ", " - ", " "):
                    idx = remaining.rfind(marker, min_chars, probe_limit)
                    if idx >= min_chars:
                        boundary = max(boundary, idx + len(marker))
                if boundary < min_chars:
                    boundary = target_chars
                parts.append(remaining[:boundary].strip())
                remaining = remaining[boundary:].strip()
            if remaining:
                parts.append(remaining)
            return parts

        normalized_sentences: list[str] = []
        for sentence in sentences:
            normalized_sentences.extend(_split_long_sentence(sentence))

        for sentence in normalized_sentences:
            candidate = sentence if not current else f"{current} {sentence}"
            if len(candidate) <= target_chars or len(current) < min_chars:
                current = candidate
                continue
            chunks.append(current.strip())
            current = sentence

        if current:
            chunks.append(current.strip())

        return chunks or [cleaned]

    def prefers_single_utterance(self) -> bool:
        """Return True when streaming playback is available and should stay contiguous."""
        # Keep the reply contiguous whenever we can stream audio incrementally.
        return self._raw_pcm_sample_rate() is not None or self._can_stream_transcoded()

    def wait_for_turn_completion(self, turn_id: int, timeout_s: float = 25.0) -> None:
        start = time.time()
        while True:
            with self._turn_lock:
                active_turn = self._turn_id
                pending_chunks = self._pending_chunks

            if turn_id != active_turn:
                return

            with self._tts_lock:
                speaking = self._is_speaking

            if pending_chunks <= 0 and not speaking:
                return

            if timeout_s > 0 and (time.time() - start) >= timeout_s:
                return

            time.sleep(0.02)

    def _is_active_turn(self, turn_id: int) -> bool:
        with self._turn_lock:
            return turn_id == self._turn_id

    @staticmethod
    def _clamp(value: int, low: int, high: int) -> int:
        return max(low, min(high, int(value)))

    @staticmethod
    def _parse_percent(value: str, default: int = 0) -> int:
        match = re.match(r"^\s*([+-]?\d+)\s*%\s*$", str(value or ""))
        if not match:
            return int(default)
        return int(match.group(1))

    @staticmethod
    def _parse_hz(value: str, default: int = 0) -> int:
        match = re.match(r"^\s*([+-]?\d+)\s*hz\s*$", str(value or ""), flags=re.IGNORECASE)
        if not match:
            return int(default)
        return int(match.group(1))

    @staticmethod
    def _format_percent(value: int) -> str:
        normalized = int(value)
        sign = "+" if normalized >= 0 else ""
        return f"{sign}{normalized}%"

    @staticmethod
    def _format_hz(value: int) -> str:
        normalized = int(value)
        sign = "+" if normalized >= 0 else ""
        return f"{sign}{normalized}Hz"

    def _prosody_for_text(self, text: str) -> tuple[str, str, str]:
        base_rate = self._parse_percent(self.config.edge_tts_rate, default=-5)
        base_pitch = self._parse_hz(self.config.edge_tts_pitch, default=-2)
        base_volume = self._parse_percent(self.config.edge_tts_volume, default=0)

        level = self._clamp(getattr(self.config, "edge_tts_expressiveness", 65), 0, 100)
        if level <= 0:
            return (
                self._format_percent(self._clamp(base_rate, -40, 40)),
                self._format_hz(self._clamp(base_pitch, -80, 80)),
                self._format_percent(self._clamp(base_volume, -25, 25)),
            )

        rate_span = max(1, int(level * 0.10))
        pitch_span = max(2, int(level * 0.22))
        volume_span = max(1, int(level * 0.08))

        question_lift = 4 if "?" in text else 0
        exclaim_energy = min(4, text.count("!"))
        long_form_slowdown = -2 if len(text) >= 200 else 0

        rate = base_rate + random.randint(-rate_span, rate_span) + long_form_slowdown + exclaim_energy
        pitch = base_pitch + random.randint(-pitch_span, pitch_span) + question_lift + exclaim_energy
        volume = base_volume + random.randint(-volume_span, volume_span) + (1 if exclaim_energy else 0)

        rate = self._clamp(rate, -40, 40)
        pitch = self._clamp(pitch, -80, 80)
        volume = self._clamp(volume, -25, 25)

        return (
            self._format_percent(rate),
            self._format_hz(pitch),
            self._format_percent(volume),
        )

    def _build_communicate(self, text: str) -> Any:
        import edge_tts

        (rate, pitch, volume) = self._prosody_for_text(text)

        kwargs: dict[str, Any] = {
            "text": text,
            "voice": self.config.edge_tts_voice,
            "rate": rate,
            "pitch": pitch,
            "volume": volume,
        }

        output_format = str(self.config.edge_tts_output_format or "").strip()
        if output_format and self._edge_supports_output_format():
            kwargs["output_format"] = output_format

        try:
            return edge_tts.Communicate(**kwargs)
        except TypeError:
            kwargs.pop("output_format", None)
            return edge_tts.Communicate(**kwargs)

    def _edge_supports_output_format(self) -> bool:
        if self._supports_edge_output_format is not None:
            return self._supports_edge_output_format

        try:
            import edge_tts

            signature = inspect.signature(edge_tts.Communicate.__init__)
            self._supports_edge_output_format = "output_format" in signature.parameters
        except Exception:
            self._supports_edge_output_format = False

        if not self._supports_edge_output_format:
            configured_format = str(self.config.edge_tts_output_format or "").strip().lower()
            if configured_format.startswith("raw-") and not self._can_stream_transcoded():
                logger.warning(
                    "Installed edge-tts does not support explicit output_format and ffmpeg is unavailable; using buffered fallback mode."
                )

        return bool(self._supports_edge_output_format)

    def _resolve_ffmpeg_binary(self) -> str | None:
        cached = getattr(self, "_ffmpeg_binary", None)
        if cached is not None:
            return cached
        resolved = shutil.which("ffmpeg")
        self._ffmpeg_binary = resolved
        return resolved

    def _can_stream_transcoded(self) -> bool:
        cached = getattr(self, "_supports_transcoded_stream", None)
        if cached is not None:
            return bool(cached)
        supported = self._resolve_ffmpeg_binary() is not None
        self._supports_transcoded_stream = supported
        return supported

    def _stream_target_sample_rate(self) -> int:
        output_format = str(self.config.edge_tts_output_format or "").strip().lower()
        match = re.match(r"^(?:raw|audio)-(\d+)khz", output_format)
        if match:
            rate_khz = int(match.group(1))
            if rate_khz > 0:
                return rate_khz * 1000
        return 24000

    def _raw_pcm_sample_rate(self) -> int | None:
        if not self._edge_supports_output_format():
            return None

        output_format = str(self.config.edge_tts_output_format or "").strip().lower()
        match = re.match(r"^raw-(\d+)khz-16bit-mono-pcm$", output_format)
        if not match:
            return None

        rate_khz = int(match.group(1))
        if rate_khz <= 0:
            return None
        return rate_khz * 1000

    @staticmethod
    def _looks_like_compressed_audio(chunk: bytes) -> bool:
        if not chunk:
            return False

        lead = bytes(chunk[:4])
        if lead.startswith(b"RIFF") or lead.startswith(b"ID3"):
            return True

        if len(chunk) >= 2 and chunk[0] == 0xFF and (chunk[1] & 0xE0) == 0xE0:
            return True

        return False

    @staticmethod
    def _align_pcm16_chunk(chunk: bytes) -> tuple[bytes, bytes]:
        """Split a PCM16 payload into aligned audio bytes and a 1-byte tail (if any)."""
        if not chunk:
            return (b"", b"")
        aligned_len = len(chunk) - (len(chunk) % 2)
        if aligned_len <= 0:
            return (b"", bytes(chunk))
        return (bytes(chunk[:aligned_len]), bytes(chunk[aligned_len:]))

    @staticmethod
    def _safe_stream_write(stream: Any, pcm_chunk: bytes) -> None:
        if not pcm_chunk:
            return
        try:
            stream.write(pcm_chunk, exception_on_underflow=False)
        except TypeError:
            stream.write(pcm_chunk)

    def _preferred_edge_stream_format(self) -> str:
        # Installed edge-tts 7.2.x does not expose configurable output formats, so
        # keep the persistent websocket session on the proven MP3 stream shape and
        # decode it to PCM locally with ffmpeg.
        return "audio-24khz-48kbitrate-mono-mp3"

    async def _close_edge_stream_session_async(self) -> None:
        websocket = self._edge_websocket
        session = self._edge_session
        self._edge_websocket = None
        self._edge_session = None
        self._edge_session_format = None

        if websocket is not None:
            try:
                response = getattr(websocket, "_response", None)
                connection = getattr(response, "connection", None)
                transport = getattr(connection, "transport", None)
                if transport is not None:
                    transport.abort()
            except Exception:
                pass
            try:
                await websocket.close()
            except Exception:
                pass

        if session is not None:
            try:
                await session.close()
            except Exception:
                pass

    async def _ensure_edge_stream_session_async(self, *, output_format: str) -> None:
        if self._edge_websocket is not None and self._edge_session is not None and self._edge_session_format == output_format:
            if not getattr(self._edge_websocket, "closed", False):
                return

        await self._close_edge_stream_session_async()

        import ssl

        import aiohttp
        import certifi
        from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
        from edge_tts.drm import DRM

        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=None,
            sock_connect=10,
            sock_read=60,
        )
        session = aiohttp.ClientSession(trust_env=True, timeout=timeout)

        try:
            websocket = await session.ws_connect(
                f"{WSS_URL}&ConnectionId={self._edge_connect_id()}"
                f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
                f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
                compress=15,
                headers=DRM.headers_with_muid(WSS_HEADERS),
                ssl=ssl_ctx,
            )
            await websocket.send_str(
                f"X-Timestamp:{self._edge_date_to_string()}\r\n"
                "Content-Type:application/json; charset=utf-8\r\n"
                "Path:speech.config\r\n\r\n"
                '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"'
                '},'
                f'"outputFormat":"{output_format}"'
                "}}}}\r\n"
            )
        except Exception:
            try:
                await session.close()
            except Exception:
                pass
            raise

        self._edge_session = session
        self._edge_websocket = websocket
        self._edge_session_format = output_format

    @staticmethod
    def _edge_connect_id() -> str:
        from edge_tts.communicate import connect_id

        return connect_id()

    @staticmethod
    def _edge_date_to_string() -> str:
        from edge_tts.communicate import date_to_string

        return date_to_string()

    async def _iter_edge_audio_chunks_async(self, text: str, turn_id: int) -> Any:
        from xml.sax.saxutils import escape

        import aiohttp
        from edge_tts.communicate import (
            get_headers_and_data,
            mkssml,
            remove_incompatible_characters,
            split_text_by_byte_length,
            ssml_headers_plus_data,
        )
        from edge_tts.data_classes import TTSConfig

        output_format = self._preferred_edge_stream_format()
        await self._ensure_edge_stream_session_async(output_format=output_format)

        rate, pitch, volume = self._prosody_for_text(text)
        tts_config = TTSConfig(
            self.config.edge_tts_voice,
            rate,
            volume,
            pitch,
            "SentenceBoundary",
        )

        escaped_text = escape(remove_incompatible_characters(text))
        websocket = self._edge_websocket
        if websocket is None:
            raise RuntimeError("edge_stream_session_missing")

        for part in split_text_by_byte_length(escaped_text, 4096):
            if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                await self._close_edge_stream_session_async()
                return

            await websocket.send_str(
                ssml_headers_plus_data(
                    self._edge_connect_id(),
                    self._edge_date_to_string(),
                    mkssml(tts_config, part),
                )
            )

            audio_received = False
            while True:
                received = await websocket.receive()

                if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                    await self._close_edge_stream_session_async()
                    return

                if received.type == aiohttp.WSMsgType.TEXT:
                    encoded_data = received.data.encode("utf-8")
                    header_end = encoded_data.find(b"\r\n\r\n")
                    if header_end < 0:
                        continue

                    parameters, _ = get_headers_and_data(encoded_data, header_end)
                    path = parameters.get(b"Path", None)
                    if path == b"turn.end":
                        if not audio_received:
                            raise RuntimeError("edge_stream_no_audio")
                        break
                    if path in {b"turn.start", b"response", b"audio.metadata"}:
                        continue
                    raise RuntimeError(f"edge_stream_unexpected_text_path:{path!r}")

                if received.type == aiohttp.WSMsgType.BINARY:
                    if len(received.data) < 2:
                        raise RuntimeError("edge_stream_binary_header_missing")

                    header_length = int.from_bytes(received.data[:2], "big")
                    parameters, data = get_headers_and_data(received.data, header_length)
                    if parameters.get(b"Path") != b"audio":
                        continue
                    if not data:
                        continue
                    audio_received = True
                    yield bytes(data)
                    continue

                raise RuntimeError(f"edge_stream_closed:{received.type}")

    def _enqueue_pcm_chunk(self, turn_id: int, pcm_chunk: bytes) -> bool:
        if not pcm_chunk:
            return False

        payload = bytes(pcm_chunk)
        while not self._stop_worker.is_set():
            if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                return False
            try:
                self._audio_queue.put((turn_id, payload, False), timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def _mark_pcm_turn_complete(self, turn_id: int) -> None:
        if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
            return
        while not self._stop_worker.is_set():
            try:
                self._audio_queue.put((turn_id, None, True), timeout=0.05)
                return
            except queue.Full:
                if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                    return

    def _prepare_pcm_turn_event(self, turn_id: int) -> threading.Event:
        event = threading.Event()
        with self._turn_lock:
            if turn_id != self._turn_id:
                event.set()
                return event
            self._pcm_turn_events[turn_id] = event
        return event

    def _signal_pcm_turn_drained(self, turn_id: int) -> None:
        event: threading.Event | None = None
        with self._turn_lock:
            event = self._pcm_turn_events.pop(turn_id, None)
        if event is not None:
            event.set()

    def _wait_for_pcm_turn_drain(self, turn_id: int, event: threading.Event) -> None:
        while not event.wait(timeout=0.05):
            if self._stop_worker.is_set():
                return
            if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                return

    def _playback_worker(self) -> None:
        import pyaudio

        sample_rate = int(self._stream_target_sample_rate())
        write_size = max(1024, int(self.config.tts_playout_chunk_size))
        if write_size % 2:
            write_size += 1
        prebuffer_target = max(write_size * 2, int(sample_rate * 2 * 0.08))

        audio_interface = pyaudio.PyAudio()
        stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            output=True,
            frames_per_buffer=max(256, int(self.config.tts_frames_per_buffer)),
        )

        with self._tts_lock:
            self._playback_audio_interface = audio_interface
            self._playback_stream = stream

        pending = bytearray()
        active_turn: int | None = None
        turn_finished = False
        speaking = False
        primed = False

        try:
            while not self._stop_worker.is_set():
                if self._playback_stop.is_set():
                    pending.clear()
                    active_turn = None
                    turn_finished = False
                    primed = False
                    if speaking:
                        speaking = False
                        with self._tts_lock:
                            self._is_speaking = False
                        self._handle_speaking_stop()
                    time.sleep(0.01)
                    continue

                try:
                    turn_id, pcm_chunk, is_end = self._audio_queue.get(timeout=0.05)
                except queue.Empty:
                    continue

                if active_turn is None or turn_id != active_turn:
                    pending.clear()
                    turn_finished = False
                    primed = False
                    if speaking:
                        speaking = False
                        with self._tts_lock:
                            self._is_speaking = False
                        self._handle_speaking_stop()
                    active_turn = turn_id

                if is_end:
                    turn_finished = True
                elif pcm_chunk:
                    pending.extend(pcm_chunk)

                if not primed and len(pending) < prebuffer_target and not turn_finished:
                    continue

                primed = True
                while len(pending) >= write_size:
                    if self._playback_stop.is_set() or active_turn is None or not self._is_active_turn(active_turn):
                        pending.clear()
                        break
                    if not speaking:
                        speaking = True
                        with self._tts_lock:
                            self._is_speaking = True
                        self._handle_speaking_start()
                    self._safe_stream_write(stream, bytes(pending[:write_size]))
                    del pending[:write_size]

                if turn_finished:
                    completed_turn = active_turn
                    if pending and active_turn is not None and self._is_active_turn(active_turn) and not self._playback_stop.is_set():
                        if not speaking:
                            speaking = True
                            with self._tts_lock:
                                self._is_speaking = True
                            self._handle_speaking_start()
                        aligned_len = len(pending) - (len(pending) % 2)
                        if aligned_len > 0:
                            self._safe_stream_write(stream, bytes(pending[:aligned_len]))
                    pending.clear()
                    active_turn = None
                    turn_finished = False
                    primed = False
                    if speaking:
                        speaking = False
                        with self._tts_lock:
                            self._is_speaking = False
                        self._handle_speaking_stop()
                    if completed_turn is not None:
                        self._signal_pcm_turn_drained(completed_turn)
        finally:
            self._release_persistent_playback()

    async def _stream_transcoded_persistent_async(self, segments: list[str], turn_id: int, sample_rate: int) -> None:
        stream_segments = [str(segment or "").strip() for segment in segments if str(segment or "").strip()]
        if not stream_segments:
            return

        playback_done = self._prepare_pcm_turn_event(turn_id)

        ffmpeg_binary = self._resolve_ffmpeg_binary()
        if not ffmpeg_binary:
            self._signal_pcm_turn_drained(turn_id)
            raise RuntimeError("ffmpeg_not_available")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-probesize",
                "32",
                "-analyzeduration",
                "0",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                str(int(sample_rate)),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            creationflags=creationflags,
        )

        if process.stdin is None or process.stdout is None:
            try:
                process.kill()
            except Exception:
                pass
            self._signal_pcm_turn_drained(turn_id)
            raise RuntimeError("ffmpeg_pipe_unavailable")

        abort_decode = threading.Event()
        decoder_finished = threading.Event()
        decode_errors: list[Exception] = []

        def _pcm_reader() -> None:
            carry = b""
            read_size = max(1024, write_size)
            try:
                while True:
                    if abort_decode.is_set():
                        break

                    pcm_chunk = process.stdout.read(read_size)
                    if not pcm_chunk:
                        break

                    chunk_bytes = bytes(pcm_chunk)
                    if carry:
                        chunk_bytes = carry + chunk_bytes
                        carry = b""

                    aligned, carry = self._align_pcm16_chunk(chunk_bytes)
                    if aligned and not self._enqueue_pcm_chunk(turn_id, aligned):
                        abort_decode.set()
                        break

                if carry:
                    aligned, carry = self._align_pcm16_chunk(carry)
                    if aligned and not self._enqueue_pcm_chunk(turn_id, aligned):
                        abort_decode.set()

                if not abort_decode.is_set() and not self._playback_stop.is_set() and self._is_active_turn(turn_id):
                    self._mark_pcm_turn_complete(turn_id)
            except Exception as exc:
                decode_errors.append(exc)
            finally:
                decoder_finished.set()

        write_size = max(1024, int(self.config.tts_playout_chunk_size))
        if write_size % 2:
            write_size += 1

        reader = threading.Thread(
            target=_pcm_reader,
            name="jarvis-edge-tts-pcm-reader",
            daemon=True,
        )
        reader.start()

        wrote_first_input_chunk = False
        interrupted = False
        try:
            for segment in stream_segments:
                async for audio_chunk in self._iter_edge_audio_chunks_async(segment, turn_id):
                    if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                        interrupted = True
                        break

                    try:
                        process.stdin.write(audio_chunk)
                        if not wrote_first_input_chunk:
                            process.stdin.flush()
                            wrote_first_input_chunk = True
                    except (BrokenPipeError, OSError) as exc:
                        raise RuntimeError("ffmpeg_decode_pipe_broken") from exc

                if interrupted:
                    break
        except Exception:
            abort_decode.set()
            await self._close_edge_stream_session_async()
            raise
        finally:
            try:
                process.stdin.close()
            except Exception:
                pass

            normal_completion = not interrupted and not self._playback_stop.is_set() and self._is_active_turn(turn_id)

            if normal_completion:
                reader.join()
            else:
                abort_decode.set()
                if process.poll() is None:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                reader.join(timeout=1.0)

            if process.poll() is None:
                try:
                    process.wait(timeout=1.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

            if decode_errors:
                self._signal_pcm_turn_drained(turn_id)
                raise decode_errors[0]

            if normal_completion and decoder_finished.is_set():
                self._wait_for_pcm_turn_drain(turn_id, playback_done)
            else:
                self._signal_pcm_turn_drained(turn_id)

    def _stream_transcoded_persistent(self, segments: list[str], turn_id: int, sample_rate: int, loop: asyncio.AbstractEventLoop) -> None:
        loop.run_until_complete(self._stream_transcoded_persistent_async(segments, turn_id, sample_rate))

    async def _stream_raw_async(self, text: str, turn_id: int, sample_rate: int) -> None:
        import pyaudio

        communicator = self._build_communicate(text)
        audio_interface = pyaudio.PyAudio()
        stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=int(sample_rate),
            output=True,
            frames_per_buffer=max(256, int(self.config.tts_frames_per_buffer)),
        )

        with self._tts_lock:
            self._audio_interface = audio_interface
            self._stream = stream
            self._is_speaking = True

        self._handle_speaking_start()
        first_audio_chunk = True
        carry = b""
        try:
            async for event in communicator.stream():
                if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                    break

                if not isinstance(event, dict) or event.get("type") != "audio":
                    continue

                chunk = event.get("data", b"")
                if chunk:
                    if first_audio_chunk:
                        first_audio_chunk = False
                        if self._looks_like_compressed_audio(bytes(chunk)):
                            raise RuntimeError("raw_pcm_unavailable")
                    raw_bytes = bytes(chunk)
                    if carry:
                        raw_bytes = carry + raw_bytes
                        carry = b""

                    aligned, carry = self._align_pcm16_chunk(raw_bytes)
                    if aligned:
                        self._safe_stream_write(stream, aligned)
        finally:
            self._release_active_audio()
            self._handle_speaking_stop()

    def _stream_raw(self, text: str, turn_id: int, sample_rate: int) -> None:
        try:
            asyncio.run(self._stream_raw_async(text, turn_id, sample_rate))
        except RuntimeError as exc:
            if "asyncio.run() cannot be called from a running event loop" not in str(exc):
                raise
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._stream_raw_async(text, turn_id, sample_rate))
            finally:
                loop.close()

    async def _stream_transcoded_async(self, text: str, turn_id: int, sample_rate: int) -> None:
        import pyaudio

        ffmpeg_binary = self._resolve_ffmpeg_binary()
        if not ffmpeg_binary:
            raise RuntimeError("ffmpeg_not_available")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-probesize",
                "32",
                "-analyzeduration",
                "0",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                str(int(sample_rate)),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            creationflags=creationflags,
        )

        if process.stdin is None or process.stdout is None:
            try:
                process.kill()
            except Exception:
                pass
            raise RuntimeError("ffmpeg_pipe_unavailable")

        communicator = self._build_communicate(text)
        audio_interface = pyaudio.PyAudio()
        stream = audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=int(sample_rate),
            output=True,
            frames_per_buffer=max(256, int(self.config.tts_frames_per_buffer)),
        )

        with self._tts_lock:
            self._audio_interface = audio_interface
            self._stream = stream
            self._is_speaking = True

        self._handle_speaking_start()
        abort_decode = threading.Event()
        decode_errors: list[Exception] = []

        def _pcm_reader() -> None:
            try:
                # Keep writes frame-aligned and lightly buffered to avoid crackle/under-runs.
                write_size = max(512, int(self.config.tts_playout_chunk_size))
                if write_size % 2:
                    write_size += 1

                read_size = max(1024, write_size)
                prebuffer_target = max(write_size, min(write_size * 2, int(sample_rate * 2 * 0.06)))

                pending = bytearray()
                carry = b""
                primed = False

                while True:
                    if abort_decode.is_set():
                        break

                    pcm_chunk = process.stdout.read(read_size)
                    if not pcm_chunk:
                        break

                    chunk_bytes = bytes(pcm_chunk)
                    if carry:
                        chunk_bytes = carry + chunk_bytes
                        carry = b""

                    aligned, carry = self._align_pcm16_chunk(chunk_bytes)
                    if not aligned:
                        continue

                    pending.extend(aligned)

                    if not primed and len(pending) < prebuffer_target:
                        continue

                    primed = True
                    while len(pending) >= write_size:
                        self._safe_stream_write(stream, bytes(pending[:write_size]))
                        del pending[:write_size]

                if carry:
                    aligned, carry = self._align_pcm16_chunk(carry)
                    if aligned:
                        pending.extend(aligned)

                if pending and not abort_decode.is_set():
                    aligned_len = len(pending) - (len(pending) % 2)
                    if aligned_len > 0:
                        self._safe_stream_write(stream, bytes(pending[:aligned_len]))
            except Exception as exc:
                decode_errors.append(exc)

        reader = threading.Thread(
            target=_pcm_reader,
            name="jarvis-edge-tts-transcode-reader",
            daemon=True,
        )
        reader.start()

        wrote_first_input_chunk = False
        interrupted = False
        try:
            async for event in communicator.stream():
                if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                    interrupted = True
                    break

                if not isinstance(event, dict) or event.get("type") != "audio":
                    continue

                chunk = event.get("data", b"")
                if not chunk:
                    continue

                try:
                    process.stdin.write(chunk)
                    if not wrote_first_input_chunk:
                        process.stdin.flush()
                        wrote_first_input_chunk = True
                except (BrokenPipeError, OSError) as exc:
                    raise RuntimeError("ffmpeg_decode_pipe_broken") from exc

            try:
                process.stdin.close()
            except Exception:
                pass

            if interrupted:
                abort_decode.set()
                if process.poll() is None:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                reader.join(timeout=1.0)
            else:
                reader.join()
            if decode_errors:
                raise decode_errors[0]
        except Exception:
            abort_decode.set()
            raise
        finally:
            abort_decode.set()

            try:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            except Exception:
                pass

            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=0.5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

            self._release_active_audio()
            self._handle_speaking_stop()

    def _stream_transcoded(self, text: str, turn_id: int, sample_rate: int) -> None:
        try:
            asyncio.run(self._stream_transcoded_async(text, turn_id, sample_rate))
        except RuntimeError as exc:
            if "asyncio.run() cannot be called from a running event loop" not in str(exc):
                raise
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._stream_transcoded_async(text, turn_id, sample_rate))
            finally:
                loop.close()

    async def _synthesize_async(self, text: str) -> bytes:
        communicator = self._build_communicate(text)
        audio_chunks = bytearray()

        async for event in communicator.stream():
            if isinstance(event, dict) and event.get("type") == "audio":
                chunk = event.get("data", b"")
                if chunk:
                    audio_chunks.extend(chunk)

        return bytes(audio_chunks)

    def _synthesize(self, text: str) -> bytes:
        try:
            return asyncio.run(self._synthesize_async(text))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._synthesize_async(text))
            finally:
                loop.close()

    def _play_wav_bytes(self, audio_bytes: bytes, turn_id: int) -> None:
        import pyaudio

        was_speaking = False
        wav_reader: wave.Wave_read | None = None

        try:
            wav_reader = wave.open(io.BytesIO(audio_bytes), "rb")
            audio_interface = pyaudio.PyAudio()
            stream = audio_interface.open(
                format=audio_interface.get_format_from_width(wav_reader.getsampwidth()),
                channels=wav_reader.getnchannels(),
                rate=wav_reader.getframerate(),
                output=True,
                frames_per_buffer=max(256, int(self.config.tts_frames_per_buffer)),
            )

            with self._tts_lock:
                self._audio_interface = audio_interface
                self._stream = stream
                self._is_speaking = True
                was_speaking = True

            self._handle_speaking_start()

            bytes_per_frame = max(1, wav_reader.getsampwidth() * wav_reader.getnchannels())
            frames_per_chunk = max(256, int(self.config.tts_playout_chunk_size) // bytes_per_frame)

            while not self._playback_stop.is_set() and self._is_active_turn(turn_id):
                pcm_chunk = wav_reader.readframes(frames_per_chunk)
                if not pcm_chunk:
                    break
                try:
                    self._safe_stream_write(stream, pcm_chunk)
                except Exception:
                    break
        finally:
            if wav_reader is not None:
                try:
                    wav_reader.close()
                except Exception:
                    pass
            self._release_active_audio()
            if was_speaking:
                self._handle_speaking_stop()

    def _play_mci_fallback(self, audio_bytes: bytes, turn_id: int) -> None:
        if os.name != "nt":
            raise RuntimeError("Edge TTS produced non-WAV audio and no fallback is available on this platform")

        import ctypes

        alias = f"jarvisedge{int(time.time() * 1000)}"
        temp_path = ""
        was_speaking = False
        send_command = ctypes.windll.winmm.mciSendStringW

        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name

            open_rc = send_command(f'open "{temp_path}" type mpegvideo alias {alias}', None, 0, None)
            if open_rc != 0:
                raise RuntimeError(f"MCI open failed with code {open_rc}")

            with self._tts_lock:
                self._is_speaking = True
                was_speaking = True

            self._handle_speaking_start()

            play_rc = send_command(f"play {alias}", None, 0, None)
            if play_rc != 0:
                raise RuntimeError(f"MCI play failed with code {play_rc}")

            status = ctypes.create_unicode_buffer(64)
            while not self._playback_stop.is_set() and self._is_active_turn(turn_id):
                status.value = ""
                send_command(f"status {alias} mode", status, len(status), None)
                mode = status.value.strip().lower()
                if mode in {"", "stopped", "not ready"}:
                    break
                time.sleep(0.02)

            if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                send_command(f"stop {alias}", None, 0, None)
        finally:
            try:
                send_command(f"close {alias}", None, 0, None)
            except Exception:
                pass
            with self._tts_lock:
                self._is_speaking = False
            if was_speaking:
                self._handle_speaking_stop()
            if temp_path and os.path.isfile(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _play_audio(self, audio_bytes: bytes, turn_id: int) -> None:
        try:
            self._play_wav_bytes(audio_bytes, turn_id)
        except wave.Error:
            self._play_mci_fallback(audio_bytes, turn_id)

    def _prefetch_segment_audio(self, segment: str, result_holder: dict[str, Any]) -> None:
        try:
            result_holder["audio"] = self._synthesize(segment)
        except Exception as exc:
            result_holder["error"] = exc

    def _play_buffered_segments(self, segments: list[str], turn_id: int) -> None:
        if not segments:
            return

        current_audio = self._synthesize(segments[0])
        if not current_audio:
            return

        for idx in range(len(segments)):
            if self._playback_stop.is_set() or not self._is_active_turn(turn_id):
                return

            prefetch_thread: threading.Thread | None = None
            prefetched: dict[str, Any] = {}
            if idx + 1 < len(segments):
                prefetch_thread = threading.Thread(
                    target=self._prefetch_segment_audio,
                    args=(segments[idx + 1], prefetched),
                    name="jarvis-edge-tts-prefetch",
                    daemon=True,
                )
                prefetch_thread.start()

            self._play_audio(current_audio, turn_id)

            if prefetch_thread is None:
                return

            prefetch_thread.join()
            if "error" in prefetched:
                raise prefetched["error"]

            next_audio = prefetched.get("audio", b"")
            if not isinstance(next_audio, (bytes, bytearray)) or not next_audio:
                return
            current_audio = bytes(next_audio)

    def _decrement_pending_if_active(self, turn_id: int) -> None:
        with self._turn_lock:
            if turn_id == self._turn_id and self._pending_chunks > 0:
                self._pending_chunks -= 1

    def _tts_worker(self) -> None:
        worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(worker_loop)
        self._edge_loop = worker_loop

        try:
            if self._can_stream_transcoded():
                try:
                    worker_loop.run_until_complete(
                        self._ensure_edge_stream_session_async(
                            output_format=self._preferred_edge_stream_format()
                        )
                    )
                except Exception as exc:
                    logger.debug("Persistent Edge session warmup skipped: %s", exc)

            while not self._stop_worker.is_set():
                try:
                    turn_id, segments = self._speech_queue.get(timeout=float(self.config.tts_queue_timeout))
                except queue.Empty:
                    continue

                if not self._is_active_turn(turn_id):
                    self._decrement_pending_if_active(turn_id)
                    continue

                if not segments:
                    self._decrement_pending_if_active(turn_id)
                    continue

                try:
                    self._playback_stop.clear()

                    sample_rate = self._raw_pcm_sample_rate()
                    if sample_rate is not None and len(segments) == 1:
                        try:
                            self._stream_raw(segments[0], turn_id, sample_rate)
                            continue
                        except Exception as exc:
                            logger.warning("Raw Edge TTS stream unavailable, falling back to buffered playback: %s", exc)

                    if segments and self._can_stream_transcoded():
                        try:
                            self._stream_transcoded_persistent(
                                segments,
                                turn_id,
                                self._stream_target_sample_rate(),
                                worker_loop,
                            )
                            continue
                        except Exception as exc:
                            worker_loop.run_until_complete(self._close_edge_stream_session_async())
                            logger.warning("Transcoded Edge TTS stream unavailable, falling back to buffered playback: %s", exc)

                    self._play_buffered_segments(segments, turn_id)
                except Exception as exc:
                    logger.warning("Edge TTS playback failed: %s", exc)
                finally:
                    self._decrement_pending_if_active(turn_id)
        finally:
            self._edge_loop = None
            try:
                worker_loop.run_until_complete(self._close_edge_stream_session_async())
            except Exception:
                pass
            worker_loop.close()

    def close(self) -> None:
        self.interrupt()
        self._stop_worker.set()
        if self._speaker_thread.is_alive():
            self._speaker_thread.join(timeout=1.0)
        if self._playback_thread.is_alive():
            self._playback_thread.join(timeout=1.0)
