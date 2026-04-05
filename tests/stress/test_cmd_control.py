# ==============================================================================
# File: tests/stress/test_cmd_control.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Core module for test_cmd_control functionalities.
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

from services.system.cmd_control import cmd_control_action
from services.system.cmd_control import CmdControl


class CmdControlStressTest(unittest.TestCase):
    def test_rejects_blocked_control_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            controller = CmdControl(workspace_root=workspace_dir)
            result = controller.run(command="echo hello && echo world")

            self.assertFalse(bool(result.get("success")), result)
            self.assertEqual(result.get("error"), "blocked_command")

    def test_rejects_cwd_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as external_dir:
            controller = CmdControl(workspace_root=workspace_dir)
            result = controller.run(command="echo ok", cwd=external_dir)

            self.assertFalse(bool(result.get("success")), result)
            self.assertEqual(result.get("error"), "invalid_cwd")

    def test_redacts_sensitive_env_values_from_output(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            controller = CmdControl(workspace_root=workspace_dir)
            result = controller.run(command="echo %API_TOKEN%", env={"API_TOKEN": "super-secret-token"})

            self.assertTrue(bool(result.get("success")), result)
            stdout = str(result.get("stdout") or "")
            self.assertIn("[REDACTED]", stdout)
            self.assertNotIn("super-secret-token", stdout)

    def test_allows_safe_command(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            controller = CmdControl(workspace_root=workspace_dir)
            result = controller.run(command="echo safe-run")

            self.assertTrue(bool(result.get("success")), result)
            self.assertEqual(int(result.get("exit_code", 1)), 0)

    def test_action_alias_execute_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            result = cmd_control_action(
                {"action": "execute", "command": "echo ok"},
                workspace_root=workspace_dir,
            )

            self.assertNotEqual(result.get("error"), "unsupported_action")

    def test_blocks_windows_recursive_delete_command(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            result = cmd_control_action(
                {"action": "run", "command": "rd /s /q C:\\Users\\Public"},
                workspace_root=workspace_dir,
            )

            self.assertFalse(bool(result.get("success")), result)
            self.assertEqual(result.get("error"), "blocked_command")


if __name__ == "__main__":
    unittest.main()
