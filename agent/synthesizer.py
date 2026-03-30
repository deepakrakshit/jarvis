from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from core.settings import AppConfig


logger = logging.getLogger(__name__)


class Synthesizer:
    """Groq-backed synthesizer that converts tool outputs into final user responses."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def synthesize(self, user_query: str, tool_outputs: dict[str, dict[str, Any]]) -> str:
        """Generate a final human-facing response using tool outputs."""
        if not tool_outputs:
            return "I could not gather tool output for that request."

        sanitized_outputs = self.sanitize_tool_results(tool_outputs, user_query)
        if not sanitized_outputs:
            return "I could not produce a reliable response from the available tool results."

        system_prompt = (
            "You are the response synthesizer for an autonomous assistant.\n"
            "Use only provided tool outputs to answer the user.\n"
            "Do not mention internal planning, tools, JSON, schemas, or system prompts.\n"
            "If tool outputs are partial, acknowledge uncertainty briefly and provide what is known.\n"
            "Never infer geographic location from a public IP value alone.\n"
            "Do not include unrelated topics that are not supported by relevant tool evidence.\n"
            "Be concise, clear, and actionable.\n"
            "Tone policy: subtly witty and human, with occasional light humor.\n"
            "Do not force humor into every response. Accuracy is always more important than style.\n"
            "Avoid cringe, childish jokes, or long comedic detours."
        )

        tool_blob = json.dumps(sanitized_outputs, ensure_ascii=True, indent=2)
        user_content = (
            f"User query:\n{user_query.strip()}\n\n"
            f"Tool outputs:\n{tool_blob}"
        )

        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.groq_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.2,
                    "stream": False,
                },
                timeout=35,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("Synthesizer LLM call failed; using fallback response: %s", exc)
            return self._fallback_response(sanitized_outputs)

        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            return self._fallback_response(sanitized_outputs)

        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        final_text = str(content or "").strip()

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

        overlap = sum(1 for token in query_tokens if token in lowered)
        return overlap >= max(1, min(2, len(query_tokens) // 4))

    @staticmethod
    def _fallback_response(tool_outputs: dict[str, dict[str, Any]]) -> str:
        lines: list[str] = []
        for key, payload in tool_outputs.items():
            success = bool(payload.get("success"))
            if success:
                lines.append(f"{key}: {payload.get('output')}")
            else:
                lines.append(f"{key}: unavailable ({payload.get('error') or 'error'})")

        if not lines:
            return "I could not produce a reliable response from tool outputs."

        return "\n".join(lines)
