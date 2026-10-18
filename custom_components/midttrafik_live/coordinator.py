"""Data update coordinators for Midttrafik Live."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Bus, Departure, MidttrafikLiveClient, MidttrafikLiveError, Stop
from .const import (
    CONF_END_STATION,
    CONF_ENTRY_TYPE,
    CONF_LINE,
    CONF_LINES,
    CONF_SCAN_INTERVAL,
    CONF_STOP_NUMBERS,
    DEFAULT_STOP_SCAN_INTERVAL,
    DEFAULT_VEHICLE_SCAN_INTERVAL,
    DOMAIN,
    LIGHT_RAIL_TRAFFIC_TYPE,
    TYPE_LINE,
)

_LOGGER = logging.getLogger(__name__)

type MidttrafikConfigEntry = ConfigEntry[StopCoordinator | VehicleCoordinator]


def departure_to_dict(d: Departure) -> dict[str, Any]:
    colors = d.colors
    return {
        "line": d.line,
        "direction": d.direction,
        "final_stop": d.final_stop,
        "stop": d.stop_name,
        "expected": d.expected.isoformat(),
        "scheduled": d.scheduled.isoformat(),
        "delay_minutes": d.delay_minutes,
        "realtime": d.has_realtime,
        "cancelled": d.cancelled,
        "light_rail": d.traffic_type_code == LIGHT_RAIL_TRAFFIC_TYPE,
        "color": colors.background if colors else None,
        "text_color": colors.text if colors else None,
        "journey_ref": d.journey_ref,
        "bus_id": d.bus_id,
    }


def bus_to_dict(b: Bus) -> dict[str, Any]:
    colors = b.colors
    return {
        "id": b.id,
        "line": b.line,
        "direction": b.direction,
        "latitude": b.latitude,
        "longitude": b.longitude,
        "journey_id": b.journey_id,
        "light_rail": b.traffic_type_code == LIGHT_RAIL_TRAFFIC_TYPE,
        "color": colors.background if colors else None,
        "text_color": colors.text if colors else None,
    }


class _BaseCoordinator[T](DataUpdateCoordinator[T]):
    config_entry: MidttrafikConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MidttrafikConfigEntry,
        client: MidttrafikLiveClient,
        default_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, default_interval)
            ),
        )
        self.client = client
        self.lines: set[str] = set(entry.options.get(CONF_LINES, []))


class StopCoordinator(_BaseCoordinator[list[Departure]]):
    """Departures from one stop, merged across all of its platforms."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, DEFAULT_STOP_SCAN_INTERVAL)
        self.stop_numbers: list[str] = entry.data[CONF_STOP_NUMBERS]
        self.stops: list[Stop] = []
        self._last: dict[str, list[Departure]] = {}

    async def _async_setup(self) -> None:
        try:
            self.stops = list(
                await asyncio.gather(*(self.client.get_stop(n) for n in self.stop_numbers))
            )
        except MidttrafikLiveError as err:
            raise UpdateFailed(f"Could not look up stop: {err}") from err

    async def _async_update_data(self) -> list[Departure]:
        responses = await asyncio.gather(
            *(self.client.get_departures(n) for n in self.stop_numbers),
            return_exceptions=True,
        )
        # The API has occasional hiccups on single stops; reuse that platform's
        # last result instead of failing the whole stop.
        results: list[list[Departure]] = []
        errors: list[BaseException] = []
        for number, response in zip(self.stop_numbers, responses):
            if isinstance(response, MidttrafikLiveError):
                errors.append(response)
                if number in self._last:
                    results.append(self._last[number])
            elif isinstance(response, BaseException):
                raise response
            else:
                self._last[number] = response
                results.append(response)
        if errors:
            if len(errors) == len(self.stop_numbers):
                raise UpdateFailed(str(errors[0])) from errors[0]
            _LOGGER.debug("Partial update for %s: %s", self.config_entry.title, errors)

        seen: set[str] = set()
        departures: list[Departure] = []
        for dep in (d for result in results for d in result):
            key = dep.raw.get("uniqueHash") or dep.journey_ref
            if key in seen or (self.lines and dep.line not in self.lines):
                continue
            seen.add(key)
            departures.append(dep)
        departures.sort(key=lambda d: d.expected)
        return departures


class VehicleCoordinator(_BaseCoordinator[dict[int, Bus]]):
    """Live vehicles, either on one line/direction or within an area."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(hass, entry, client, DEFAULT_VEHICLE_SCAN_INTERVAL)
        self.is_line = entry.data[CONF_ENTRY_TYPE] == TYPE_LINE

    async def _async_update_data(self) -> dict[int, Bus]:
        data = self.config_entry.data
        try:
            if self.is_line:
                buses = await self.client.get_buses_on_routes(
                    [(data[CONF_LINE], data[CONF_END_STATION])]
                )
            else:
                buses = await self.client.get_buses_nearby(
                    data[CONF_LATITUDE], data[CONF_LONGITUDE], int(data[CONF_RADIUS])
                )
        except MidttrafikLiveError as err:
            raise UpdateFailed(str(err)) from err
        return {b.id: b for b in buses if not self.lines or b.line in self.lines}
