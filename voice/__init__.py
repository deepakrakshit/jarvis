# ==============================================================================
# File: voice/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Voice Engine Package Initializer
#
#    - Exports TTS and STT components for the JARVIS voice interface.
#    - RealtimePiperTTS: turn-based text-to-speech with Piper backend.
#    - STT module: speech-to-text for voice input processing.
#    - Voice pipeline: mic capture -> STT -> runtime -> TTS -> speaker.
#    - Turn management with monotonic IDs for interruption safety.
#    - Markdown stripping in the TTS preparation stage.
#    - Configurable voice model download from HuggingFace.
#    - Designed for real-time conversational voice interaction.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================
