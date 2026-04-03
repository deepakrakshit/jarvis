# ==============================================================================
# File: services/document/qa_engine.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Retrieval-Augmented Document Q&A Engine
#
#    - Question answering system over analyzed document content.
#    - Semantic chunk retrieval via SemanticRetriever with top-k selection.
#    - Evidence ranking based on relevance scoring to the question.
#    - LLM-powered answer generation with retrieved chunks as context.
#    - Citation tracking: maps answer claims to source chunks.
#    - Single-document Q&A: answer_single_document_question().
#    - Cross-document comparison: answer_multi_document_question() for
#      pricing, plans, risks, and key differences across multiple files.
#    - looks_like_compare_question(): detects comparative intent in queries.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import json
import re
from typing import Any

from services.document.llm_client import DocumentLLMClient
from services.document.processors.entities import extract_key_entities, merge_entities, normalize_entities
from services.document.processors.retriever import SemanticRetriever

_DOC_QA_SYSTEM_PROMPT = """You are a document QA engine.
Answer only from the provided document chunks and metadata.
Do not hallucinate or assume facts not present in the evidence.
Return strict JSON with this schema:
{
    "answer": "...",
    "supporting_points": ["..."],
    "citations": [{"chunk_id": "...", "source": "...", "quote": "..."}],
    "confidence": "high|medium|low",
    "entities": {
        "names": ["..."],
        "dates": ["..."],
        "prices": ["..."],
        "companies": ["..."],
        "plans": ["..."],
        "features": ["..."]
    }
}
"""

_MULTI_DOC_COMPARE_SYSTEM_PROMPT = """You are a cross-document analysis engine.
Compare documents only from provided evidence.
Do not hallucinate missing details.
Return strict JSON with this schema:
{
    "summary": "...",
    "comparisons": ["..."],
    "risks": ["..."],
    "recommendation": "...",
    "citations": [{"file": "...", "chunk_id": "...", "quote": "..."}],
    "entities": {
        "names": ["..."],
        "dates": ["..."],
        "prices": ["..."],
        "companies": ["..."],
        "plans": ["..."],
        "features": ["..."]
    }
}
"""


