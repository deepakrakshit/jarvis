from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from core.runtime import JarvisRuntime


class _FakeDocumentService:
    def has_active_documents(self) -> bool:
        return True

    def active_document_names(self) -> list[str]:
        return ["A.pdf", "B.pdf"]


class _FakeTTS:
    def __init__(self) -> None:
        self.turn_id = 0

    def interrupt(self) -> int:
        self.turn_id += 1
        return self.turn_id


class _FakeResponse:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RuntimeInteractionFlowsTest(unittest.TestCase):
    def _runtime_for_compare(self) -> JarvisRuntime:
        runtime = object.__new__(JarvisRuntime)
        runtime.document_service = _FakeDocumentService()
        runtime._last_fact_source = ""
        runtime._is_factual_query = lambda _text: False  # type: ignore[assignment]
        return runtime

    def _runtime_minimal(self) -> JarvisRuntime:
        runtime = object.__new__(JarvisRuntime)
        runtime.document_service = None
        runtime._last_search_query = ""
        runtime._last_fact_source = ""
        return runtime

    def test_compare_the_two_documents_uses_file_picker_flow(self) -> None:
        runtime = self._runtime_for_compare()

        self.assertFalse(runtime._is_document_question_request("compare the 2 documents"))
        self.assertFalse(runtime._is_document_question_request("compare these two files for pricing"))
        self.assertTrue(runtime._is_document_question_request("compare documents"))

    def test_file_manager_phrases_do_not_trigger_document_picker(self) -> None:
        runtime = self._runtime_for_compare()

        self.assertFalse(runtime._is_document_request("open file explorer"))
        self.assertFalse(runtime._is_document_request("open file manager"))

    def test_explicit_picker_phrases_trigger_document_picker(self) -> None:
        runtime = self._runtime_for_compare()

        self.assertTrue(runtime._is_document_request("open file picker"))
        self.assertTrue(runtime._is_document_request("open document selector"))

    def test_location_declaration_only_matcher(self) -> None:
        runtime = self._runtime_minimal()

        self.assertTrue(runtime._is_location_declaration_only("i am in greater noida"))
        self.assertFalse(runtime._is_location_declaration_only("i am in greater noida weather?"))
        self.assertEqual(runtime._extract_declared_location("i am in greater noida"), "greater noida")

    def test_search_or_factual_matcher_handles_ipl_query(self) -> None:
        runtime = self._runtime_minimal()

        self.assertTrue(runtime._is_search_or_factual_request("who won ipl 2025 season"))
        self.assertFalse(runtime._is_search_or_factual_request("what is my ip"))

    def test_browser_navigation_phrase_not_treated_as_factual_search(self) -> None:
        runtime = self._runtime_minimal()

        prompt = "open chrome and search on youtube about python tutorials"
        self.assertTrue(runtime._is_browser_navigation_request(prompt))
        self.assertFalse(runtime._is_search_or_factual_request(prompt))

    def test_connectivity_phrase_not_treated_as_search_policy_feedback(self) -> None:
        runtime = self._runtime_minimal()

        self.assertFalse(runtime._is_search_policy_feedback("check internet connectivity"))

    def test_explicit_good_afternoon_greeting_keeps_user_period(self) -> None:
        runtime = self._runtime_minimal()

        reply = runtime._handle_greeting("good afternoon")

        self.assertIn("Good afternoon", reply)

    def test_extract_ipl_winner_answer_from_search_snippets(self) -> None:
        runtime = self._runtime_minimal()
        results = [
            {
                "title": "IPL 2025 Final, PBKS vs RCB Highlights: RCB won",
                "snippet": "Royal Challengers Bengaluru defeated Punjab Kings in the IPL 2025 final.",
            },
            {
                "title": "Match report",
                "snippet": "RCB lifted the trophy after winning the title.",
            },
        ]

        answer = runtime._extract_ipl_winner_answer("who won ipl 2025 season", results)

        self.assertIn("Royal Challengers Bengaluru", answer)
        self.assertIn("IPL 2025", answer)

    def test_skip_cancels_active_turn_and_forces_listening_mode(self) -> None:
        runtime = object.__new__(JarvisRuntime)
        runtime.tts = _FakeTTS()
        runtime._cancel_event = threading.Event()
        runtime._stream_response_lock = threading.Lock()

        active_response = _FakeResponse()
        runtime._active_stream_response = active_response

        runtime._api_active = True
        runtime._on_mode_change = None
        runtime._on_text_delta = None
        mode_events: list[str] = []
        api_events: list[bool] = []
        runtime._on_mode_change = lambda mode: mode_events.append(mode)
        runtime._on_api_activity = lambda active: api_events.append(bool(active))

        result = runtime.skip_current_reply()

        self.assertTrue(bool(result.get("skipped")))
        self.assertTrue(bool(result.get("cancel_requested")))
        self.assertTrue(runtime._cancel_event.is_set())
        self.assertFalse(runtime._api_active)
        self.assertTrue(active_response.closed)
        self.assertIsNone(runtime._active_stream_response)
        self.assertIn("listening", mode_events)
        self.assertIn(False, api_events)

    def test_document_picker_disables_cli_fallback_in_desktop_mode(self) -> None:
        runtime = object.__new__(JarvisRuntime)
        runtime.document_service = _FakeDocumentService()
        runtime._on_mode_change = lambda _mode: None
        runtime._on_text_delta = lambda _delta: None
        runtime._on_api_activity = lambda _active: None

        with patch("services.document.file_selector.select_files", return_value=None) as select_files_mock:
            response = runtime._handle_document("open document")

        self.assertIn("No document was selected", response)
        self.assertFalse(bool(select_files_mock.call_args.kwargs.get("allow_cli_fallback")))

    def test_document_picker_keeps_cli_fallback_in_cli_mode(self) -> None:
        runtime = object.__new__(JarvisRuntime)
        runtime.document_service = _FakeDocumentService()
        runtime._on_mode_change = None
        runtime._on_text_delta = None
        runtime._on_api_activity = None

        with patch("services.document.file_selector.select_files", return_value=None) as select_files_mock:
            response = runtime._handle_document("open document")

        self.assertIn("No document was selected", response)
        self.assertTrue(bool(select_files_mock.call_args.kwargs.get("allow_cli_fallback")))


if __name__ == "__main__":
    unittest.main()
