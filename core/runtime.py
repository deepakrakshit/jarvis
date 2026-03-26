from __future__ import annotations

import json
import threading
import time
from typing import Callable

import requests

from core.settings import AppConfig, RESET, SYSTEM_PROMPT, WHITE
from voice.tts import RealtimePiperTTS


class JarvisRuntime:
    EARLY_CHUNK_MIN_CHARS = 14
    EARLY_CHUNK_TARGET_CHARS = 28
    EARLY_CHUNK_MAX_CHARS = 32
    EARLY_CHUNK_MAX_WAIT_SECONDS = 0.45

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env(".env")
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._on_mode_change: Callable[[str], None] | None = None
        self._on_text_delta: Callable[[str], None] | None = None
        self._on_api_activity: Callable[[bool], None] | None = None
        self._request_lock = threading.Lock()
        self.tts = RealtimePiperTTS(
            self.config,
            on_speaking_start=self._handle_tts_start,
            on_speaking_stop=self._handle_tts_stop,
        )

    def set_event_callbacks(
        self,
        *,
        on_mode_change: Callable[[str], None] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_api_activity: Callable[[bool], None] | None = None,
    ) -> None:
        self._on_mode_change = on_mode_change
        self._on_text_delta = on_text_delta
        self._on_api_activity = on_api_activity

    def _emit_mode(self, mode: str) -> None:
        if self._on_mode_change:
            try:
                self._on_mode_change(mode)
            except Exception:
                pass

    def _emit_text_delta(self, delta: str) -> None:
        if self._on_text_delta:
            try:
                self._on_text_delta(delta)
            except Exception:
                pass

    def _emit_api_activity(self, active: bool) -> None:
        if self._on_api_activity:
            try:
                self._on_api_activity(active)
            except Exception:
                pass

    def _handle_tts_start(self) -> None:
        self._emit_mode("speaking")

    def _handle_tts_stop(self) -> None:
        self._emit_mode("listening")

    def _trim_history(self) -> None:
        if len(self.messages) > (self.config.max_context_messages + 1):
            self.messages = [self.messages[0]] + self.messages[-self.config.max_context_messages:]

    def _should_flush_speech_buffer(self, buffer: str) -> bool:
        stripped = buffer.strip()
        if not stripped:
            return False

        flush_chars = max(18, min(self.config.tts_chunk_chars, self.EARLY_CHUNK_MAX_CHARS))

        if stripped[-1] in ".?!":
            return True

        if len(stripped) >= flush_chars:
            return True

        return False

    def _next_speech_chunk(self, buffer: str, *, final: bool = False) -> tuple[str, str]:
        if not buffer:
            return "", ""

        if final:
            return buffer.strip(), ""

        if not self._should_flush_speech_buffer(buffer):
            return "", buffer

        boundaries = [". ", "? ", "! ", ", ", "; ", ": ", "\n", " "]
        cutoff = -1
        for marker in boundaries:
            idx = buffer.rfind(marker)
            if idx > cutoff:
                cutoff = idx + len(marker)

        if cutoff <= 0:
            cutoff = min(len(buffer), self.config.tts_chunk_chars)

        chunk = buffer[:cutoff].strip()
        rest = buffer[cutoff:]

        if len(chunk) < 8:
            return "", buffer

        return chunk, rest

    def _early_speech_chunk(self, buffer: str) -> tuple[str, str]:
        stripped = buffer.strip()
        if len(stripped) < self.EARLY_CHUNK_MIN_CHARS:
            return "", buffer

        target = max(self.EARLY_CHUNK_TARGET_CHARS, min(self.config.tts_chunk_chars, self.EARLY_CHUNK_MAX_CHARS))
        target = min(target, len(buffer))
        cutoff = target

        while cutoff > 0 and buffer[cutoff - 1] not in (" ", "\n", ",", ".", "?", "!", ";", ":"):
            cutoff -= 1

        if cutoff <= 0:
            cutoff = target

        chunk = buffer[:cutoff].strip()
        rest = buffer[cutoff:]
        if len(chunk) < self.EARLY_CHUNK_MIN_CHARS:
            return "", buffer

        return chunk, rest

    def ask_groq(
        self,
        text: str,
        *,
        persist_user: bool = True,
        stream_to_stdout: bool = True,
    ) -> str:
        with self._request_lock:
            return self._ask_groq_locked(
                text,
                persist_user=persist_user,
                stream_to_stdout=stream_to_stdout,
            )

    def _ask_groq_locked(
        self,
        text: str,
        *,
        persist_user: bool = True,
        stream_to_stdout: bool = True,
    ) -> str:
        if persist_user:
            self.messages.append({"role": "user", "content": text})
            self._trim_history()
            outbound_messages = self.messages
        else:
            outbound_messages = self.messages + [{"role": "user", "content": text}]

        turn_id = self.tts.interrupt()
        self._emit_mode("processing")
        self._emit_api_activity(True)

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.groq_model,
                "messages": outbound_messages,
                "temperature": 0.3,
                "stream": True,
            },
            stream=True,
            timeout=60,
        )
        response.raise_for_status()

        full_text = ""
        speak_buffer = ""
        first_voice_chunk = True
        queued_any_speech = False
        last_chunk_queued_at = time.perf_counter()

        if stream_to_stdout:
            print(f"{WHITE}JARVIS:{RESET} ", end="", flush=True)

        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                if line.startswith("data: "):
                    chunk = line[6:]

                    if chunk == "[DONE]":
                        break

                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0].get("delta", {}).get("content")

                        if delta:
                            if stream_to_stdout:
                                print(delta, end="", flush=True)
                            self._emit_text_delta(delta)
                            full_text += delta
                            speak_buffer += delta

                            while True:
                                chunk_to_speak, speak_buffer = self._next_speech_chunk(
                                    speak_buffer,
                                    final=False,
                                )

                                if not chunk_to_speak:
                                    break

                                if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                                    time.sleep(self.config.tts_first_chunk_delay)
                                first_voice_chunk = False
                                queued_any_speech = True
                                self.tts.enqueue_text(chunk_to_speak, turn_id)
                                last_chunk_queued_at = time.perf_counter()

                            if speak_buffer.strip() and (time.perf_counter() - last_chunk_queued_at) >= self.EARLY_CHUNK_MAX_WAIT_SECONDS:
                                early_chunk, speak_buffer = self._early_speech_chunk(speak_buffer)
                                if early_chunk:
                                    if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                                        time.sleep(self.config.tts_first_chunk_delay)
                                    first_voice_chunk = False
                                    queued_any_speech = True
                                    self.tts.enqueue_text(early_chunk, turn_id)
                                    last_chunk_queued_at = time.perf_counter()

                    except Exception:
                        continue
        finally:
            self._emit_api_activity(False)

        if speak_buffer.strip():
            if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                time.sleep(self.config.tts_first_chunk_delay)
            tail_chunk, _ = self._next_speech_chunk(speak_buffer, final=True)
            if tail_chunk:
                queued_any_speech = True
                self.tts.enqueue_text(tail_chunk, turn_id)

        if not full_text.strip():
            full_text = "I did not receive a valid response. Please try again."
            if stream_to_stdout:
                print(full_text, end="", flush=True)
            self.tts.enqueue_text(full_text, turn_id)
            queued_any_speech = True

        if stream_to_stdout:
            print()

        if not queued_any_speech:
            self._emit_mode("listening")

        full_text = full_text.strip().strip('"')

        if persist_user:
            self.messages.append({"role": "assistant", "content": full_text})
            self._trim_history()

        return full_text

    def greet(self) -> str:
        greeting_prompt = (
            "Deliver a concise system-ready greeting to the authorized user in one line."
        )
        return self.ask_groq(greeting_prompt, persist_user=False)

    def close(self) -> None:
        self.tts.close()
