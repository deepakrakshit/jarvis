from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(order=True)
class IntentRoute:
    priority: int
    name: str = field(compare=False)
    matcher: Callable[[str], bool] = field(compare=False)
    handler: Callable[[str], str] = field(compare=False)


@dataclass(frozen=True)
class IntentDispatchResult:
    name: str
    response: str


class IntentRouter:
    """Simple priority-based intent router for local service features."""

    def __init__(self) -> None:
        self._routes: list[IntentRoute] = []

    def register(
        self,
        *,
        name: str,
        matcher: Callable[[str], bool],
        handler: Callable[[str], str],
        priority: int,
    ) -> None:
        self._routes.append(
            IntentRoute(
                priority=priority,
                name=name,
                matcher=matcher,
                handler=handler,
            )
        )
        self._routes.sort()

    def dispatch_result(self, text: str) -> IntentDispatchResult | None:
        query = (text or "").strip()
        if not query:
            return None

        for route in self._routes:
            if route.matcher(query):
                return IntentDispatchResult(name=route.name, response=route.handler(query))

        return None

    def dispatch(self, text: str) -> str | None:
        result = self.dispatch_result(text)
        if result:
            return result.response

        return None
