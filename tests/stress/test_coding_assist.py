# ==============================================================================
# File: tests/stress/test_coding_assist.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Core module for test_coding_assist functionalities.
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

from services.actions.coding_assist import CodingAssistService, GeneratedProjectBundle, coding_assist_action


class CodingAssistStressTest(unittest.TestCase):
    def test_sanitize_project_name_preserves_readable_slug(self) -> None:
        self.assertEqual(
            CodingAssistService._sanitize_project_name(" Calculator from scratch! "),
            "Calculator-from-scratch",
        )

    def test_sanitize_project_name_trims_trailing_separator(self) -> None:
        self.assertEqual(CodingAssistService._sanitize_project_name("CALCULATOR_"), "CALCULATOR")

    def test_create_project_accepts_python_alias_with_calculator_objective(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = CodingAssistService(workspace_root=temp_dir)
            with patch.object(service, "_generate_project_with_gemini", return_value=None), patch.object(
                service._file_controller,
                "open_path",
                return_value={"success": True, "status": "success", "action": "open"},
            ):
                result = service.create_project(
                    name="Calculator",
                    project_type="python",
                    objective="Build an advanced calculator with tests.",
                )

            self.assertTrue(result.get("success"), result)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertEqual(data.get("project_type"), "python-cli")
            self.assertEqual(data.get("generator"), "template")
            self.assertTrue(bool(data.get("opened")))
            project_root = Path(str(data.get("project_root") or "")).as_posix()
            self.assertIn("/Projects/", project_root)

            created_files = data.get("created_files") if isinstance(data.get("created_files"), list) else []
            created_posix = {Path(path).as_posix() for path in created_files}
            self.assertTrue(any(path.endswith("src/calculator/engine.py") for path in created_posix))
            self.assertTrue(any(path.endswith("src/calculator/errors.py") for path in created_posix))
            self.assertTrue(any(path.endswith("tests/test_cli.py") for path in created_posix))

    def test_create_project_prefers_gemini_bundle_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = CodingAssistService(workspace_root=temp_dir)
            generated = GeneratedProjectBundle(
                files=(
                    ("README.md", "# Generated\n"),
                    ("src/main.py", "print('generated')\n"),
                ),
                summary="Generated scaffold from Gemini",
            )

            with patch.object(service, "_generate_project_with_gemini", return_value=generated), patch.object(
                service._file_controller,
                "open_path",
                return_value={"success": True, "status": "success", "action": "open"},
            ):
                result = service.create_project(
                    name="SampleProject",
                    project_type="py",
                    objective="Create a small demo app.",
                )

            self.assertTrue(result.get("success"), result)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertEqual(data.get("generator"), "gemini")
            self.assertEqual(data.get("generation_summary"), "Generated scaffold from Gemini")

            project_root = Path(str(data.get("project_root") or ""))
            self.assertTrue((project_root / "README.md").exists())
            self.assertTrue((project_root / "src" / "main.py").exists())
            self.assertTrue(bool(data.get("opened")))

    def test_action_prompt_is_used_as_project_objective(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(CodingAssistService, "_generate_project_with_gemini", return_value=None), patch(
                "services.actions.coding_assist.FileController.open_path",
                return_value={"success": True, "status": "success", "action": "open"},
            ):
                result = coding_assist_action(
                    {
                        "action": "create_project",
                        "name": "Tracker",
                        "project_type": "python",
                        "prompt": "Build a task tracker CLI with persistent storage.",
                    },
                    workspace_root=temp_dir,
                )

            self.assertTrue(result.get("success"), result)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            objective = str(data.get("objective") or "")
            self.assertIn("task tracker CLI", objective)
            project_root = Path(str(data.get("project_root") or "")).as_posix()
            self.assertIn("/Projects/", project_root)

    def test_compare_dependencies_falls_back_to_pyproject_when_setup_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text("requests\nfastapi\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["requests>=2.0", "uvicorn"]
""".strip()
                + "\n",
                encoding="utf-8",
            )

            service = CodingAssistService(workspace_root=temp_dir)
            result = service.compare_dependencies()

            self.assertTrue(result.get("success"), result)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertEqual(data.get("reference_source"), "pyproject.toml")
            self.assertIn("fastapi", data.get("only_in_requirements", []))
            self.assertIn("uvicorn", data.get("only_in_reference", []))

    def test_compare_dependencies_action_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "requirements.txt").write_text("requests\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                """
[project]
name = "demo"
version = "0.1.0"
dependencies = ["requests"]
""".strip()
                + "\n",
                encoding="utf-8",
            )

            result = coding_assist_action(
                {
                    "action": "compare_dependencies",
                    "requirements_path": "requirements.txt",
                    "setup_path": "setup.py",
                    "pyproject_path": "pyproject.toml",
                },
                workspace_root=temp_dir,
            )

            self.assertTrue(result.get("success"), result)
            self.assertEqual(result.get("action"), "compare_dependencies")

    def test_run_file_executes_python_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "main.py"
            script.write_text("print('ok')\n", encoding="utf-8")

            service = CodingAssistService(workspace_root=temp_dir)
            with patch.object(
                service._cmd_controller,
                "run",
                return_value={"status": "success", "action": "run_command", "success": True, "verified": True},
            ) as run_mock:
                result = service.run_file(file_path="main.py")

            self.assertTrue(result.get("success"), result)
            self.assertEqual(result.get("action"), "run_file")
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertIn("python", str(data.get("command") or ""))
            run_mock.assert_called_once()

    def test_run_project_infers_npm_dev_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "package.json").write_text(
                '{"name":"demo","version":"1.0.0","scripts":{"dev":"vite"}}\n',
                encoding="utf-8",
            )

            service = CodingAssistService(workspace_root=temp_dir)
            with patch.object(
                service._cmd_controller,
                "run",
                return_value={"status": "success", "action": "run_command", "success": True, "verified": True},
            ) as run_mock:
                result = service.run_project(project_path=".", request="run this project")

            self.assertTrue(result.get("success"), result)
            self.assertEqual(result.get("action"), "run_project")
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertEqual(data.get("command"), "npm run dev")
            run_mock.assert_called_once()

    def test_run_from_request_handles_open_and_run_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "main.py"
            script.write_text("print('ok')\n", encoding="utf-8")

            service = CodingAssistService(workspace_root=temp_dir)
            with patch.object(
                service._file_controller,
                "open_path",
                return_value={"status": "success", "success": True, "action": "open"},
            ) as open_mock, patch.object(
                service._cmd_controller,
                "run",
                return_value={"status": "success", "action": "run_command", "success": True, "verified": True},
            ) as run_mock:
                result = service.run_from_request(
                    request="open the project folder and run main.py in terminal",
                    open_folder=True,
                )

            self.assertTrue(result.get("success"), result)
            self.assertEqual(result.get("action"), "run_from_request")
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            self.assertEqual(data.get("run_action"), "run_file")
            self.assertIn("python", str(data.get("command") or ""))
            open_mock.assert_called_once()
            run_mock.assert_called_once()

    def test_run_from_request_action_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "main.py"
            script.write_text("print('adapter')\n", encoding="utf-8")

            with patch("services.actions.coding_assist.FileController.open_path", return_value={"success": True}), patch(
                "services.actions.coding_assist.CmdControl.run",
                return_value={"status": "success", "action": "run_command", "success": True, "verified": True},
            ):
                result = coding_assist_action(
                    {
                        "action": "run_from_request",
                        "request": "run main.py in terminal",
                        "open_folder": False,
                    },
                    workspace_root=temp_dir,
                )

            self.assertTrue(result.get("success"), result)
            self.assertEqual(result.get("action"), "run_from_request")


if __name__ == "__main__":
    unittest.main()