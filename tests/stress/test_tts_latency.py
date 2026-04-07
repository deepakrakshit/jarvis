# ==============================================================================
# File: tests/stress/test_tts_latency.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Core module for test_tts_latency functionalities.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.runtime import JarvisRuntime
from voice.tts import EdgeNeuralTTS


class TtsLatencyStressTest(unittest.TestCase):
    def test_align_pcm16_chunk_separates_odd_tail_byte(self) -> None:
        aligned, tail = EdgeNeuralTTS._align_pcm16_chunk(b"\x01\x02\x03")

        self.assertEqual(aligned, b"\x01\x02")
        self.assertEqual(tail, b"\x03")

    def test_prefers_single_utterance_when_low_latency_streaming_is_available(self) -> None:
        tts = object.__new__(EdgeNeuralTTS)
        tts._raw_pcm_sample_rate = lambda: None  # type: ignore[attr-defined]
        tts._can_stream_transcoded = lambda: True  # type: ignore[attr-defined]

        self.assertTrue(EdgeNeuralTTS.prefers_single_utterance(tts))

    def test_enqueue_speech_chunks_splits_long_reply_for_faster_start(self) -> None:
        runtime = object.__new__(JarvisRuntime)
        runtime.config = SimpleNamespace(tts_chunk_chars=34, tts_min_first_fragment_length=14)

        calls: list[str] = []

        class _FakeTts:
            def enqueue_text(self, chunk: str, turn_id: int) -> bool:
                calls.append(chunk)
                return True

        runtime.tts = _FakeTts()

        text = (
            "This is a long reply that should start speaking quickly for the user "
            "while the remaining part is queued right after the first fragment "
            "to reduce time-to-first-audio."
        )
        queued = JarvisRuntime._enqueue_speech_chunks(runtime, text, 1)

        self.assertTrue(queued)
        self.assertEqual(len(calls), 2)
        self.assertLess(len(calls[0]), len(text))

    def test_enqueue_speech_chunks_keeps_short_reply_single(self) -> None:
        runtime = object.__new__(JarvisRuntime)
        runtime.config = SimpleNamespace(tts_chunk_chars=34, tts_min_first_fragment_length=14)

        calls: list[str] = []

        class _FakeTts:
            def enqueue_text(self, chunk: str, turn_id: int) -> bool:
                calls.append(chunk)
                return True

        runtime.tts = _FakeTts()

        text = "Short answer."
        queued = JarvisRuntime._enqueue_speech_chunks(runtime, text, 1)

        self.assertTrue(queued)
        self.assertEqual(calls, [text])

    def test_enqueue_speech_chunks_keeps_streaming_reply_single(self) -> None:
        runtime = object.__new__(JarvisRuntime)
        runtime.config = SimpleNamespace(tts_chunk_chars=34, tts_min_first_fragment_length=14)

        calls: list[str] = []

        class _FakeStreamingTts:
            def prefers_single_utterance(self) -> bool:
                return True

            def enqueue_text(self, chunk: str, turn_id: int) -> bool:
                calls.append(chunk)
                return True

        runtime.tts = _FakeStreamingTts()

        text = (
            "This is a long response that should remain one utterance when streaming is active "
            "to avoid audible breaks between separately synthesized fragments."
        )
        queued = JarvisRuntime._enqueue_speech_chunks(runtime, text, 1)

        self.assertTrue(queued)
        self.assertEqual(calls, [text])

    def test_split_for_buffered_mode_prefers_early_chunk_for_long_text(self) -> None:
        tts = object.__new__(EdgeNeuralTTS)
        tts._raw_pcm_sample_rate = lambda: None  # type: ignore[attr-defined]
        tts._can_stream_transcoded = lambda: False  # type: ignore[attr-defined]

        text = (
            "This is a long assistant response designed to verify low-latency startup in buffered mode. "
            "It should be split into an early first segment so users hear speech quickly, "
            "instead of waiting for a full long synthesis before playback starts."
        )
        parts = EdgeNeuralTTS._split_for_buffered_mode(tts, text)

        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0])
        self.assertTrue(parts[1])
        self.assertLess(len(parts[0]), len(text))

    def test_split_for_buffered_mode_keeps_single_chunk_for_short_text(self) -> None:
        tts = object.__new__(EdgeNeuralTTS)
        tts._raw_pcm_sample_rate = lambda: None  # type: ignore[attr-defined]
        tts._can_stream_transcoded = lambda: False  # type: ignore[attr-defined]

        text = "Short answer for quick playback."
        parts = EdgeNeuralTTS._split_for_buffered_mode(tts, text)

        self.assertEqual(parts, [text])

    def test_split_for_buffered_mode_uses_sentence_chunks_when_streaming_available(self) -> None:
        tts = object.__new__(EdgeNeuralTTS)
        tts._raw_pcm_sample_rate = lambda: None  # type: ignore[attr-defined]
        tts._can_stream_transcoded = lambda: True  # type: ignore[attr-defined]
        tts.config = SimpleNamespace(tts_chunk_chars=34)

        text = (
            "This is a long assistant response that would normally split in buffered mode, "
            "but should be emitted as sentence-level streaming chunks when low-latency decode is available. "
            "That lets playback begin earlier without reopening the Edge session between fragments."
        )
        parts = EdgeNeuralTTS._split_for_buffered_mode(tts, text)

        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(all(parts))


if __name__ == "__main__":
    unittest.main()
