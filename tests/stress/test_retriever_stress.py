from __future__ import annotations

import time
import unittest

from services.document.processors.retriever import SemanticRetriever


class RetrieverStressTest(unittest.TestCase):
    def test_retriever_build_and_query_throughput(self) -> None:
        retriever = SemanticRetriever(max_chunk_chars=720, overlap_chars=120)

        base_paragraph = (
            "The Enterprise plan costs $149 per month and includes API access, "
            "advanced analytics, SSO, audit logs, and priority support. "
            "Risk notes include lock-in period and annual billing terms. "
            "Contract date: 2026-03-01."
        )
        text_blocks = [
            ("text", "\n\n".join(base_paragraph for _ in range(650))),
            ("ocr", "\n\n".join(base_paragraph for _ in range(220))),
            ("vision_summary", "Pricing table confirms Pro, Business, and Enterprise tiers."),
        ]

        build_start = time.perf_counter()
        chunks = retriever.build_chunks(text_blocks, max_chunks=220)
        build_elapsed = time.perf_counter() - build_start

        self.assertGreaterEqual(len(chunks), 120)

        queries = [
            "what is the enterprise price",
            "list risk notes",
            "find billing terms",
            "which plans are mentioned",
            "show date and contract reference",
            "compare pro vs enterprise features",
        ] * 90

        query_start = time.perf_counter()
        total_hits = 0
        for query in queries:
            results = retriever.retrieve(query, chunks, top_k=6)
            total_hits += len(results)
        query_elapsed = time.perf_counter() - query_start

        self.assertGreater(total_hits, 0)
        # Keep thresholds generous to avoid flaky CI on low-end machines.
        self.assertLess(build_elapsed, 10.0)
        self.assertLess(query_elapsed, 20.0)


if __name__ == "__main__":
    unittest.main()
