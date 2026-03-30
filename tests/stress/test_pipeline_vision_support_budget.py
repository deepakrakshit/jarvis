from __future__ import annotations

import unittest

from core.settings import AppConfig
from services.document.models import PipelineProgress, RawExtractionResult
from services.document.pipeline import DocumentPipeline


class _FastLlmStub:
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


class PipelineVisionSupportBudgetStressTest(unittest.TestCase):
    def test_text_primary_caps_vision_support_inputs(self) -> None:
        config = AppConfig.from_env(".env")
        pipeline = DocumentPipeline(_FastLlmStub(), config)
        pipeline._text_rich_min_chars = 900
        pipeline._text_primary_max_vision_support_images = 3
        pipeline._vision_support_second_pass = False

        long_text = "\n".join(["Enterprise plan includes API, analytics, and reporting."] * 80)
        vision_images = [
            {
                "source": f"page_{idx}",
                "mime_type": "image/png",
                "bytes": b"fake-image-bytes",
            }
            for idx in range(1, 10)
        ]

        extraction = RawExtractionResult(
            text=long_text,
            pages=[],
            tables=[],
            metadata={
                "vision_images": vision_images,
                "ocr_images": [],
                "is_scanned": False,
                "source_type": "pdf",
            },
            source_type="pdf",
            file_path="dummy.pdf",
            error="",
        )

        captured: dict[str, object] = {
            "vision_count": 0,
            "allow_second_pass": None,
            "ocr_called": False,
        }

        def _vision_stub(images: list[dict], max_workers: int = 3, allow_second_pass: bool = False) -> list[dict]:
            captured["vision_count"] = len(images)
            captured["allow_second_pass"] = allow_second_pass
            return [
                {
                    "visible_text": "Vision support context",
                    "layout": "table",
                    "categories": ["pricing"],
                    "key_elements": ["enterprise"],
                    "tables": [],
                    "summary": "Vision summary",
                    "warning": "",
                    "error": "",
                }
            ]

        def _ocr_stub(*_: object, **__: object) -> dict:
            captured["ocr_called"] = True
            return {"text": "", "confidence": 0.0, "warning": "", "error": "", "per_image": []}

        pipeline._parse_document = lambda _path: extraction
        pipeline._vision.analyze_images = _vision_stub
        pipeline._ocr.extract_images = _ocr_stub

        result = pipeline._process_document(
            "dummy.pdf",
            PipelineProgress(),
            user_query="summarize this document",
        )

        self.assertEqual(captured["vision_count"], 3)
        self.assertFalse(bool(captured["allow_second_pass"]))
        self.assertFalse(bool(captured["ocr_called"]))

        self.assertEqual(result.metadata.get("vision_input_count_original"), 9)
        self.assertEqual(result.metadata.get("vision_input_count_used"), 3)
        self.assertTrue(result.metadata.get("text_primary_applied"))


if __name__ == "__main__":
    unittest.main()
