from __future__ import annotations

import unittest

from services.document.vision import VisionConfig, VisionProcessor


class VisionModelSelectionStressTest(unittest.TestCase):
    def test_current_gemini_model_chain_is_preserved(self) -> None:
        processor = VisionProcessor(
            VisionConfig(
                api_key="dummy",
                primary_model="gemini-2.5-flash",
                fallback_models=(
                    "gemini-2.0-flash",
                    "gemini-2.5-flash",
                ),
            )
        )

        self.assertEqual(processor._model_chain[0], "gemini-2.5-flash")
        self.assertIn("gemini-2.0-flash", processor._model_chain)
        self.assertEqual(len(processor._model_chain), len(set(processor._model_chain)))

    def test_legacy_free_suffixes_are_normalized(self) -> None:
        processor = VisionProcessor(
            VisionConfig(
                api_key="dummy",
                primary_model="gemini-2.5-flash:free",
                fallback_models=(
                    "gemini-2.0-flash:free",
                    "gemini-2.5-flash",
                ),
            )
        )

        self.assertEqual(processor._model_chain[0], "gemini-2.5-flash")
        self.assertIn("gemini-2.0-flash", processor._model_chain)
        self.assertTrue(all(":free" not in model for model in processor._model_chain))


if __name__ == "__main__":
    unittest.main()
