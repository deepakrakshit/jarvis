from __future__ import annotations

import unittest

from services.document.processors.retriever import SemanticRetriever
from services.document.qa_engine import DocumentQAEngine


class _FastCompareLLM:
    def __init__(self) -> None:
        self.fast_calls = 0
        self.deep_calls = 0

    def extract_json_fast(self, **_: object) -> dict:
        self.fast_calls += 1
        return {
            "summary": "Quick compare summary.",
            "comparisons": ["A has lower pricing", "B has more features"],
            "risks": ["B requires yearly lock-in"],
            "recommendation": "Pick A for cost-sensitive decisions.",
            "entities": {"prices": ["$99", "$149"], "plans": ["A", "B"]},
        }

    def extract_json_deep(self, **_: object) -> dict:
        self.deep_calls += 1
        return {
            "summary": "Deep compare summary.",
            "comparisons": ["Deep output"],
            "risks": [],
            "recommendation": "Deep recommendation",
            "entities": {},
        }


class _FallbackCompareLLM:
    def __init__(self) -> None:
        self.fast_calls = 0
        self.deep_calls = 0

    def extract_json_fast(self, **_: object) -> dict:
        self.fast_calls += 1
        return {"answer": "invalid compare schema"}

    def extract_json_deep(self, **_: object) -> dict:
        self.deep_calls += 1
        return {
            "summary": "Deep fallback summary.",
            "comparisons": ["A vs B"],
            "risks": ["Contract lock-in"],
            "recommendation": "Choose A",
            "entities": {},
        }


class CompareModelRoutingTest(unittest.TestCase):
    @staticmethod
    def _records() -> list[dict]:
        return [
            {
                "file_name": "A.pdf",
                "summary": "Plan A starts at $99.",
                "key_points": ["Lower cost"],
                "risks": ["Limited analytics"],
                "entities": {},
                "chunks": [{"id": "a1", "source": "text", "text": "A plan costs $99 monthly."}],
            },
            {
                "file_name": "B.pdf",
                "summary": "Plan B starts at $149.",
                "key_points": ["Richer analytics"],
                "risks": ["Annual lock-in"],
                "entities": {},
                "chunks": [{"id": "b1", "source": "text", "text": "B plan costs $149 monthly."}],
            },
        ]

    def test_compare_uses_fast_model_first(self) -> None:
        llm = _FastCompareLLM()
        engine = DocumentQAEngine(llm, SemanticRetriever())

        payload = engine.answer_multi_document_question("compare pricing and risks", self._records(), top_k=6)

        self.assertTrue(payload.get("success"))
        self.assertEqual(payload.get("mode"), "multi_document_compare")
        self.assertIn("Quick compare", str(payload.get("summary") or ""))
        self.assertEqual(llm.fast_calls, 1)
        self.assertEqual(llm.deep_calls, 0)

    def test_compare_falls_back_to_deep_when_fast_schema_is_invalid(self) -> None:
        llm = _FallbackCompareLLM()
        engine = DocumentQAEngine(llm, SemanticRetriever())

        payload = engine.answer_multi_document_question("compare pricing and risks", self._records(), top_k=6)

        self.assertTrue(payload.get("success"))
        self.assertEqual(payload.get("mode"), "multi_document_compare")
        self.assertIn("Deep fallback", str(payload.get("summary") or ""))
        self.assertEqual(llm.fast_calls, 1)
        self.assertEqual(llm.deep_calls, 1)


if __name__ == "__main__":
    unittest.main()