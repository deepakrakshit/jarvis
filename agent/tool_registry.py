from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from services.network_service import NetworkService
from services.search_service import SearchService
from services.system.app_control import AppControlService
from services.system.system_service import SystemControlService
from services.weather_service import WeatherService

try:
    from services.document.document_service import DocumentService
except ImportError:
    DocumentService = None  # type: ignore[assignment,misc]

ToolFn = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolDefinition:
    """Tool metadata and callable implementation."""

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: ToolFn
    timeout_seconds: float = 20.0
    safe_to_parallelize: bool = True

    @property
    def parallel_safe(self) -> bool:
        """Backward-compatible alias required by phase-2 executor contract."""
        return self.safe_to_parallelize


class ToolRegistry:
    """Registry for tool lookup, schema metadata, and argument validation."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition by name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        """Return a tool definition by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Return whether a tool is registered."""
        return name in self._tools

    def describe_for_planner(self) -> list[dict[str, Any]]:
        """Return planner-facing metadata for all tools."""
        described: list[dict[str, Any]] = []
        for tool in self._tools.values():
            described.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "parallel_safe": tool.parallel_safe,
                }
            )
        return described

    def validate_args(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Validate arguments against a lightweight JSON-schema-like structure."""
        tool = self.get(tool_name)
        if tool is None:
            return False, "unknown tool"

        schema = tool.input_schema or {}
        required = schema.get("required", [])
        if isinstance(required, list):
            for field_name in required:
                if field_name not in args:
                    return False, f"missing required field '{field_name}'"

        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return True, "ok"

        for field_name, field_schema in properties.items():
            if field_name not in args:
                continue
            if not isinstance(field_schema, dict):
                continue

            expected_type = str(field_schema.get("type") or "").strip().lower()
            if not expected_type:
                continue

            if not self._is_type_match(args[field_name], expected_type):
                return False, f"field '{field_name}' must be {expected_type}"

        return True, "ok"

    @staticmethod
    def _is_type_match(value: Any, expected_type: str) -> bool:
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "array":
            return isinstance(value, list)
        return True


