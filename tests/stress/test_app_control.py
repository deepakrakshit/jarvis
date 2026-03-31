from __future__ import annotations

import unittest
from unittest.mock import patch

from services.system.app_control import AppControlService, AppExecutor, AppRecord, AppResolver


class _MemoryStub:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


class _ExecutorStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def execute(self, *, action: str, app_name: str) -> dict[str, object]:
        self.calls.append((action, app_name))
        return {
            "status": "success",
            "action": action,
            "app": app_name,
            "verified": True,
            "confidence": 95.0,
        }


class _ResolvedNoFuzzyResolver:
    @property
    def fuzzy_available(self) -> bool:
        return False

    def resolve(self, _app_name: str):
        record = AppRecord(name="Visual Studio Code", app_id="", process_hints=("code",), source="canonical")
        return AppResolver(start_apps_loader=lambda: [])._decide("code", [(96.0, record)])


class AppControlStressTest(unittest.TestCase):
    def test_alias_resolution_auto_executes_with_high_confidence(self) -> None:
        resolver = AppResolver(
            start_apps_loader=lambda: [
                AppRecord(
                    name="Google Chrome",
                    app_id="Chrome",
                    process_hints=("chrome",),
                    source="start_apps",
                )
            ]
        )

        decision = resolver.resolve("browser")

        self.assertEqual(decision.status, "resolved")
        self.assertIsNotNone(decision.match)
        self.assertGreater(decision.confidence, 85.0)

    def test_file_explorer_alias_resolves_to_explorer(self) -> None:
        resolver = AppResolver(
            start_apps_loader=lambda: [
                AppRecord(
                    name="File Explorer",
                    app_id="Microsoft.Windows.Explorer",
                    process_hints=("explorer",),
                    source="start_apps",
                )
            ]
        )

        decision = resolver.resolve("file manager")

        self.assertEqual(decision.status, "resolved")
        self.assertIsNotNone(decision.match)
        assert decision.match is not None
        self.assertIn("explorer", decision.match.process_hints)

    def test_vscode_resolution_includes_code_process_hint(self) -> None:
        resolver = AppResolver(
            start_apps_loader=lambda: [
                AppRecord(
                    name="Visual Studio Code",
                    app_id="Microsoft.VisualStudioCode",
                    process_hints=("visualstudiocode", "visual", "studio"),
                    source="start_apps",
                )
            ]
        )

        decision = resolver.resolve("vscode")

        self.assertEqual(decision.status, "resolved")
        self.assertIsNotNone(decision.match)
        assert decision.match is not None
        self.assertIn("code", decision.match.process_hints)

    def test_ambiguous_and_not_found_thresholds(self) -> None:
        resolver = AppResolver(start_apps_loader=lambda: [])

        ambiguous = resolver._decide(
            "code",
            [
                (
                    81.0,
                    AppRecord(name="Visual Studio", app_id="VS", process_hints=("devenv",), source="start_apps"),
                ),
                (
                    73.0,
                    AppRecord(name="Visual Studio Code", app_id="Code", process_hints=("code",), source="start_apps"),
                ),
            ],
        )
        not_found = resolver._decide(
            "unknown",
            [
                (
                    61.0,
                    AppRecord(name="Calculator", app_id="Calc", process_hints=("calculator",), source="start_apps"),
                )
            ],
        )

        self.assertEqual(ambiguous.status, "ambiguous")
        self.assertLessEqual(len(ambiguous.candidates), 5)
        self.assertEqual(not_found.status, "not_found")

    def test_open_requires_verification(self) -> None:
        resolver = AppResolver(start_apps_loader=lambda: [])
        executor = AppExecutor(resolver)

        with patch.object(
            resolver,
            "resolve",
            return_value=resolver._decide(
                "chrome",
                [
                    (
                        98.0,
                        AppRecord(name="chrome", app_id="", process_hints=("chrome",), source="canonical"),
                    )
                ],
            ),
        ), patch("services.system.app_control.os.name", "nt"), patch("services.system.app_control.psutil", object()), patch.object(
            executor,
            "_snapshot_matching_pids",
            return_value=set(),
        ), patch.object(
            executor,
            "_launch_app",
            return_value=True,
        ), patch.object(executor, "_wait_for_open_verification", return_value=False):
            result = executor.execute(action="open", app_name="chrome")

        self.assertEqual(result.get("status"), "error")
        self.assertEqual(result.get("reason"), "execution_failed")

    def test_compact_process_matching_handles_hyphenated_names(self) -> None:
        resolver = AppResolver(start_apps_loader=lambda: [])
        executor = AppExecutor(resolver)

        matched = executor._matches_any_hint("anaconda-navigator", {"anacondanavigator"})
        self.assertTrue(matched)

    def test_short_hint_does_not_match_unrelated_process(self) -> None:
        resolver = AppResolver(start_apps_loader=lambda: [])
        executor = AppExecutor(resolver)

        matched = executor._matches_any_hint("vscodehelper", {"code"})
        self.assertFalse(matched)

    def test_non_fuzzy_fallback_can_resolve_exact_name(self) -> None:
        resolver = AppResolver(
            start_apps_loader=lambda: [
                AppRecord(
                    name="Visual Studio Code",
                    app_id="Microsoft.VisualStudioCode",
                    process_hints=("code",),
                    source="start_apps",
                )
            ]
        )

        with patch("services.system.app_control.process", None), patch("services.system.app_control.fuzz", None):
            decision = resolver.resolve("visual studio code")

        self.assertEqual(decision.status, "resolved")
        self.assertGreater(decision.confidence, 85.0)

    def test_executor_does_not_fail_when_fuzzy_is_unavailable(self) -> None:
        executor = AppExecutor(_ResolvedNoFuzzyResolver())  # type: ignore[arg-type]

        with patch("services.system.app_control.os.name", "nt"), patch("services.system.app_control.psutil", object()), patch.object(
            executor,
            "_open_app",
            return_value={
                "status": "success",
                "action": "open",
                "app": "Visual Studio Code",
                "verified": True,
                "confidence": 96.0,
            },
        ):
            result = executor.execute(action="open", app_name="vscode")

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("action"), "open")

    def test_close_it_uses_remembered_app(self) -> None:
        memory = _MemoryStub()
        exec_stub = _ExecutorStub()
        service = AppControlService(memory_store=memory, executor=exec_stub)

        open_result = service.control(action="open", app_name="chrome")
        close_result = service.control(action="close", app_name="it")

        self.assertEqual(open_result.get("status"), "success")
        self.assertEqual(close_result.get("status"), "success")
        self.assertEqual(exec_stub.calls[1], ("close", "chrome"))

    def test_close_it_without_memory_returns_not_found(self) -> None:
        service = AppControlService(memory_store=_MemoryStub(), executor=_ExecutorStub())
        result = service.control(action="close", app_name="it")
        self.assertEqual(result.get("status"), "error")
        self.assertEqual(result.get("reason"), "not_found")


if __name__ == "__main__":
    unittest.main()
