from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from services.actions import screen_processor as sp


def _frame_bytes(rect: tuple[int, int, int, int]) -> bytes:
    image = Image.new("RGB", (320, 180), color=(12, 12, 12))
    draw = ImageDraw.Draw(image)
    draw.rectangle(rect, fill=(240, 240, 240))
    draw.rectangle((rect[0] + 10, rect[1] + 10, rect[0] + 30, rect[1] + 30), fill=(60, 190, 80))

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class ScreenProcessorPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        sp._reset_state_for_tests()

    def test_screen_process_returns_structured_payload(self) -> None:
        with patch.object(sp, "_capture_screenshot", return_value=_frame_bytes((70, 40, 190, 130))):
            result = sp.screen_process(
                {
                    "angle": "screen",
                    "action": "view_now",
                    "text": "show me my screen",
                    "live_enrichment": False,
                }
            )

        self.assertTrue(bool(result.get("success")))
        self.assertEqual(str(result.get("status")), "success")
        self.assertEqual(str(result.get("action")), "screen_process")

        analysis = result.get("analysis")
        self.assertIsInstance(analysis, dict)
        assert isinstance(analysis, dict)
        self.assertTrue(bool(str(analysis.get("summary") or "").strip()))

        history = analysis.get("history")
        self.assertIsInstance(history, dict)
        assert isinstance(history, dict)
        self.assertGreaterEqual(int(history.get("frames_stored") or 0), 1)

    def test_view_latest_returns_cached_frame_without_new_capture(self) -> None:
        with patch.object(sp, "_capture_screenshot", return_value=_frame_bytes((60, 30, 170, 120))):
            first = sp.screen_process(
                {
                    "angle": "screen",
                    "action": "view_now",
                    "text": "analyze screen",
                    "live_enrichment": False,
                }
            )

        with patch.object(sp, "_capture_screenshot", side_effect=AssertionError("unexpected capture call")):
            cached = sp.screen_process(
                {
                    "angle": "screen",
                    "action": "view_latest",
                    "live_enrichment": False,
                }
            )

        self.assertTrue(bool(cached.get("success")))
        self.assertTrue(bool(cached.get("analysis", {}).get("from_cache")))
        self.assertEqual(first.get("analysis", {}).get("frame_id"), cached.get("analysis", {}).get("frame_id"))

    @unittest.skipUnless(getattr(sp, "_CV2_OK", False) and getattr(sp, "_NP_OK", False), "requires cv2 + numpy")
    def test_object_tracking_reuses_track_ids_across_frames(self) -> None:
        frames = [
            _frame_bytes((70, 40, 190, 130)),
            _frame_bytes((82, 44, 202, 134)),
        ]

        with patch.object(sp, "_capture_screenshot", side_effect=lambda: frames.pop(0)):
            first = sp.screen_process(
                {
                    "angle": "screen",
                    "action": "analyze",
                    "text": "analyze my screen",
                    "live_enrichment": False,
                }
            )
            second = sp.screen_process(
                {
                    "angle": "screen",
                    "action": "analyze",
                    "text": "analyze my screen again",
                    "live_enrichment": False,
                }
            )

        first_ids = {int(obj.get("track_id")) for obj in first.get("analysis", {}).get("objects", []) if isinstance(obj, dict)}
        second_ids = {int(obj.get("track_id")) for obj in second.get("analysis", {}).get("objects", []) if isinstance(obj, dict)}

        self.assertTrue(first_ids)
        self.assertTrue(second_ids)
        self.assertTrue(bool(first_ids.intersection(second_ids)))


if __name__ == "__main__":
    unittest.main()
