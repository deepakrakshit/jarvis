"""Document Intelligence System for JARVIS.

Production-grade document ingestion, parsing, and intelligence extraction
pipeline supporting PDF, DOCX, and image-based documents.
"""

from services.document.document_service import DocumentService

__all__ = ["DocumentService"]
