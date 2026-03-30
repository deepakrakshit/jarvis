from __future__ import annotations

import time
import unittest

from core.settings import AppConfig
from services.document.pipeline import DocumentPipeline


class _NoLlmCalls:
    def complete_fast(self, **_: object) -> str:
        raise AssertionError("LLM should not be called in ultra-fast deterministic mode")

    def extract_json_fast(self, **_: object) -> dict:
        raise AssertionError("LLM should not be called in ultra-fast deterministic mode")

    def extract_json_deep(self, **_: object) -> dict:
        raise AssertionError("LLM should not be called in ultra-fast deterministic mode")


class FastPathLatencyStressTest(unittest.TestCase):
    def test_ultra_fast_reasoning_skips_llm_roundtrip(self) -> None:
        config = AppConfig.from_env(".env")
        pipeline = DocumentPipeline(_NoLlmCalls(), config)
        pipeline._ultra_fast_enabled = True
        pipeline._ultra_fast_min_chars = 180
        pipeline._text_rich_min_chars = 600

        fused = {
            "text_content": " ".join(["Enterprise plan includes analytics, API access, SSO, and reporting."] * 30),
            "ocr_content": "",
            "vision_data": {
                "visible_text": "",
                "layout": "",
                "summary": "",
                "categories": [],
                "key_elements": [],
                "tables": [],
                "warnings": [],
                "errors": [],
            },
            "metadata": {"source_type": "pdf", "page_count": 8},
        }

        start = time.perf_counter()
        result = pipeline._reason_over_fused_data(
            fused=fused,
            tables=[],
            user_query="summarize this document quickly",
        )
        elapsed = time.perf_counter() - start

        self.assertEqual(result.metadata.get("reasoning_mode"), "ultra_fast_deterministic")
        self.assertTrue(result.summary)
        self.assertLess(elapsed, 0.15)


if __name__ == "__main__":
    unittest.main()
