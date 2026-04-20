"""US city/state timezone lookup utilities for shipment scheduling."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from geonamescache import GeonamesCache

STATE_NAME_TO_CODE = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def _normalize_city(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", value.lower()).strip()


def _normalize_state(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower().strip(".")
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned.upper()
    return STATE_NAME_TO_CODE.get(cleaned)


def _parse_city_state(location: str | None) -> tuple[str | None, str | None]:
    if not location:
        return None, None
    cleaned = re.sub(r"\s+", " ", location).strip(" ,.-")
    if not cleaned:
        return None, None

    if "," in cleaned:
        city_raw, state_raw = cleaned.rsplit(",", 1)
        city = city_raw.strip()
        state = _normalize_state(state_raw)
        return (city or None), state

    parts = cleaned.split(" ")
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
        state = _normalize_state(parts[-1])
        city = " ".join(parts[:-1]).strip()
        return (city or None), state

    return cleaned, None


@lru_cache(maxsize=1)
def _city_state_timezone_index() -> dict[tuple[str, str], str]:
    """Build in-memory index: (normalized_city, state_code) -> IANA timezone."""
    gc = GeonamesCache()
    index: dict[tuple[str, str], tuple[str, int]] = {}
    for city in gc.get_cities().values():
        if city.get("countrycode") != "US":
            continue
        state_code = _normalize_state(str(city.get("admin1code", "")))
        timezone_name = city.get("timezone")
        city_name = city.get("name")
        if not state_code or not timezone_name or not city_name:
            continue
        key = (_normalize_city(str(city_name)), state_code)
        population = int(city.get("population") or 0)
        existing = index.get(key)
        if existing is None or population > existing[1]:
            index[key] = (str(timezone_name), population)
    return {key: value[0] for key, value in index.items()}


def resolve_us_timezone(location: str | None) -> str | None:
    """Resolve IANA timezone for a US location string like 'Dallas, TX'."""
    city, state = _parse_city_state(location)
    if not city or not state:
        return None
    return _city_state_timezone_index().get((_normalize_city(city), state))


def infer_shipment_timezone(origin: str | None, destination: str | None) -> str | None:
    """Infer shipment timezone prioritizing origin, then destination."""
    return resolve_us_timezone(origin) or resolve_us_timezone(destination)


def local_naive_to_utc(local_naive: datetime, timezone_name: str) -> datetime:
    """Interpret naive datetime in timezone_name and convert to UTC."""
    local = local_naive.replace(tzinfo=ZoneInfo(timezone_name))
    return local.astimezone(timezone.utc)


def offset_minutes_for_local_naive(timezone_name: str, local_naive: datetime) -> int:
    """UTC offset in minutes for timezone_name at the given local (naive) civil datetime."""
    aware_local = local_naive.replace(tzinfo=ZoneInfo(timezone_name))
    at_utc = aware_local.astimezone(timezone.utc)
    return offset_minutes_at(timezone_name, at_utc)


def local_date_iso_in_zone(local_naive: datetime, timezone_name: str | None) -> str:
    """Calendar date for a naive local civil time in timezone_name (DST-aware)."""
    if timezone_name:
        aware = local_naive.replace(tzinfo=ZoneInfo(timezone_name))
        return aware.date().isoformat()
    return local_naive.date().isoformat()


def format_ready_at_wall_display(local_naive: datetime | None, timezone_name: str | None) -> str:
    """Human/TMS-friendly ready time: wall clock + optional IANA zone (no UTC conversion)."""
    if local_naive is None:
        return ""
    base = local_naive.replace(microsecond=0).isoformat(sep=" ")
    if timezone_name:
        return f"{base} ({timezone_name})"
    return base


def apply_shipment_ready_at_wall_fields(
    ready_at: datetime | None,
    origin: str | None,
    destination: str | None,
) -> tuple[datetime | None, str | None, int | None]:
    """
    Keep ready_at as local wall-clock time (naive). Attach IANA zone from route; store offset metadata.

    Aware datetimes are converted to local wall time in the resolved zone (or UTC if unknown zone).
    """
    if ready_at is None:
        return None, None, None

    timezone_name = infer_shipment_timezone(origin, destination)
    wall: datetime
    if ready_at.tzinfo is None:
        wall = ready_at
    elif timezone_name:
        wall = ready_at.astimezone(ZoneInfo(timezone_name)).replace(tzinfo=None)
    else:
        wall = ready_at.astimezone(timezone.utc).replace(tzinfo=None)

    offset: int | None
    if timezone_name:
        offset = offset_minutes_for_local_naive(timezone_name, wall)
    else:
        offset = None

    return wall, timezone_name, offset


def offset_minutes_at(timezone_name: str, at_utc: datetime | None = None) -> int:
    """Return UTC offset in minutes for timezone_name at given UTC instant."""
    current = at_utc or datetime.now(timezone.utc)
    offset = current.astimezone(ZoneInfo(timezone_name)).utcoffset()
    return int((offset.total_seconds() if offset else 0) // 60)
