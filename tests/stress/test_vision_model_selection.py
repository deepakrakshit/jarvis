from __future__ import annotations

import unittest

from services.document.vision import VisionConfig, VisionProcessor


class VisionModelSelectionStressTest(unittest.TestCase):
    def test_current_groq_model_chain_is_preserved(self) -> None:
        processor = VisionProcessor(
            VisionConfig(
                api_key="dummy",
                primary_model="meta-llama/llama-4-scout-17b-16e-instruct",
                fallback_models=(
                    "meta-llama/llama-4-maverick-17b-128e-instruct",
                    "meta-llama/llama-4-scout-17b-16e-instruct",
                ),
            )
        )

        self.assertEqual(processor._model_chain[0], "meta-llama/llama-4-scout-17b-16e-instruct")
        self.assertIn("meta-llama/llama-4-maverick-17b-128e-instruct", processor._model_chain)
        self.assertEqual(len(processor._model_chain), len(set(processor._model_chain)))

    def test_legacy_free_suffixes_fall_back_to_current_default(self) -> None:
        processor = VisionProcessor(
            VisionConfig(
                api_key="dummy",
                primary_model="google/gemma-3-27b-it:free",
                fallback_models=(
                    "google/gemma-3-12b-it:free",
                    "meta-llama/llama-4-scout-17b-16e-instruct",
                ),
            )
        )

        # Primary should fall back to Groq-safe default and free-tag fallbacks are ignored.
        self.assertEqual(processor._model_chain[0], "meta-llama/llama-4-scout-17b-16e-instruct")
        self.assertIn("meta-llama/llama-4-scout-17b-16e-instruct", processor._model_chain)
        self.assertTrue(all(":free" not in model for model in processor._model_chain))


if __name__ == "__main__":
    unittest.main()
