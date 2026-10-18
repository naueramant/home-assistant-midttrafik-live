"""Sensors for Midttrafik Live."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Departure
from .const import (
    CONF_DEPARTURE_SENSORS,
    CONF_ENTRY_TYPE,
    CONF_STOP_NAME,
    DEFAULT_DEPARTURE_SENSORS,
    LIGHT_RAIL_TRAFFIC_TYPE,
    TYPE_STOP,
)
from .coordinator import (
    MidttrafikConfigEntry,
    StopCoordinator,
    VehicleCoordinator,
    bus_to_dict,
    departure_to_dict,
)
from .entity import MidttrafikEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MidttrafikConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if entry.data[CONF_ENTRY_TYPE] == TYPE_STOP:
        count = int(entry.options.get(CONF_DEPARTURE_SENSORS, DEFAULT_DEPARTURE_SENSORS))
        async_add_entities(
            [UpcomingDeparturesSensor(coordinator)]
            + [DepartureSensor(coordinator, i) for i in range(count)]
        )
    else:
        async_add_entities([VehicleCountSensor(coordinator)])


class UpcomingDeparturesSensor(MidttrafikEntity[StopCoordinator], SensorEntity):
    """Number of upcoming departures; the full list lives in attributes for the card."""

    _attr_translation_key = "upcoming_departures"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"departures", "stops"})

    def __init__(self, coordinator: StopCoordinator) -> None:
        super().__init__(coordinator, "upcoming_departures")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        entry = self.coordinator.config_entry
        return {
            "stop_name": entry.data[CONF_STOP_NAME],
            "stops": [
                {"number": s.number, "name": s.name, "latitude": s.latitude, "longitude": s.longitude}
                for s in self.coordinator.stops
            ],
            "departures": [departure_to_dict(d) for d in self.coordinator.data],
        }


class DepartureSensor(MidttrafikEntity[StopCoordinator], SensorEntity):
    """The n-th next departure, as a timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "departure"

    def __init__(self, coordinator: StopCoordinator, index: int) -> None:
        super().__init__(coordinator, f"departure_{index + 1}")
        self._index = index
        self._attr_translation_placeholders = {"number": str(index + 1)}
        # Only the first one is on by default; the rest are opt-in.
        self._attr_entity_registry_enabled_default = index == 0

    @property
    def _departure(self) -> Departure | None:
        data = self.coordinator.data
        return data[self._index] if self._index < len(data) else None

    @property
    def native_value(self) -> datetime | None:
        dep = self._departure
        return dep.expected if dep else None

    @property
    def icon(self) -> str:
        dep = self._departure
        if dep and dep.traffic_type_code == LIGHT_RAIL_TRAFFIC_TYPE:
            return "mdi:tram"
        return "mdi:bus-clock"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        dep = self._departure
        return departure_to_dict(dep) if dep else None


class VehicleCountSensor(MidttrafikEntity[VehicleCoordinator], SensorEntity):
    """Number of live vehicles; their positions live in attributes for the map card."""

    _attr_translation_key = "vehicles"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"vehicles"})

    def __init__(self, coordinator: VehicleCoordinator) -> None:
        super().__init__(coordinator, "vehicles")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"vehicles": [bus_to_dict(b) for b in self.coordinator.data.values()]}
