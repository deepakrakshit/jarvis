from __future__ import annotations

import unittest

from services.document.vision import VisionConfig, VisionProcessor


class VisionModelChainNormalizationStressTest(unittest.TestCase):
    def test_openrouter_style_free_suffix_is_sanitized(self) -> None:
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
