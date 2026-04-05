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
#    - Buffered fallback: synthesizes full payload and plays WAV/MP3 if raw mode
#      is not configured.
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
        self._stop_worker = threading.Event()
        self._playback_stop = threading.Event()
        self._turn_lock = threading.Lock()
        self._tts_lock = threading.Lock()

        self._turn_id = 0
        self._pending_chunks = 0
        self._is_speaking = False

        self._stream: Any | None = None
        self._audio_interface: Any | None = None
        self._supports_edge_output_format: bool | None = None

        self._speaker_thread = threading.Thread(
            target=self._tts_worker,
            name="jarvis-edge-tts-worker",
            daemon=True,
        )
        self._speaker_thread.start()

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

    def interrupt(self) -> int:
        with self._turn_lock:
            self._turn_id += 1
            self._pending_chunks = 0
            active_turn = self._turn_id

        self._playback_stop.set()
        self._clear_speech_queue()
        self._release_active_audio()
        return active_turn

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

        # Keep one utterance in raw-stream mode where startup is already low-latency.
        if self._raw_pcm_sample_rate() is not None:
            return [text]

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
        base_rate = self._parse_percent(self.config.edge_tts_rate, default=-4)
        base_pitch = self._parse_hz(self.config.edge_tts_pitch, default=6)
        base_volume = self._parse_percent(self.config.edge_tts_volume, default=8)

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
            if configured_format.startswith("raw-"):
                logger.warning(
                    "Installed edge-tts does not support explicit output_format; using buffered fallback mode."
                )

        return bool(self._supports_edge_output_format)

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
                    stream.write(chunk)
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
                    stream.write(pcm_chunk)
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

                self._play_buffered_segments(segments, turn_id)
            except Exception as exc:
                logger.warning("Edge TTS playback failed: %s", exc)
            finally:
                self._decrement_pending_if_active(turn_id)

    def close(self) -> None:
        self.interrupt()
        self._stop_worker.set()
        if self._speaker_thread.is_alive():
            self._speaker_thread.join(timeout=1.0)
