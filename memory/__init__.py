# ==============================================================================
# File: memory/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Memory Persistence Package Initializer
#
#    - Exports the MemoryStore class for persistent user fact storage.
#    - JSON file-backed key/value store for cross-session persistence.
#    - Stores user_name, last_city, last_opened_app, and other facts.
#    - Thread-safe implementation with reentrant lock protection.
#    - Atomic file writes prevent corruption on unexpected shutdown.
#    - Also exports extract_user_name() for NLP-based name detection.
#    - Single-file module design for simplicity and reliability.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from .store import MemoryStore, extract_user_name

__all__ = ["MemoryStore", "extract_user_name"]
