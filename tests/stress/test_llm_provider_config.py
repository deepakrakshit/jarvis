from __future__ import annotations

import unittest
from unittest.mock import patch

from core.settings import AppConfig


class LlmProviderConfigTest(unittest.TestCase):
    def test_primary_config_uses_gemini_key_and_model(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GEMINI_API_KEY": "gem-key",
                "GEMINI_MODEL": "gemini-2.5-flash",
            },
            clear=False,
        ):
            config = AppConfig.from_env(".env")

        self.assertEqual(config.normalized_llm_provider(), "gemini")
        self.assertEqual(config.primary_llm_api_key(), "gem-key")
        self.assertEqual(config.primary_llm_model(), "gemini-2.5-flash")
        self.assertEqual(config.required_primary_llm_key_name(), "GEMINI_API_KEY")

    def test_provider_name_is_gemini_even_with_unknown_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LLM_PROVIDER": "unknown",
                "GEMINI_API_KEY": "gem-key",
            },
            clear=False,
        ):
            config = AppConfig.from_env(".env")

        self.assertEqual(config.normalized_llm_provider(), "gemini")
        self.assertEqual(config.primary_llm_api_key(), "gem-key")
        self.assertEqual(config.required_primary_llm_key_name(), "GEMINI_API_KEY")


if __name__ == "__main__":
    unittest.main()
