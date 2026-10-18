"""Typed models for Midttrafik Live API responses.

Each model keeps the untouched JSON in ``raw`` so fields not modelled here are
still reachable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

# The API returns naive local timestamps ("2026-10-18T17:51:00").
TZ = ZoneInfo("Europe/Copenhagen")

# trafficTypeCode values seen in the API.
TRAFFIC_TYPE_LIGHT_RAIL = "070"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


@dataclass(slots=True)
class LineColors:
    foreground: str | None
    background: str | None
    text: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> LineColors | None:
        if not d:
            return None
        return cls(d.get("colorForeground"), d.get("colorBackground"), d.get("colorText"))


@dataclass(slots=True)
class Stop:
    number: str
    name: str
    latitude: float
    longitude: float
    distance: float | None
    is_light_rail: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Stop:
        return cls(
            number=d["number"],
            name=d["name"],
            latitude=d["latitude"],
            longitude=d["longitude"],
            distance=d.get("distance"),
            # "types": {"2": "2"} marks light rail (Letbane) stops.
            is_light_rail="2" in (d.get("types") or {}),
            raw=d,
        )


@dataclass(slots=True)
class Bus:
    """A vehicle currently driving, with its live GPS position."""

    id: int
    line: str
    latitude: float
    longitude: float
    direction: str
    journey_id: str
    end_station: str
    traffic_type_code: str | None
    distance: float | None
    colors: LineColors | None
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Bus:
        return cls(
            id=d["id"],
            line=d["line"],
            latitude=d["latitude"],
            longitude=d["longitude"],
            direction=d.get("directionText", ""),
            journey_id=d.get("journeyId", ""),
            end_station=d.get("endStation", ""),
            traffic_type_code=d.get("trafficTypeCode"),
            distance=d.get("distance"),
            colors=LineColors.from_dict(d.get("colors")),
            raw=d,
        )


@dataclass(slots=True)
class Departure:
    line: str
    direction: str
    stop_name: str
    final_stop: str
    scheduled: datetime
    realtime: datetime | None
    cancelled: bool
    journey_ref: str
    bus_id: str | None
    journey_id: str | None
    traffic_type_code: str | None
    colors: LineColors | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def expected(self) -> datetime:
        """Best known departure time (realtime if available, else scheduled)."""
        return self.realtime or self.scheduled

    @property
    def delay_minutes(self) -> int:
        return round((self.expected - self.scheduled).total_seconds() / 60)

    @property
    def has_realtime(self) -> bool:
        return self.realtime is not None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Departure:
        active = d.get("activeBus") or {}
        return cls(
            line=d["name"],
            direction=d.get("direction", ""),
            stop_name=d.get("stop", ""),
            final_stop=d.get("finalStop", ""),
            scheduled=parse_dt(d["dateTime"]),
            realtime=parse_dt(d.get("realRtDateTime") or d.get("rtDateTime")),
            cancelled=bool(d.get("cancelled")),
            journey_ref=d.get("ref", ""),
            bus_id=active.get("id"),
            journey_id=active.get("journeyId"),
            traffic_type_code=d.get("trafficTypeCode"),
            colors=LineColors.from_dict(d.get("colors")),
            raw=d,
        )


@dataclass(slots=True)
class JourneyStop:
    number: str
    name: str
    latitude: float
    longitude: float
    scheduled_arrival: datetime | None
    scheduled_departure: datetime | None
    realtime_arrival: datetime | None
    realtime_departure: datetime | None
    passed: bool
    cancelled: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_journey_details(cls, d: dict[str, Any]) -> JourneyStop:
        return cls(
            number=d["number"],
            name=d["name"],
            latitude=d["latitude"],
            longitude=d["longitude"],
            scheduled_arrival=parse_dt(d.get("arrDateTime")),
            scheduled_departure=parse_dt(d.get("depDateTime")),
            realtime_arrival=parse_dt(d.get("rtArrDateTime")),
            realtime_departure=parse_dt(d.get("rtDepDateTime")),
            passed=bool(d.get("stopPassed")),
            cancelled=bool(d.get("cancelled")),
            raw=d,
        )

    @classmethod
    def from_bus_stops(cls, d: dict[str, Any]) -> JourneyStop:
        return cls(
            number=d["number"],
            name=d["name"],
            latitude=d["latitude"],
            longitude=d["longitude"],
            scheduled_arrival=parse_dt(d.get("arriveTime")),
            scheduled_departure=parse_dt(d.get("departureTime")),
            realtime_arrival=parse_dt(d.get("rtArriveTime")),
            realtime_departure=parse_dt(d.get("rtDepartureTime")),
            passed=bool(d.get("stopPassed")),
            cancelled=bool(d.get("cancelled")),
            raw=d,
        )


@dataclass(slots=True)
class SearchResult:
    """Grouped result of a free-text search. ``routes`` and ``stops`` are raw items."""

    routes: list[dict[str, Any]]
    stops: list[dict[str, Any]]
    raw: dict[str, Any] = field(repr=False)

    @property
    def stop_numbers(self) -> list[tuple[str, str]]:
        """Flattened ``(stop_number, name)`` pairs from the stop groups."""
        return [(s["number"], group["name"]) for group in self.stops for s in group.get("stops", [])]
