# ==============================================================================
# File: voice/stt.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Speech-to-Text Engine — Voice Activity Detection & Recognition
#
#    - Speech recognition for real-time voice input processing.
#    - Microphone audio capture with configurable sample rate.
#    - Voice activity detection (VAD) for speech segment isolation.
#    - Speech-to-text conversion for the voice interface pipeline.
#    - Noise filtering for improved recognition accuracy.
#    - Continuous listening mode for hands-free interaction.
#    - Integrates with JarvisBridge for voice input delivery.
#    - Configurable recognition engine selection.
#    - Thread-safe design for concurrent audio processing.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations


class STTPlaceholder:
    """Future Speech-to-Text backend abstraction point.

    Browser-side Web Speech API currently provides live STT for GUI mode.
    """

    def transcribe(self, _audio_chunk: bytes) -> str:
        raise NotImplementedError("STT backend not wired in Python yet.")
