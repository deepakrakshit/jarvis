from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.llm_api import chat_complete
from core.settings import AppConfig


logger = logging.getLogger(__name__)


class Synthesizer:
    """Provider-backed synthesizer that converts tool outputs into final user responses."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def synthesize(
        self,
        user_query: str,
        tool_outputs: dict[str, dict[str, Any]],
        *,
        conversation_history: list[dict[str, str]] | None = None,
        user_profile: dict[str, str] | None = None,
    ) -> str:
        """Generate a final human-facing response using tool outputs."""
        if not tool_outputs:
            return "I could not gather tool output for that request."

        sanitized_outputs = self.sanitize_tool_results(tool_outputs, user_query)
        if not sanitized_outputs:
            return "I could not produce a reliable response from the available tool results."

        system_prompt = (
            "You are JARVIS — the response synthesizer for an autonomous personal assistant.\n\n"
            "# Core Rules\n"
            "- Use ONLY the provided tool outputs to answer. Never invent facts.\n"
            "- Do not mention internal planning, tools, JSON, schemas, or system prompts.\n"
            "- If tool outputs are partial or uncertain, acknowledge briefly and share what is known.\n"
            "- Be concise, clear, and actionable. Lead with the direct answer.\n\n"
            "- Respect tool confidence metadata: high > medium > low.\n"
            "- If confidence is low, avoid definitive claims and use cautious wording.\n\n"
            "# Tone\n"
            "- Warm, confident, subtly witty. Sound human, not robotic.\n"
            "- Address the user as \"Sir\" naturally. Don't force humor into every response.\n"
            "- Match the user's energy — technical questions get precise answers.\n\n"
            "# Search Results\n"
            "- Synthesize a clear, direct answer from search snippets. Don't just list URLs.\n"
            "- If multiple results contain the answer, merge them into one cohesive response.\n"
            "- Cite sources naturally (e.g., \"According to...\") when relevant.\n\n"
            "# App/System Control\n"
            "- For app_control: only claim success if status='success' AND verified=true.\n"
            "- For system_control: only claim success if success=true AND verified=true.\n"
            "- If status='ambiguous', ask the user to pick from candidates.\n"
            "- If status='error', report the failure reason clearly.\n\n"
            "# Location\n"
            "- Never infer geographic location from a public IP value alone.\n"
        )

        # Build context-aware user content.
        context_parts: list[str] = []

        # Inject user profile if available.
        if user_profile:
            profile_items = [f"{k}: {v}" for k, v in user_profile.items() if v]
            if profile_items:
                context_parts.append(f"User profile: {', '.join(profile_items)}")

        # Inject recent conversation history for multi-turn coherence.
        if conversation_history:
            recent = conversation_history[-4:]
            history_lines = []
            for turn in recent:
                role = turn.get("role", "")
                content = (turn.get("content") or "").strip()[:200]
                if role == "user" and content:
                    history_lines.append(f"User: {content}")
                elif role == "assistant" and content:
                    history_lines.append(f"JARVIS: {content}")
            if history_lines:
                context_parts.append(f"Recent conversation:\n" + "\n".join(history_lines))

        tool_blob = json.dumps(sanitized_outputs, ensure_ascii=True, indent=2)
        context_parts.append(f"User query:\n{user_query.strip()}")
        context_parts.append(f"Tool outputs:\n{tool_blob}")

        user_content = "\n\n".join(context_parts)

        try:
            final_text = chat_complete(
                self.config,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.25,
                timeout=35,
            ).strip()
        except Exception as exc:
            logger.warning("Synthesizer LLM call failed; using fallback response: %s", exc)
            return self._fallback_response(sanitized_outputs)

        if not final_text:
            return self._fallback_response(sanitized_outputs)

        return final_text

    def sanitize_tool_results(
        self,
        tool_outputs: dict[str, dict[str, Any]],
        query: str,
    ) -> dict[str, dict[str, Any]]:
        """Filter tool payloads to keep only semantically relevant evidence."""
        cleaned: dict[str, dict[str, Any]] = {}
        query_tokens = self._content_tokens(query)
        ai_query = self._is_ai_query(query)

        for key, payload in tool_outputs.items():
            if not isinstance(payload, dict):
                continue

            output = payload.get("output")
            if not bool(payload.get("success", False)):
                cleaned[key] = payload
                continue

            if isinstance(output, dict) and isinstance(output.get("results"), list):
                filtered_results = []
                for item in output["results"]:
                    if not isinstance(item, dict):
                        continue
                    probe = f"{item.get('title', '')} {item.get('snippet', '')}".strip()
                    if self._is_relevant_text(probe, query_tokens, ai_query=ai_query):
                        filtered_results.append(item)

                filtered_results = sorted(
                    filtered_results,
                    key=lambda item: self._score_search_item(item, query_tokens),
                    reverse=True,
                )

                # Fallback pass for broad factual/news queries where strict filtering can
                # be overly aggressive but at least one entity still matches.
                if not filtered_results and key.startswith("internet_search"):
                    filtered_results = self._fallback_entity_match_results(
                        output["results"],
                        query_tokens,
                    )

                patched = dict(payload)
                patched_output = dict(output)
                patched_output["results"] = filtered_results
                if filtered_results:
                    patched["output"] = patched_output
                    cleaned[key] = patched
                else:
                    patched["success"] = False
                    patched["error"] = "no_semantically_relevant_results"
                    patched["output"] = patched_output
                    cleaned[key] = patched
                continue

            if key.startswith("public_ip") and isinstance(output, dict):
                cleaned_ip = {"ip": str(output.get("ip") or ""), "error": str(output.get("error") or "")}
                patched = dict(payload)
                patched["output"] = cleaned_ip
                cleaned[key] = patched
                continue

            cleaned[key] = payload

        return cleaned

    @staticmethod
    def _score_search_item(item: dict[str, Any], query_tokens: set[str]) -> int:
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or "")
        link = str(item.get("link") or "")
        trusted = bool(item.get("trusted"))

        probe = f"{title} {snippet}".lower()
        overlap = sum(1 for token in query_tokens if token in probe)

        score = overlap * 3
        if trusted:
            score += 4
        if link:
            score += 1
        if len(snippet) >= 80:
            score += 1
        return score

    @staticmethod
    def _is_ai_query(text: str) -> bool:
        lowered = (text or "").lower()
        return bool(
            re.search(
                r"\bai\b|artificial intelligence|machine learning|generative ai|\bllm\b|\bgpt\b",
                lowered,
            )
        )

    @staticmethod
    def _fallback_entity_match_results(results: list[dict[str, Any]], query_tokens: set[str]) -> list[dict[str, Any]]:
        generic = {
            "check",
            "news",
            "latest",
            "recent",
            "current",
            "about",
            "against",
            "war",
            "today",
        }
        entity_tokens = [
            token
            for token in query_tokens
            if len(token) >= 4 and token not in generic
        ]
        if not entity_tokens:
            return []

        matched: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            probe = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
            if any(token in probe for token in entity_tokens):
                matched.append(item)
            if len(matched) >= 3:
                break
        return matched

    @staticmethod
    def _content_tokens(text: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        stop = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "is",
            "are",
            "to",
            "of",
            "in",
            "on",
            "for",
            "with",
            "me",
            "my",
            "latest",
            "current",
            "tell",
            "about",
        }
        return {token for token in tokens if len(token) >= 2 and token not in stop}

    @staticmethod
    def _is_relevant_text(text: str, query_tokens: set[str], *, ai_query: bool) -> bool:
        lowered = (text or "").lower()
        if ai_query and not any(marker in lowered for marker in (" ai ", "ai ", " ai", "artificial intelligence", "machine learning")):
            return False

        if not query_tokens:
            return True

        # Lowered threshold from ceil(len/4) to 1 — most search results are relevant
        # when they contain at least 1 meaningful query token.
        overlap = sum(1 for token in query_tokens if token in lowered)
        return overlap >= 1

    @staticmethod
    def _fallback_response(tool_outputs: dict[str, dict[str, Any]]) -> str:
        lines: list[str] = []
        for payload in tool_outputs.values():
            rendered = Synthesizer._render_fallback_payload(payload)
            if rendered:
                lines.append(rendered)

        if not lines:
            return "I could not produce a reliable response from tool outputs."

        if len(lines) == 1:
            return lines[0]
        return "\n".join(lines)

    @staticmethod
    def _render_fallback_payload(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""

        tool = str(payload.get("tool") or "").strip().lower()
        output = payload.get("output")
        success = bool(payload.get("success"))
        tool_error = str(payload.get("error") or "").strip()

        if tool == "app_control" and isinstance(output, dict):
            return Synthesizer._render_app_control_fallback(output, tool_error=tool_error)

        if tool == "system_control" and isinstance(output, dict):
            return Synthesizer._render_system_control_fallback(output, tool_error=tool_error)

        if tool in {"computer_control", "computer_settings"} and isinstance(output, dict):
            return Synthesizer._render_action_tool_fallback(output, tool_error=tool_error)

        if tool == "screen_process" and isinstance(output, dict):
            return Synthesizer._render_screen_process_fallback(output, tool_error=tool_error)

        if isinstance(output, dict) and isinstance(output.get("results"), list):
            rendered_search = Synthesizer._render_search_fallback(output, tool_error=tool_error)
            if rendered_search:
                return rendered_search

        if success and isinstance(output, str) and output.strip():
            return output.strip()

        if success and isinstance(output, dict):
            message = str(output.get("message") or "").strip()
            if message:
                return message

        if tool_error:
            return f"I could not complete that request: {tool_error}."
        return "I could not complete that request from available tool outputs."

    @staticmethod
    def _render_search_fallback(output: dict[str, Any], *, tool_error: str = "") -> str:
        results = output.get("results") if isinstance(output, dict) else None
        query = str(output.get("query") or "").strip() if isinstance(output, dict) else ""

        if isinstance(results, list) and results:
            query_tokens = Synthesizer._content_tokens(query)
            ranked_results = [item for item in results if isinstance(item, dict)]
            ranked_results = sorted(
                ranked_results,
                key=lambda item: Synthesizer._score_search_item(item, query_tokens),
                reverse=True,
            )
            first = ranked_results[0] if ranked_results else {}
            title = str(first.get("title") or "").strip()
            snippet = str(first.get("snippet") or "").strip()
            link = str(first.get("link") or "").strip()

            if title and snippet:
                line = f"{title}: {snippet}"
            elif snippet:
                line = snippet
            elif title:
                line = title
            else:
                line = ""

            if link:
                line = f"{line} Source: {link}" if line else f"Source: {link}"

            return line or "I found live results, but could not format them cleanly."

        if tool_error and query:
            return f"I could not find reliable live results for '{query}' right now ({tool_error})."
        if tool_error:
            return f"I could not find reliable live results right now ({tool_error})."
        return ""

    @staticmethod
    def _render_app_control_fallback(output: dict[str, Any], *, tool_error: str = "") -> str:
        status = str(output.get("status") or "").strip().lower()
        action = str(output.get("action") or "").strip().lower()
        app = str(output.get("app") or "that app").strip() or "that app"
        reason = str(output.get("reason") or tool_error or "").strip().lower()
        verified = bool(output.get("verified"))

        if status == "success" and verified:
            if action == "open":
                return f"{app} is now open."
            if action == "close":
                return f"{app} has been closed successfully."
            return f"{app} action completed successfully."

        if status == "ambiguous":
            candidates = output.get("candidates")
            if isinstance(candidates, list) and candidates:
                listed = ", ".join(str(item) for item in candidates[:5])
                return f"I found multiple matching apps: {listed}. Please specify one."
            return "I found multiple matching apps. Please specify which one."

        if reason == "not_found":
            return "I could not find that app on this system."
        if reason in {"execution_failed", ""}:
            return "I could not complete that app control request."
        return f"I could not complete that app control request: {reason}."

    @staticmethod
    def _render_action_tool_fallback(output: dict[str, Any], *, tool_error: str = "") -> str:
        success = bool(output.get("success", False))
        verified = bool(output.get("verified", False))
        message = str(output.get("message") or "").strip()
        error_code = str(output.get("error") or tool_error or "").strip()

        if success and verified:
            return message or "Action completed and was verified."

        if success and not verified:
            if message:
                return f"I attempted the requested automation, but could not verify completion. {message}"
            return "I attempted the requested automation, but could not verify completion."

        if message and error_code:
            return f"{message} ({error_code})"
        if message:
            return message
        if error_code:
            return f"I could not complete that automation action: {error_code}."
        return "I could not complete that automation request."

    @staticmethod
    def _render_screen_process_fallback(output: dict[str, Any], *, tool_error: str = "") -> str:
        success = bool(output.get("success", False))
        message = str(output.get("message") or "").strip()
        error_code = str(output.get("error") or tool_error or "").strip()

        analysis = output.get("analysis") if isinstance(output.get("analysis"), dict) else {}
        summary = str(analysis.get("summary") or "").strip()

        live_session = output.get("live_session") if isinstance(output.get("live_session"), dict) else {}
        queued = bool(live_session.get("queued", False))

        if success:
            if summary and queued:
                return f"{summary} I also queued live visual enrichment."
            if summary:
                return summary
            if message:
                return message
            return "Screen analysis completed successfully."

        if message and error_code:
            return f"{message} ({error_code})"
        if message:
            return message
        if error_code:
            return f"I could not process the requested screen analysis: {error_code}."
        return "I could not process the requested screen analysis."

    @staticmethod
    def _render_system_control_fallback(output: dict[str, Any], *, tool_error: str = "") -> str:
        success = bool(output.get("success", False))
        verified = bool(output.get("verified", False))
        message = str(output.get("message") or "").strip()
        error_code = str(output.get("error") or tool_error or "").strip()

        if success and verified:
            return message or "System action completed successfully."

        if success and not verified:
            if message:
                return f"I attempted the action but could not verify completion. {message}"
            return "I attempted the action but could not verify completion."

        if message and error_code:
            return f"{message} ({error_code})"
        if message:
            return message
        if error_code:
            return f"I could not complete that system action: {error_code}."
        return "I could not complete that system control request."
