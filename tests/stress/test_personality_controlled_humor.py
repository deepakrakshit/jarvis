from __future__ import annotations

import unittest

from core.humor import HumorEngine
from core.personality import PersonalityEngine


class PersonalityControlledHumorTest(unittest.TestCase):
    def test_finalize_appends_controlled_humor_line(self) -> None:
        engine = PersonalityEngine(humor_engine=HumorEngine(seed=7), controlled_humor=True)
        base = "Weather in Delhi is 31C with moderate humidity."

        result = engine.finalize(base, user_text="weather in delhi")

        self.assertTrue(result.startswith(base))
        self.assertGreater(len(result), len(base))

    def test_finalize_is_idempotent_when_called_twice(self) -> None:
        engine = PersonalityEngine(humor_engine=HumorEngine(seed=11), controlled_humor=True)
        base = "Internet connectivity is up."

        first = engine.finalize(base, user_text="check internet connectivity")
        second = engine.finalize(first, user_text="check internet connectivity")

        self.assertEqual(first, second)

    def test_finalize_varies_humor_lines_over_consecutive_turns(self) -> None:
        engine = PersonalityEngine(humor_engine=HumorEngine(seed=13), controlled_humor=True)
        base = "Public IP: 1.2.3.4."

        outputs = [engine.finalize(base, user_text="what is my ip") for _ in range(6)]
        tails = [item.replace(base, "", 1).strip() for item in outputs]

        self.assertGreaterEqual(len(set(tails)), 4)


if __name__ == "__main__":
    unittest.main()
