# ==============================================================================
# File: services/document/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Document Intelligence Package Initializer
#
#    - Exports the DocumentService facade for the analysis pipeline.
#    - DocumentService: top-level orchestrator with multi-tier caching.
#    - DocumentPipeline: multi-stage extraction and reasoning engine.
#    - DocumentLLMClient: dual-model inference client (fast + deep).
#    - Supports PDF, DOCX, and image file format analysis.
#    - Integrates retrieval-augmented Q&A and cross-document comparison.
#    - Cache layer: L1 in-memory OrderedDict + L2 SQLite persistence.
#    - Designed for production-grade document intelligence extraction.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from services.document.document_service import DocumentService

__all__ = ["DocumentService"]
