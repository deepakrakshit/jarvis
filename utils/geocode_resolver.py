from __future__ import annotations

import re
from typing import Any

from services.utils.http_client import HttpClient
from services.utils.location_utils import LocationInfo


_MAJOR_REGION_HINTS: dict[str, str] = {
    "florida": "united states",
    "new york": "united states",
    "california": "united states",
    "texas": "united states",
    "delhi": "india",
    "mumbai": "india",
    "bengaluru": "india",
    "bangalore": "india",
    "london": "united kingdom",
    "paris": "france",
}

_MAJOR_COUNTRIES = {
    "india",
    "united states",
    "united kingdom",
    "canada",
    "australia",
    "germany",
    "france",
    "japan",
}

_COUNTRY_ALIASES = {
    "us": "united states",
    "usa": "united states",
    "uk": "united kingdom",
    "uae": "united arab emirates",
}


def _normalized(value: str) -> str:
    lowered = (value or "").strip().lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return _COUNTRY_ALIASES.get(lowered, lowered)


def _extract_country_hint(query: str) -> str | None:
    match = re.search(r"\b(?:in|for|at)\s+([a-zA-Z\s]{2,40})$", query or "", flags=re.IGNORECASE)
    if not match:
        return None
    tail = _normalized(match.group(1))
    if len(tail.split()) > 4:
        return None
    return tail


def _score_result(
    result: dict[str, Any],
    *,
    query_city: str,
    user_country: str | None,
    query_country_hint: str | None,
) -> float:
    score = 0.0

    city = _normalized(str(result.get("name") or ""))
    region = _normalized(str(result.get("admin1") or ""))
    country = _normalized(str(result.get("country") or ""))
    population = float(result.get("population") or 0)

    query_normalized = _normalized(query_city)
    if city == query_normalized:
        score += 180
    elif city.startswith(query_normalized):
        score += 120
    elif query_normalized in city:
        score += 70

    if region == query_normalized:
        score += 85

    if user_country and country == user_country:
        score += 150

    if query_country_hint and country == query_country_hint:
        score += 160

    if country in _MAJOR_COUNTRIES:
        score += 25

    hinted_country = _MAJOR_REGION_HINTS.get(query_normalized)
    if hinted_country and country == hinted_country:
        score += 200

    if population > 0:
        score += min(120.0, population / 150000.0)

    return score


def resolve_geocode(
    http: HttpClient,
    city_name: str,
    *,
    user_country: str | None = None,
    query: str = "",
) -> LocationInfo | None:
    """Resolve city geocoding with ranked Open-Meteo candidates."""
    payload = http.get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": city_name,
            "count": 3,
            "language": "en",
            "format": "json",
        },
    )
    if not payload:
        return None

    records = payload.get("results")
    if not isinstance(records, list) or not records:
        return None

    normalized_user_country = _normalized(user_country or "") or None
    query_country_hint = _extract_country_hint(query)

    ranked = sorted(
        records,
        key=lambda item: _score_result(
            item,
            query_city=city_name,
            user_country=normalized_user_country,
            query_country_hint=query_country_hint,
        ),
        reverse=True,
    )

    best = ranked[0]
    try:
        return LocationInfo(
            city=str(best.get("name") or city_name),
            region=str(best.get("admin1") or ""),
            country=str(best.get("country") or ""),
            latitude=float(best.get("latitude")),
            longitude=float(best.get("longitude")),
            timezone=str(best.get("timezone") or ""),
            source="open-meteo-geocoding-ranked",
        )
    except Exception:
        return None
