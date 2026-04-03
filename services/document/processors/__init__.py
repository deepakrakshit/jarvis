# ==============================================================================
# File: services/document/processors/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Document Processor Package Initializer
#
#    - Exports document processing components for the intelligence pipeline.
#    - Chunker: splits text into retrieval-optimized segments.
#    - Cleaner: normalizes and sanitizes raw extracted content.
#    - Entities: named entity extraction and normalization.
#    - Fusion: multi-source content merging and deduplication.
#    - Retriever: semantic chunk retrieval for Q&A operations.
#    - Each processor is independently testable and composable.
#    - Designed for pipeline-stage modularity and extensibility.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from services.document.processors.cleaner import DocumentCleaner
from services.document.processors.chunker import SemanticChunker
from services.document.processors.fusion import FusionProcessor
from services.document.processors.entities import extract_key_entities, merge_entities, normalize_entities
from services.document.processors.retriever import SemanticRetriever

__all__ = [
    "DocumentCleaner",
    "SemanticChunker",
    "FusionProcessor",
    "extract_key_entities",
    "merge_entities",
    "normalize_entities",
    "SemanticRetriever",
]
