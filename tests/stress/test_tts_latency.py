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

from voice.tts import EdgeNeuralTTS


class TtsLatencyStressTest(unittest.TestCase):
    def test_split_for_buffered_mode_prefers_early_chunk_for_long_text(self) -> None:
        tts = object.__new__(EdgeNeuralTTS)
        tts._raw_pcm_sample_rate = lambda: None  # type: ignore[attr-defined]

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

        text = "Short answer for quick playback."
        parts = EdgeNeuralTTS._split_for_buffered_mode(tts, text)

        self.assertEqual(parts, [text])


if __name__ == "__main__":
    unittest.main()
