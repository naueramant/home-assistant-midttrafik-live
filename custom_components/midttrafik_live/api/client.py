"""Async client for the (unofficial) Midttrafik Live API.

Endpoints were taken from the Midttrafik Live Android app (v1.29.11). The
public read endpoints used here require no authentication.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import aiohttp

from .exceptions import MidttrafikLiveApiError, MidttrafikLiveConnectionError
from .models import Bus, Departure, JourneyStop, SearchResult, Stop

DEFAULT_BASE_URL = "https://apilivemidttrafik.adibuslive.com/api"
USER_AGENT = "python-midttrafik-live"


class MidttrafikLiveClient:
    """Client for live bus / light rail data in the Midttrafik region (Aarhus)."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15,
    ) -> None:
        # Home Assistant should pass its shared session (async_get_clientsession).
        self._session = session
        self._owns_session = session is None
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def __aenter__(self) -> MidttrafikLiveClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        if isinstance(params, dict):
            params = {k: _fmt(v) for k, v in params.items() if v is not None}
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                data=data,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=self._timeout,
            ) as resp:
                try:
                    payload = await resp.json(content_type=None)
                except ValueError as err:
                    raise MidttrafikLiveApiError(resp.status, "invalid JSON") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise MidttrafikLiveConnectionError(str(err)) from err

        # Responses are wrapped as {"data": ..., "status": 200, "errors": null}.
        if not isinstance(payload, dict):
            raise MidttrafikLiveApiError(resp.status, payload)
        status = payload.get("status", resp.status)
        if status != 200 or payload.get("errors"):
            raise MidttrafikLiveApiError(status, payload.get("errors"))
        return payload.get("data") or {}

    # --- Stops -----------------------------------------------------------

    async def get_stops_nearby(self, latitude: float, longitude: float, radius: int = 500) -> list[Stop]:
        """Stops within ``radius`` metres, sorted by distance."""
        data = await self._request(
            "GET", "/stops", params={"latitude": latitude, "longitude": longitude, "radius": radius}
        )
        return [Stop.from_dict(s) for s in data.get("stops", [])]

    async def get_stop(self, stop_number: str) -> Stop:
        data = await self._request("GET", f"/stops/single/{stop_number}")
        return Stop.from_dict(data["stop"])

    async def get_departures(
        self,
        stop_number: str,
        *,
        at: datetime | None = None,
        include_group_stops: bool | None = None,
    ) -> list[Departure]:
        """Upcoming departures from a stop (about 20), with realtime where available.

        ``at`` asks for departures from another point in time.
        ``include_group_stops`` also includes sibling platforms of the same stop.
        """
        data = await self._request(
            "GET",
            f"/stops/departures/{stop_number}",
            params={
                "overrideDateTime": at.strftime("%Y-%m-%dT%H:%M:%S") if at else None,
                "includeGroupStops": include_group_stops,
            },
        )
        return [Departure.from_dict(d) for d in data.get("departures", [])]

    async def get_journey_details(self, journey_ref: str) -> list[JourneyStop]:
        """All stops of the trip behind a departure (``Departure.journey_ref``)."""
        data = await self._request("POST", "/stops/journeydetails", data={"journeyRef": journey_ref})
        return [JourneyStop.from_journey_details(s) for s in data.get("stops", [])]

    async def get_journey_details_raw(self, journey_ref: str) -> dict[str, Any]:
        """Like :meth:`get_journey_details` but includes messages, changes and route coordinates."""
        return await self._request("POST", "/stops/journeydetails", data={"journeyRef": journey_ref})

    # --- Vehicles --------------------------------------------------------

    async def get_buses_nearby(self, latitude: float, longitude: float, radius: int = 1000) -> list[Bus]:
        """Vehicles currently within ``radius`` metres, with live positions."""
        data = await self._request(
            "GET", "/buses", params={"latitude": latitude, "longitude": longitude, "radius": radius}
        )
        return [Bus.from_dict(b) for b in data.get("buses", [])]

    async def get_bus(self, bus_id: int | str) -> Bus:
        data = await self._request("GET", f"/buses/{bus_id}")
        return Bus.from_dict(data["bus"])

    async def get_buses_on_routes(self, routes: Iterable[tuple[str, str]]) -> list[Bus]:
        """All live vehicles on the given ``(line, end_station_number)`` routes.

        Example: ``[("L2", "860431601")]`` — every L2 tram heading to Lisbjergskolen.
        """
        data = await self._request("GET", "/buses/routeMultiple", params=_line_end_params(routes))
        return [Bus.from_dict(b) for b in data.get("buses", [])]

    async def get_bus_stops(self, journey_id: str) -> list[JourneyStop]:
        """Stops for a running vehicle's journey (``Bus.journey_id``)."""
        data = await self._request("GET", f"/buses/stops/{journey_id}", params={"polyline": False})
        return [JourneyStop.from_bus_stops(s) for s in data.get("stops", [])]

    async def get_route_stops(
        self,
        routes: Iterable[tuple[str, str]],
        latitude: float,
        longitude: float,
        radius: int = 500,
    ) -> list[Stop]:
        """Stops served by the given ``(line, end_station_number)`` routes."""
        params = _line_end_params(routes) + [
            ("latitude", _fmt(latitude)),
            ("longitude", _fmt(longitude)),
            ("radius", _fmt(radius)),
        ]
        data = await self._request("GET", "/stops/routeMultiple", params=params)
        return [Stop.from_dict(s) for s in data.get("stops", [])]

    async def get_passenger_count(self, bus_id: int | str) -> dict[str, Any]:
        """Seat occupancy description for a vehicle (not available on all vehicles)."""
        return await self._request(
            "GET", "/passengercount/getpassengercountdescriptionfromunit", params={"unitId": bus_id}
        )

    # --- Search ----------------------------------------------------------

    async def search(
        self,
        query: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> SearchResult:
        """Free-text search for stops and lines. Coordinates sort results by distance."""
        data = await self._request(
            "GET", "/search/query", params={"query": query, "latitude": latitude, "longitude": longitude}
        )
        return SearchResult(
            routes=(data.get("routes") or {}).get("items", []),
            stops=(data.get("stops") or {}).get("items", []),
            raw=data,
        )


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _line_end_params(routes: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    # The app serialises with qs.stringify: lineEnd[0]=L2|860431601&lineEnd[1]=...
    return [(f"lineEnd[{i}]", f"{line}|{end}") for i, (line, end) in enumerate(routes)]
