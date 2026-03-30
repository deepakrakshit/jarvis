from __future__ import annotations

import unittest

from services.document.qa_engine import DocumentQAEngine
from services.document.processors.retriever import SemanticRetriever


class _FakeLLMClient:
    def extract_json_fast(self, **_: object) -> dict:
        return {
            "answer": "Enterprise pricing is $149/month with API and analytics included.",
            "supporting_points": ["Pricing table includes Enterprise at $149/month."],
            "confidence": "high",
            "entities": {"prices": ["$149/month"], "plans": ["Enterprise"]},
        }

    def extract_json_deep(self, **_: object) -> dict:
        return {
            "summary": "Document A is cheaper, Document B has broader analytics.",
            "comparisons": ["A: lower cost", "B: richer features"],
            "risks": ["B has annual lock-in"],
            "recommendation": "Choose A for cost, B for capability depth.",
            "entities": {"prices": ["$149/month", "$199/month"], "plans": ["Enterprise", "Business"]},
        }


class QaEngineStressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DocumentQAEngine(_FakeLLMClient(), SemanticRetriever())

    def test_single_document_answer_shape(self) -> None:
        record = {
            "file_name": "Pricing_A.pdf",
            "file_path": "Pricing_A.pdf",
            "summary": "Enterprise plan starts at $149/month.",
            "key_points": ["API included", "Analytics included"],
            "entities": {},
            "chunks": [
                {"id": "c1", "source": "text", "text": "Enterprise plan is $149/month with API and analytics."},
                {"id": "c2", "source": "text", "text": "Business plan is $99/month."},
            ],
        }

        payload = self.engine.answer_single_document_question("what is the enterprise price", record, top_k=5)
        self.assertTrue(payload.get("success"))
        self.assertEqual(payload.get("mode"), "single_document_qa")
        self.assertTrue(payload.get("answer"))
        self.assertTrue(isinstance(payload.get("citations"), list))

    def test_multi_document_answer_shape(self) -> None:
        records = [
            {
                "file_name": "A.pdf",
                "summary": "A is lower cost.",
                "key_points": ["A = $149/month"],
                "risks": ["Annual payment"],
                "entities": {},
                "chunks": [{"id": "a1", "source": "text", "text": "A costs $149/month."}],
            },
            {
                "file_name": "B.pdf",
                "summary": "B has more features.",
                "key_points": ["B = $199/month"],
                "risks": ["Migration overhead"],
                "entities": {},
                "chunks": [{"id": "b1", "source": "text", "text": "B costs $199/month and has richer analytics."}],
            },
        ]

        payload = self.engine.answer_multi_document_question("compare pricing and risks", records, top_k=6)
        self.assertTrue(payload.get("success"))
        self.assertEqual(payload.get("mode"), "multi_document_compare")
        self.assertTrue(payload.get("summary"))
        self.assertTrue(isinstance(payload.get("comparisons"), list))


if __name__ == "__main__":
    unittest.main()
