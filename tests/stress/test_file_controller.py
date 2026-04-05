# ==============================================================================
# File: tests/stress/test_file_controller.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Core module for test_file_controller functionalities.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.actions.file_controller import FileController


class FileControllerStressTest(unittest.TestCase):
    def test_workspace_boundary_blocks_external_read(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as external_dir:
            external_file = Path(external_dir) / "secret.txt"
            external_file.write_text("hidden", encoding="utf-8")

            controller = FileController(workspace_root=workspace_dir)
            result = controller.read_text(path=str(external_file))

            self.assertFalse(bool(result.get("success")), result)
            self.assertEqual(result.get("error"), "invalid_path")

    def test_list_entries_respects_limit_and_reports_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            root = Path(workspace_dir)
            for idx in range(6):
                (root / f"file_{idx}.txt").write_text("x", encoding="utf-8")

            controller = FileController(workspace_root=workspace_dir)
            result = controller.list_entries(path=".", limit=3)

            self.assertTrue(bool(result.get("success")), result)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            entries = data.get("entries") if isinstance(data.get("entries"), list) else []
            self.assertEqual(len(entries), 3)
            self.assertTrue(bool(data.get("truncated")))

    def test_write_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            controller = FileController(workspace_root=workspace_dir)
            write_result = controller.write_text(path="a/b/sample.txt", content="hello")
            self.assertTrue(bool(write_result.get("success")), write_result)

            read_result = controller.read_text(path="a/b/sample.txt")
            self.assertTrue(bool(read_result.get("success")), read_result)
            data = read_result.get("data") if isinstance(read_result.get("data"), dict) else {}
            self.assertEqual(data.get("content"), "hello")

    def test_bulk_random_generation_fills_remaining_files(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            target_dir = Path(workspace_dir) / "StressTest"
            target_dir.mkdir(parents=True, exist_ok=True)
            for idx in range(1, 6):
                (target_dir / f"file_{idx:03d}.txt").write_text("seed", encoding="utf-8")

            controller = FileController(workspace_root=workspace_dir)
            result = controller.create_random_text_files(path="StressTest", count=50, fill_to_count=True)

            self.assertTrue(bool(result.get("success")), result)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertEqual(data.get("target_count"), 50)
            self.assertEqual(data.get("created_count"), 45)
            self.assertEqual(data.get("existing_count"), 5)
            self.assertEqual(data.get("total_available"), 50)

    def test_bulk_random_generation_rejects_zero_count(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            controller = FileController(workspace_root=workspace_dir)
            result = controller.create_random_text_files(path="StressTest", count=0)

            self.assertFalse(bool(result.get("success")), result)
            self.assertEqual(result.get("error"), "invalid_count")

    def test_bulk_random_generation_supports_exact_chars(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            controller = FileController(workspace_root=workspace_dir)
            result = controller.create_random_text_files(path="StressTest", count=3, exact_chars=1024)

            self.assertTrue(bool(result.get("success")), result)
            sample = Path(workspace_dir) / "StressTest" / "file_001.txt"
            self.assertTrue(sample.exists())
            payload = sample.read_text(encoding="utf-8")
            self.assertEqual(len(payload), 1024)

    def test_filter_move_by_content_moves_matching_files(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            root = Path(workspace_dir) / "StressTest"
            root.mkdir(parents=True, exist_ok=True)
            (root / "file_001.txt").write_text("abcdez", encoding="utf-8")
            (root / "file_002.txt").write_text("abcde", encoding="utf-8")

            controller = FileController(workspace_root=workspace_dir)
            result = controller.filter_move_by_content(
                path="StressTest",
                search_text="z",
                destination_subfolder="Filtered",
            )

            self.assertTrue(bool(result.get("success")), result)
            self.assertFalse((root / "file_001.txt").exists())
            self.assertTrue((root / "Filtered" / "file_001.txt").exists())
            self.assertIn("z", (root / "Filtered" / "file_001.txt").read_text(encoding="utf-8"))
            self.assertTrue((root / "file_002.txt").exists())

    def test_open_path_allows_external_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as external_dir:
            external_file = Path(external_dir) / "clip.txt"
            external_file.write_text("hello", encoding="utf-8")

            controller = FileController(workspace_root=workspace_dir)
            with patch("services.actions.file_controller.os.name", "nt"), patch(
                "services.actions.file_controller.os.startfile"
            ) as startfile_mock:
                result = controller.open_path(path=str(external_file))

            self.assertTrue(bool(result.get("success")), result)
            startfile_mock.assert_called_once()

    def test_open_path_fuzzy_resolves_movie_in_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as home_dir:
            downloads = Path(home_dir) / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            movie = downloads / "Peaky.Blinders.The.Immortal.Man.2026.1080p.mkv"
            movie.write_text("stub", encoding="utf-8")

            controller = FileController(workspace_root=workspace_dir)
            with patch("services.actions.file_controller.Path.home", return_value=Path(home_dir)), patch(
                "services.actions.file_controller.os.name", "nt"
            ), patch("services.actions.file_controller.os.startfile") as startfile_mock:
                result = controller.open_path(path="open the peaky bliners movie from the downloads folder")

            self.assertTrue(bool(result.get("success")), result)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertIn("matched_path", data)
            self.assertTrue(str(data.get("matched_path") or "").lower().endswith(".mkv"))
            startfile_mock.assert_called_once()

    def test_open_path_suggests_related_file_when_exact_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as home_dir:
            downloads = Path(home_dir) / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            near_match = downloads / "Peaky.Notes.2026.mp4"
            near_match.write_text("stub", encoding="utf-8")

            controller = FileController(workspace_root=workspace_dir)
            with patch("services.actions.file_controller.Path.home", return_value=Path(home_dir)), patch(
                "services.actions.file_controller.os.name", "nt"
            ), patch("services.actions.file_controller.os.startfile") as startfile_mock:
                result = controller.open_path(path="open peaky blinders movie from downloads")

            self.assertFalse(bool(result.get("success")), result)
            self.assertEqual(result.get("error"), "not_found_with_suggestion")
            self.assertIn("If you want it, say: open", str(result.get("message") or ""))
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            suggestions = data.get("suggestions") if isinstance(data.get("suggestions"), list) else []
            self.assertTrue(suggestions)
            startfile_mock.assert_not_called()

    def test_open_path_folder_only_request_opens_named_folder(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as home_dir:
            downloads = Path(home_dir) / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)

            controller = FileController(workspace_root=workspace_dir)
            with patch("services.actions.file_controller.Path.home", return_value=Path(home_dir)), patch(
                "services.actions.file_controller.os.name", "nt"
            ), patch("services.actions.file_controller.os.startfile") as startfile_mock:
                result = controller.open_path(path="open downloads folder")

            self.assertTrue(bool(result.get("success")), result)
            startfile_mock.assert_called_once()

    def test_remove_blocks_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            controller = FileController(workspace_root=workspace_dir)
            result = controller.remove(path=workspace_dir, recursive=True)

            self.assertFalse(bool(result.get("success")), result)
            self.assertEqual(result.get("error"), "protected_path")


if __name__ == "__main__":
    unittest.main()