class DocumentQAEngine:
    """Retrieval-backed QA for analyzed documents."""

    def __init__(self, llm_client: DocumentLLMClient, retriever: SemanticRetriever) -> None:
        self._llm_client = llm_client
        self._retriever = retriever

    def answer_single_document_question(
        self,
        question: str,
        record: dict[str, Any],
        *,
        top_k: int,
    ) -> dict[str, Any]:
        chunks = record.get("chunks") if isinstance(record.get("chunks"), list) else []
        retrieved = self._retriever.retrieve(question, chunks, top_k=max(3, min(int(top_k), 10)))

        if not retrieved:
            fallback_text = self._fallback_context_text(record)
            if fallback_text:
                retrieved = [{"id": "fallback-0", "source": "summary", "text": fallback_text, "score": 0.01}]

        prompt_payload = {
            "question": question,
            "document": {
                "file_name": str(record.get("file_name") or "Document"),
                "summary": str(record.get("summary") or ""),
                "key_points": record.get("key_points") if isinstance(record.get("key_points"), list) else [],
                "entities": normalize_entities(record.get("entities")),
            },
            "retrieved_chunks": retrieved,
        }

        llm_result = self._llm_client.extract_json_fast(
            system_prompt=_DOC_QA_SYSTEM_PROMPT,
            user_prompt=(
                "Answer the question from this evidence payload only: "
                f"{self._to_json(prompt_payload)}"
            ),
            temperature=0.1,
            max_tokens=1300,
        )

        answer = ""
        supporting_points: list[str] = []
        confidence = "medium"
        llm_entities = self._empty_entities()

        if isinstance(llm_result, dict):
            answer = self._compact_text(str(llm_result.get("answer") or ""), max_chars=420)
            supporting_points = self._compact_list(llm_result.get("supporting_points"), max_items=4, max_chars=160)
            confidence = self._normalize_confidence(str(llm_result.get("confidence") or ""))
            llm_entities = normalize_entities(llm_result.get("entities"))

        if not answer:
            top_text = str(retrieved[0].get("text") or "").strip() if retrieved else ""
            answer = self._compact_text(top_text, max_chars=360) or "I could not find enough supporting evidence in the active document."
            if not supporting_points and top_text:
                supporting_points = [self._compact_text(top_text, max_chars=140)]
            confidence = "low"

        citations = self._build_citations(retrieved, file_name=str(record.get("file_name") or "Document"))
        evidence_text = "\n".join(str(item.get("text") or "") for item in retrieved)
        entities = merge_entities(
            normalize_entities(record.get("entities")),
            llm_entities,
            extract_key_entities(evidence_text),
        )

        return {
            "success": True,
            "mode": "single_document_qa",
            "question": question,
            "file_name": str(record.get("file_name") or "Document"),
            "file_path": str(record.get("file_path") or ""),
            "answer": answer,
            "supporting_points": supporting_points,
            "citations": citations,
            "confidence": confidence,
            "entities": entities,
            "retrieved_chunks": len(retrieved),
            "error": "",
        }

    def answer_multi_document_question(
        self,
        question: str,
        records: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> dict[str, Any]:
        evidence_docs: list[dict[str, Any]] = []
        merged_entities = self._empty_entities()
        merged_retrieved: list[dict[str, Any]] = []

        per_doc_k = max(2, min(6, int(top_k)))
        for record in records:
            chunks = record.get("chunks") if isinstance(record.get("chunks"), list) else []
            retrieved = self._retriever.retrieve(question, chunks, top_k=per_doc_k)
            if not retrieved:
                fallback_text = self._fallback_context_text(record)
                if fallback_text:
                    retrieved = [{"id": "fallback-0", "source": "summary", "text": fallback_text, "score": 0.01}]

            merged_retrieved.extend(
                {
                    "file": str(record.get("file_name") or "Document"),
                    "id": str(item.get("id") or ""),
                    "source": str(item.get("source") or "chunk"),
                    "text": str(item.get("text") or ""),
                    "score": float(item.get("score") or 0.0),
                }
                for item in retrieved
            )

            doc_entities = normalize_entities(record.get("entities"))
            merged_entities = merge_entities(merged_entities, doc_entities)

            evidence_docs.append(
                {
                    "file_name": str(record.get("file_name") or "Document"),
                    "summary": str(record.get("summary") or ""),
                    "key_points": record.get("key_points") if isinstance(record.get("key_points"), list) else [],
                    "risks": record.get("risks") if isinstance(record.get("risks"), list) else [],
                    "entities": doc_entities,
                    "retrieved_chunks": retrieved,
                }
            )

        prompt_payload = {
            "question": question,
            "documents": evidence_docs,
        }

        llm_result = self._run_compare_llm(question=question, prompt_payload=prompt_payload)

        summary = ""
        comparisons: list[str] = []
        risks: list[str] = []
        recommendation = ""
        llm_entities = self._empty_entities()
        confidence = "medium"

        if isinstance(llm_result, dict):
            summary = self._compact_text(str(llm_result.get("summary") or ""), max_chars=460)
            comparisons = self._compact_list(llm_result.get("comparisons"), max_items=6, max_chars=170)
            risks = self._compact_list(llm_result.get("risks"), max_items=5, max_chars=150)
            recommendation = self._compact_text(str(llm_result.get("recommendation") or ""), max_chars=220)
            llm_entities = normalize_entities(llm_result.get("entities"))
            confidence = "high" if summary else "medium"

        if not summary:
            summary = self._build_multi_doc_fallback_summary(records, question)
            confidence = "low"

        citations = self._build_multi_doc_citations(merged_retrieved)
        evidence_text = "\n".join(str(item.get("text") or "") for item in merged_retrieved)
        entities = merge_entities(merged_entities, llm_entities, extract_key_entities(evidence_text))

        answer = summary
        if recommendation:
            answer = f"{summary} Recommendation: {recommendation}".strip()

        return {
            "success": True,
            "mode": "multi_document_compare",
            "question": question,
            "answer": answer,
            "summary": summary,
            "comparisons": comparisons,
            "risks": risks,
            "recommendation": recommendation,
            "citations": citations,
            "confidence": confidence,
            "entities": entities,
            "document_count": len(records),
            "error": "",
        }

    @staticmethod
    def looks_like_compare_question(question: str) -> bool:
        lowered = str(question or "").lower()
        return bool(re.search(r"\b(compare|comparison|versus|\bvs\b|difference|differences)\b", lowered))

    @staticmethod
    def _needs_deep_compare(question: str) -> bool:
        lowered = str(question or "").lower()
        return any(
            token in lowered
            for token in (
                "detailed",
                "in detail",
                "deep",
                "comprehensive",
                "thorough",
                "exhaustive",
                "full breakdown",
            )
        )

    @staticmethod
    def _looks_like_compare_payload(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        if str(payload.get("summary") or "").strip():
            return True
        if isinstance(payload.get("comparisons"), list) and payload.get("comparisons"):
            return True
        if isinstance(payload.get("risks"), list) and payload.get("risks"):
            return True
        if str(payload.get("recommendation") or "").strip():
            return True
        return False

    def _run_compare_llm(self, *, question: str, prompt_payload: dict[str, Any]) -> dict[str, Any]:
        user_prompt = (
            "Compare and answer from this cross-document evidence payload only: "
            f"{self._to_json(prompt_payload)}"
        )

        if self._needs_deep_compare(question):
            deep_result = self._llm_client.extract_json_deep(
                system_prompt=_MULTI_DOC_COMPARE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.15,
                max_tokens=1900,
            )
            return deep_result if isinstance(deep_result, dict) else {}

        fast_result = self._llm_client.extract_json_fast(
            system_prompt=_MULTI_DOC_COMPARE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=1200,
        )
        if self._looks_like_compare_payload(fast_result):
            return fast_result

        deep_result = self._llm_client.extract_json_deep(
            system_prompt=_MULTI_DOC_COMPARE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.15,
            max_tokens=1900,
        )
        return deep_result if isinstance(deep_result, dict) else {}

    @staticmethod
    def _build_citations(retrieved: list[dict[str, Any]], *, file_name: str) -> list[dict[str, str]]:
        citations: list[dict[str, str]] = []
        for item in retrieved[:4]:
            quote = str(item.get("text") or "").strip()
            if not quote:
                continue
            citations.append(
                {
                    "file": file_name,
                    "chunk_id": str(item.get("id") or ""),
                    "source": str(item.get("source") or "chunk"),
                    "quote": quote[:180],
                }
            )
        return citations

    @staticmethod
    def _build_multi_doc_citations(retrieved: list[dict[str, Any]]) -> list[dict[str, str]]:
        citations: list[dict[str, str]] = []
        for item in retrieved[:8]:
            quote = str(item.get("text") or "").strip()
            if not quote:
                continue
            citations.append(
                {
                    "file": str(item.get("file") or "Document"),
                    "chunk_id": str(item.get("id") or ""),
                    "source": str(item.get("source") or "chunk"),
                    "quote": quote[:180],
                }
            )
        return citations

    @staticmethod
    def _build_multi_doc_fallback_summary(records: list[dict[str, Any]], question: str) -> str:
        file_names = [str(item.get("file_name") or "Document") for item in records]
        focus = DocumentQAEngine._compact_text(question, max_chars=120)
        return (
            f"Compared {len(records)} documents ({', '.join(file_names[:4])}) for: {focus}. "
            "Use the listed differences and evidence highlights for decision making."
        )

    @staticmethod
    def _fallback_context_text(record: dict[str, Any]) -> str:
        pieces: list[str] = [str(record.get("summary") or "").strip()]
        pieces.extend(str(item or "").strip() for item in (record.get("key_points") or [])[:4])
        return "\n".join(part for part in pieces if part)

    @staticmethod
    def _normalize_confidence(value: str) -> str:
        lowered = str(value or "").strip().lower()
        if lowered in {"high", "medium", "low"}:
            return lowered
        return "medium"

    @staticmethod
    def _to_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _empty_entities() -> dict[str, list[str]]:
        return {
            "names": [],
            "dates": [],
            "prices": [],
            "companies": [],
            "plans": [],
            "features": [],
        }

    @staticmethod
    def _compact_text(value: str, *, max_chars: int) -> str:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            return ""
        if len(cleaned) <= max_chars:
            return cleaned
        truncated = cleaned[:max_chars].rstrip(" ,.;:-")
        return truncated + "..."

    @classmethod
    def _compact_list(cls, value: Any, *, max_items: int, max_chars: int) -> list[str]:
        if not isinstance(value, list):
            return []

        output: list[str] = []
        seen: set[str] = set()
        for item in value:
            compact = cls._compact_text(str(item or ""), max_chars=max_chars)
            key = compact.lower()
            if not compact or key in seen:
                continue
            seen.add(key)
            output.append(compact)
            if len(output) >= max_items:
                break

        return output
