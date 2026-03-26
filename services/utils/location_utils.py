from __future__ import annotations

from dataclasses import dataclass

from services.utils.http_client import HttpClient


@dataclass(frozen=True)
class LocationInfo:
    city: str
    region: str
    country: str
    latitude: float
    longitude: float
    timezone: str
    source: str
    ip: str = ""

    @property
    def label(self) -> str:
        parts = [self.city, self.region, self.country]
        return ", ".join(part for part in parts if part)


def geocode_city_open_meteo(http: HttpClient, city_name: str) -> LocationInfo | None:
    payload = http.get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": city_name,
            "count": 1,
            "language": "en",
            "format": "json",
        },
    )
    if not payload:
        return None

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None

    first = results[0]
    try:
        return LocationInfo(
            city=str(first.get("name") or city_name),
            region=str(first.get("admin1") or ""),
            country=str(first.get("country") or ""),
            latitude=float(first.get("latitude")),
            longitude=float(first.get("longitude")),
            timezone=str(first.get("timezone") or ""),
            source="open-meteo-geocoding",
        )
    except Exception:
        return None


def _ip_location_from_ip_api(http: HttpClient, ip: str | None = None) -> LocationInfo | None:
    target = ip.strip() if ip else ""
    url = f"http://ip-api.com/json/{target}"
    payload = http.get_json(
        url,
        params={
            "fields": "status,message,country,regionName,city,lat,lon,timezone,query",
        },
    )
    if not payload or payload.get("status") != "success":
        return None

    try:
        return LocationInfo(
            city=str(payload.get("city") or ""),
            region=str(payload.get("regionName") or ""),
            country=str(payload.get("country") or ""),
            latitude=float(payload.get("lat")),
            longitude=float(payload.get("lon")),
            timezone=str(payload.get("timezone") or ""),
            source="ip-api",
            ip=str(payload.get("query") or target),
        )
    except Exception:
        return None


def _ip_location_from_ipinfo(http: HttpClient, ip: str | None = None) -> LocationInfo | None:
    target = ip.strip() if ip else ""
    url = f"https://ipinfo.io/{target}/json" if target else "https://ipinfo.io/json"
    payload = http.get_json(url)
    if not payload:
        return None

    loc = str(payload.get("loc") or "")
    if "," not in loc:
        return None

    try:
        lat_text, lon_text = loc.split(",", 1)
        return LocationInfo(
            city=str(payload.get("city") or ""),
            region=str(payload.get("region") or ""),
            country=str(payload.get("country") or ""),
            latitude=float(lat_text),
            longitude=float(lon_text),
            timezone=str(payload.get("timezone") or ""),
            source="ipinfo",
            ip=str(payload.get("ip") or target),
        )
    except Exception:
        return None


def resolve_ip_location(http: HttpClient, ip: str | None = None) -> LocationInfo | None:
    primary = _ip_location_from_ip_api(http, ip)
    if primary:
        return primary

    return _ip_location_from_ipinfo(http, ip)
