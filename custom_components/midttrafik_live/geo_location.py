"""Live vehicles as geo_location entities, so they show up on Home Assistant's map."""

from __future__ import annotations

import base64
from html import escape
import re
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.location import distance

from .api import Bus
from .const import ATTRIBUTION, DOMAIN, LIGHT_RAIL_TRAFFIC_TYPE
from .coordinator import MidttrafikConfigEntry, VehicleCoordinator, bus_to_dict

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{3,8}$")


def _badge(line: str, background: str | None, text: str | None) -> str:
    """SVG line badge as a data URL, shown as the marker on Home Assistant's map."""
    bg = background if background and _HEX_COLOR.match(background) else "#0077B3"
    fg = text if text and _HEX_COLOR.match(text) else "#FFFFFF"
    size = 30 if len(line) <= 2 else 24 if len(line) <= 3 else 18
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" fill="{bg}"/>'
        f'<text x="32" y="{32 + size * 0.36:.0f}" font-family="Arial,Helvetica,sans-serif" '
        f'font-size="{size}" font-weight="700" text-anchor="middle" fill="{fg}">{escape(line)}</text>'
        "</svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MidttrafikConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: VehicleCoordinator = entry.runtime_data
    tracked: dict[int, VehicleEvent] = {}

    @callback
    def _sync() -> None:
        """Add entities for new vehicles and drop those that disappeared."""
        current = coordinator.data or {}
        new = [VehicleEvent(coordinator, bus) for bus_id, bus in current.items() if bus_id not in tracked]
        for entity in new:
            tracked[entity.bus_id] = entity
        if new:
            async_add_entities(new)
        for bus_id in [b for b in tracked if b not in current]:
            hass.async_create_task(tracked.pop(bus_id).async_remove(force_remove=True))

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class VehicleEvent(CoordinatorEntity[VehicleCoordinator], GeolocationEvent):
    """One moving bus or tram. Not stored in the entity registry (no unique_id)."""

    _attr_attribution = ATTRIBUTION
    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator: VehicleCoordinator, bus: Bus) -> None:
        super().__init__(coordinator)
        self.bus_id = bus.id
        self._bus = bus
        self._attr_name = f"{bus.line} → {bus.direction}"

    @callback
    def _handle_coordinator_update(self) -> None:
        # Keep the last known position if the vehicle is about to be removed.
        if (bus := self.coordinator.data.get(self.bus_id)) is not None:
            self._bus = bus
        super()._handle_coordinator_update()

    @property
    def icon(self) -> str:
        return "mdi:tram" if self._bus.traffic_type_code == LIGHT_RAIL_TRAFFIC_TYPE else "mdi:bus"

    @property
    def entity_picture(self) -> str:
        colors = self._bus.colors
        return _badge(
            self._bus.line,
            colors.background if colors else None,
            colors.text if colors else None,
        )

    @property
    def latitude(self) -> float:
        return self._bus.latitude

    @property
    def longitude(self) -> float:
        return self._bus.longitude

    @property
    def distance(self) -> float:
        home = self.hass.config
        return round(distance(home.latitude, home.longitude, self.latitude, self.longitude) / 1000, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = bus_to_dict(self._bus)
        del attrs["latitude"], attrs["longitude"]
        return attrs
