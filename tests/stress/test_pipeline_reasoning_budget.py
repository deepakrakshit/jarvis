from __future__ import annotations

import unittest

from core.settings import AppConfig
from services.document.pipeline import DocumentPipeline


class _FakeLlm:
    def complete_fast(self, **_: object) -> str:
        return ""

    def extract_json_fast(self, **_: object) -> dict:
        return {
            "summary": "ok",
            "insights": [],
            "key_points": [],
            "metrics": [],
            "risks": [],
            "entities": {},
        }

    def extract_json_deep(self, **_: object) -> dict:
        return {
            "summary": "ok",
            "insights": [],
            "key_points": [],
            "metrics": [],
            "risks": [],
            "entities": {},
        }


class PipelineReasoningBudgetStressTest(unittest.TestCase):
    def test_reasoning_payload_respects_budgets(self) -> None:
        config = AppConfig.from_env(".env")
        pipeline = DocumentPipeline(_FakeLlm(), config)

        fused = {
            "text_content": "A" * 120000,
            "ocr_content": "B" * 50000,
            "vision_data": {
                "visible_text": "C" * 35000,
                "layout": "D" * 12000,
                "summary": "E" * 9000,
                "categories": ["invoice"],
                "key_elements": ["pricing table"],
                "tables": [],
                "warnings": [],
                "errors": [],
            },
            "metadata": {
                "source_type": "pdf",
                "retrieval_chunks": [{"id": "x"}],
                "text_primary_applied": True,
                "text_primary_summary": "S" * 2000,
                "text_primary_key_points": ["kp1", "kp2"],
                "text_primary_risks": ["r1"],
                "text_primary_mode": "llm_text_primary",
            },
        }

        payload = pipeline._build_reasoning_payload(fused, user_query="extract pricing and risk details")

        self.assertLessEqual(len(payload["text_content"]), config.document_reasoning_text_char_budget + 3)
        self.assertLessEqual(len(payload["ocr_content"]), config.document_reasoning_ocr_char_budget + 3)
        self.assertLessEqual(
            len(payload["vision_data"]["visible_text"]),
            config.document_reasoning_vision_visible_char_budget + 3,
        )
        self.assertLessEqual(
            len(payload["vision_data"]["layout"]),
            config.document_reasoning_vision_layout_char_budget + 3,
        )
        self.assertLessEqual(
            len(payload["vision_data"]["summary"]),
            config.document_reasoning_vision_summary_char_budget + 3,
        )
        self.assertEqual(payload["user_query"], "extract pricing and risk details")
        self.assertTrue(payload["text_primary_context"]["applied"])
        self.assertLessEqual(len(payload["text_primary_context"]["summary"]), 363)


if __name__ == "__main__":
    unittest.main()