def build_default_tool_registry(
    *,
    network_service: NetworkService,
    weather_service: WeatherService,
    search_service: SearchService,
    document_service: object | None = None,
    memory_store: Any | None = None,
    get_session_location: Callable[[], str | None] | None = None,
    set_session_location: Callable[[str], None] | None = None,
) -> ToolRegistry:
    """Build the default production tool registry for the agent loop."""
    registry = ToolRegistry()
    app_control_service = AppControlService(memory_store=memory_store)
    system_control_service = SystemControlService()

    def _normalize_location(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", (value or "").strip())
        return cleaned.strip(" .,!?;:")

    def _extract_location_from_text(text: str) -> str:
        source = str(text or "")
        patterns = (
            r"\b(?:weather|temperature|forecast)\s+(?:in|at|for)\s+([a-zA-Z][a-zA-Z\s\-]{1,80})",
            r"\b(?:in|at|for)\s+([a-zA-Z][a-zA-Z\s\-]{1,80})",
        )
        for pattern in patterns:
            match = re.search(pattern, source, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = _normalize_location(match.group(1))
            candidate = re.split(r"\b(?:and|also|please|right now|currently)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
            candidate = _normalize_location(candidate)
            if candidate:
                return candidate
        return ""

    def weather_tool(args: dict[str, Any]) -> Any:
        query = str(args.get("query") or "").strip()
        provided_location = _normalize_location(str(args.get("location") or ""))
        query_location = _extract_location_from_text(query)
        session_location = _normalize_location((get_session_location() or "") if get_session_location else "")

        # Priority order for weather requests:
        # 1) explicit location argument from planner/runtime
        # 2) query-provided location phrase
        # 3) session location (user-corrected persistent override)
        # 4) IP fallback in weather service
        effective_location = provided_location or query_location or session_location

        if not effective_location and not query:
            effective_location = "here"
            query = "weather here"

        if query and not effective_location:
            effective_location = "here"

        if effective_location and set_session_location and provided_location:
            # Only persist when the planner/runtime explicitly supplied a location.
            set_session_location(effective_location)

        return weather_service.get_weather_data(
            query=query,
            explicit_location=effective_location,
            session_location=session_location,
            allow_ip_fallback=True,
        )

    def internet_search_tool(args: dict[str, Any]) -> Any:
        query = str(args.get("query") or "").strip()
        max_results = int(args.get("max_results") or 5)
        if not query:
            return {"query": "", "results": [], "error": "missing query"}
        return search_service.search_web_raw(query, max_results=max_results)

    def speedtest_tool(args: dict[str, Any]) -> Any:
        query = str(args.get("query") or "").strip() or "run speed test"
        return network_service.handle_speedtest_query(query)

    def public_ip_tool(_args: dict[str, Any]) -> Any:
        ip = network_service.get_public_ip()
        if not ip:
            return {"ip": "", "error": "public_ip_unavailable"}
        return {"ip": ip, "error": ""}

    def network_location_tool(_args: dict[str, Any]) -> Any:
        return network_service.describe_ip_location()

    def system_status_tool(_args: dict[str, Any]) -> Any:
        return network_service.get_system_status_snapshot()

    def temporal_tool(args: dict[str, Any]) -> Any:
        query = str(args.get("query") or "").strip()
        return network_service.get_temporal_snapshot(query)

    def update_status_tool(_args: dict[str, Any]) -> Any:
        return network_service.get_update_status()

    def app_control_tool(args: dict[str, Any]) -> Any:
        action = str(args.get("action") or "").strip().lower()
        app_name = str(args.get("app_name") or "").strip()
        return app_control_service.control(action=action, app_name=app_name)

    def system_control_tool(args: dict[str, Any]) -> Any:
        action = str(args.get("action") or args.get("command") or args.get("query") or "").strip().lower()
        params = args.get("params")
        safe_params = dict(params) if isinstance(params, dict) else {}
        if not safe_params:
            for key in ("step", "level", "app", "app_name", "actions_in_request"):
                if key in args:
                    safe_params[key] = args.get(key)
        return system_control_service.control(action=action, params=safe_params)

    registry.register(
        ToolDefinition(
            name="weather",
            description="Fetch current weather details for a location or local context.",
            input_schema={
                "type": "object",
                "required": ["location"],
                "properties": {
                    "query": {"type": "string"},
                    "location": {"type": "string"},
                },
            },
            fn=weather_tool,
            timeout_seconds=20.0,
            safe_to_parallelize=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="internet_search",
            description="Fetch raw web search results (title, snippet, link) for factual, news, and internet lookup queries.",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
            },
            fn=internet_search_tool,
            timeout_seconds=20.0,
            safe_to_parallelize=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="speedtest",
            description="Run speedtest command or fetch latest speedtest result.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
            },
            fn=speedtest_tool,
            timeout_seconds=90.0,
            safe_to_parallelize=False,
        )
    )

    registry.register(
        ToolDefinition(
            name="public_ip",
            description="Get current public IP address.",
            input_schema={"type": "object", "properties": {}},
            fn=public_ip_tool,
            timeout_seconds=10.0,
            safe_to_parallelize=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="network_location",
            description="Resolve approximate location from current public IP.",
            input_schema={"type": "object", "properties": {}},
            fn=network_location_tool,
            timeout_seconds=12.0,
            safe_to_parallelize=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="system_status",
            description="Get CPU, RAM, uptime, and current clock snapshot.",
            input_schema={"type": "object", "properties": {}},
            fn=system_status_tool,
            timeout_seconds=8.0,
            safe_to_parallelize=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="temporal",
            description="Get current local time and date snapshot.",
            input_schema={"type": "object", "properties": {}},
            fn=temporal_tool,
            timeout_seconds=8.0,
            safe_to_parallelize=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="update_status",
            description="Get current software update status for Jarvis build.",
            input_schema={"type": "object", "properties": {}},
            fn=update_status_tool,
            timeout_seconds=8.0,
            safe_to_parallelize=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="app_control",
            description=(
                "Control desktop applications deterministically. "
                "Supports open and close actions with OS-level verification."
            ),
            input_schema={
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string"},
                    "app_name": {"type": "string"},
                },
            },
            fn=app_control_tool,
            timeout_seconds=35.0,
            safe_to_parallelize=False,
        )
    )

    registry.register(
        ToolDefinition(
            name="system_control",
            description=(
                "Deterministic operating-system controls with strict validation and safety policy. "
                "Supports volume, brightness, window, desktop, and safe system actions."
            ),
            input_schema={
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string"},
                    "params": {"type": "object"},
                },
            },
            fn=system_control_tool,
            timeout_seconds=20.0,
            safe_to_parallelize=False,
        )
    )

    # ── Document Tool ───────────────────────────────────────────────────
    if document_service is not None and DocumentService is not None:
        _doc_service = document_service

        def document_tool(args: dict[str, Any]) -> Any:
            file_path = str(args.get("file_path") or "").strip()
            query = str(args.get("query") or "").strip()
            if not file_path:
                return {
                    "success": False,
                    "error": "No file path provided. The system must select a file first.",
                    "requires_file": True,
                }
            return _doc_service.analyze(file_path, user_query=query)

        registry.register(
            ToolDefinition(
                name="document",
                description="Analyze a document (PDF, DOCX, or image). Extracts content, produces structured summary, insights, key points, and tables.",
                input_schema={
                    "type": "object",
                    "required": ["file_path"],
                    "properties": {
                        "file_path": {"type": "string"},
                        "query": {"type": "string"},
                    },
                },
                fn=document_tool,
                timeout_seconds=180.0,
                safe_to_parallelize=False,
            )
        )

    return registry
