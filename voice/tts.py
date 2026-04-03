from __future__ import annotations

import importlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any, Callable

import requests

from core.settings import AppConfig

logger = logging.getLogger(__name__)


class RealtimePiperTTS:
    """RealtimeTTS + Piper backend with turn-based interruption safety."""

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

        self._speech_queue: queue.Queue[tuple[int, str]] = queue.Queue()
        self._stop_worker = threading.Event()
        self._turn_lock = threading.Lock()
        self._tts_lock = threading.Lock()

        self._turn_id = 0
        self._pending_chunks = 0
        self._stream_started = False

        self.engine, self.stream = self._init_tts()

        self._speaker_thread = threading.Thread(
            target=self._tts_worker,
            name="jarvis-piper-tts-worker",
            daemon=True,
        )
        self._speaker_thread.start()

    def _import_tts_classes(self) -> tuple[Any, Any, Any]:
        module_names = ("realtime_tts", "RealtimeTTS")

        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
                piper_engine = getattr(module, "PiperEngine")
                text_to_audio_stream = getattr(module, "TextToAudioStream")

                piper_voice = getattr(module, "PiperVoice", None)
                if piper_voice is None:
                    try:
                        voice_module = importlib.import_module(f"{module_name}.engines.piper_engine")
                    except Exception:
                        voice_module = importlib.import_module("RealtimeTTS.engines.piper_engine")
                    piper_voice = getattr(voice_module, "PiperVoice")

                return piper_engine, text_to_audio_stream, piper_voice
            except Exception:
                continue

        raise ImportError("RealtimeTTS package with Piper support is not available")

    def _download_file(self, url: str, target_path: str) -> None:
        headers = {"Authorization": f"Bearer {self.config.hf_token}"} if self.config.hf_token else {}
        response = requests.get(url, headers=headers, stream=True, timeout=120)
        response.raise_for_status()

        with open(target_path, "wb") as file_obj:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    file_obj.write(chunk)

    def _ensure_piper_voice_files(self) -> tuple[str, str]:
        model_path = os.path.abspath(os.path.expanduser(self.config.piper_model_path))
        config_path = os.path.abspath(os.path.expanduser(self.config.piper_config_path))

        os.makedirs(os.path.dirname(model_path), exist_ok=True)

        if not os.path.exists(model_path):
            self._download_file(self.config.piper_model_url, model_path)

        if not os.path.exists(config_path):
            self._download_file(self.config.piper_config_url, config_path)

        return model_path, config_path

    @staticmethod
    def _read_piper_sample_rate(config_path: str) -> int:
        try:
            with open(config_path, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
            return int(config.get("audio", {}).get("sample_rate", 16000))
        except Exception:
            return 16000

    def _resolve_piper_path(self) -> str:
        candidates = []
        if self.config.piper_path:
            candidates.append(os.path.abspath(os.path.expanduser(self.config.piper_path)))

        candidates.extend(
            [
                os.path.abspath(os.path.join("venv", "Scripts", "piper.exe")),
                os.path.abspath(os.path.join(".venv", "Scripts", "piper.exe")),
            ]
        )

        found_on_path = shutil.which("piper.exe") or shutil.which("piper")
        if found_on_path:
            candidates.append(found_on_path)

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate

        raise RuntimeError(
            "Piper executable not found. Set PIPER_PATH in .env or install piper.exe in your venv Scripts folder."
        )

    def _init_tts(self) -> tuple[Any, Any]:
        PiperEngine, TextToAudioStream, PiperVoice = self._import_tts_classes()

        model_path, config_path = self._ensure_piper_voice_files()
        piper_exec = self._resolve_piper_path()
        sample_rate = self._read_piper_sample_rate(config_path)

        class AdaptivePiperEngine(PiperEngine):
            def __init__(self, *, output_rate: int, **kwargs: Any) -> None:
                self.output_rate = int(output_rate)
                super().__init__(**kwargs)

            def get_stream_info(self) -> tuple[Any, int, int]:
                import pyaudio

                return pyaudio.paInt16, 1, self.output_rate

            def synthesize(self, text: str) -> bool:
                if not self.voice:
                    return False

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav_file:
                    output_wav_path = tmp_wav_file.name

                cmd_list = [
                    self.piper_path,
                    "-m",
                    self.voice.model_file,
                    "-f",
                    output_wav_path,
                ]

                if self.voice.config_file:
                    cmd_list.extend(["-c", self.voice.config_file])

                try:
                    subprocess.run(
                        cmd_list,
                        input=text.encode("utf-8"),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=True,
                        shell=False,
                    )

                    with wave.open(output_wav_path, "rb") as wav_file:
                        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                            return False

                        audio_data = wav_file.readframes(wav_file.getnframes())
                        rate = wav_file.getframerate()

                        if rate != self.output_rate:
                            import audioop

                            audio_data, _ = audioop.ratecv(
                                audio_data,
                                2,
                                1,
                                rate,
                                self.output_rate,
                                None,
                            )

                        self.queue.put(audio_data)

                    return True
                except Exception:
                    return False
                finally:
                    if os.path.isfile(output_wav_path):
                        os.remove(output_wav_path)

        voice = PiperVoice(model_file=model_path, config_file=config_path)
        engine = AdaptivePiperEngine(
            piper_path=piper_exec,
            voice=voice,
            output_rate=sample_rate,
            debug=False,
        )
        stream = TextToAudioStream(
            engine,
            language="en",
            level=40,
            frames_per_buffer=self.config.tts_frames_per_buffer,
            playout_chunk_size=self.config.tts_playout_chunk_size,
            on_audio_stream_start=self._handle_speaking_start,
            on_audio_stream_stop=self._handle_speaking_stop,
        )
        return engine, stream

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

    def interrupt(self) -> int:
        with self._turn_lock:
            self._turn_id += 1
            self._pending_chunks = 0
            active_turn = self._turn_id

        self._clear_speech_queue()
        with self._tts_lock:
            if self._stream_started and self.stream.is_playing():
                self.stream.stop()

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
        cleaned = re.sub(r"^\s*[-+]\s+", "", cleaned)
        cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned)
        cleaned = re.sub(r"\s*([,;:.!?])\s*", r"\1 ", cleaned)
        cleaned = re.sub(r"([,;:.!?]){2,}", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def enqueue_text(self, chunk: str, turn_id: int) -> bool:
        text = " ".join(str(chunk or "").strip().split())
        text = text.strip('"')
        text = self._prepare_for_tts(text)
        if not text:
            return False

        with self._turn_lock:
            if turn_id != self._turn_id:
                return False
            self._pending_chunks += 1

        self._speech_queue.put((turn_id, text))
        return True

    def wait_for_turn_completion(self, turn_id: int, timeout_s: float = 25.0) -> None:
        start = time.time()
        while True:
            with self._turn_lock:
                active_turn = self._turn_id
                pending_chunks = self._pending_chunks

            if turn_id != active_turn:
                return

            with self._tts_lock:
                is_playing = self._stream_started and self.stream.is_playing()

            if pending_chunks <= 0 and not is_playing:
                return

            if timeout_s > 0 and (time.time() - start) >= timeout_s:
                return

            time.sleep(0.02)

    def _is_active_turn(self, turn_id: int) -> bool:
        with self._turn_lock:
            return turn_id == self._turn_id

    def _tts_worker(self) -> None:
        while not self._stop_worker.is_set():
            try:
                turn_id, text = self._speech_queue.get(timeout=float(self.config.tts_queue_timeout))
            except queue.Empty:
                continue

            if not self._is_active_turn(turn_id):
                with self._turn_lock:
                    if self._pending_chunks > 0:
                        self._pending_chunks -= 1
                continue

            try:
                with self._tts_lock:
                    if not self._is_active_turn(turn_id):
                        continue

                    min_sentence_length = max(10, min(self.config.tts_min_sentence_length, 15))
                    min_first_fragment_length = max(8, min(self.config.tts_min_first_fragment_length, 11))
                    force_first_fragment_after_words = max(9, min(self.config.tts_force_first_fragment_after_words, 13))

                    self.stream.feed(text + " ")
                    if not self._is_active_turn(turn_id):
                        self.stream.stop()
                        continue

                    if not self.stream.is_playing():
                        self._stream_started = True
                        self.stream.play_async(
                            fast_sentence_fragment=True,
                            fast_sentence_fragment_allsentences=False,
                            buffer_threshold_seconds=0.04,
                            minimum_sentence_length=min_sentence_length,
                            minimum_first_fragment_length=min_first_fragment_length,
                            sentence_fragment_delimiters=".?!;:\n",
                            force_first_fragment_after_words=force_first_fragment_after_words,
                            language="en",
                        )
            except Exception as exc:
                logger.warning("Realtime Piper TTS playback failed: %s", exc)
            finally:
                with self._turn_lock:
                    if turn_id == self._turn_id and self._pending_chunks > 0:
                        self._pending_chunks -= 1

    def close(self) -> None:
        self.interrupt()
        self._stop_worker.set()
        if self._speaker_thread.is_alive():
            self._speaker_thread.join(timeout=1.0)
