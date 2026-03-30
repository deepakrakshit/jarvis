from __future__ import annotations

import time
import unittest

from services.document.processors.entities import extract_key_entities, normalize_entities


class EntitiesStressTest(unittest.TestCase):
    def test_entity_extraction_stability_under_load(self) -> None:
        text = "\n".join(
            [
                "Acme Corporation announced the Enterprise Plan at $199/month on 2026-01-12.",
                "Contact: Dr Alice Johnson. Features include OCR, API, Analytics, and Reporting.",
                "Beta Ltd and Gamma LLC were listed in the procurement notes.",
            ]
            * 900
        )

        start = time.perf_counter()
        final_payload = {}
        for _ in range(80):
            final_payload = extract_key_entities(text)
            final_payload = normalize_entities(final_payload)
        elapsed = time.perf_counter() - start

        self.assertIn("prices", final_payload)
        self.assertIn("companies", final_payload)
        self.assertTrue(final_payload["companies"])
        self.assertLess(elapsed, 18.0)


if __name__ == "__main__":
    unittest.main()
