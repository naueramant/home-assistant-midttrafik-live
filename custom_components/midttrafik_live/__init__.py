"""The Midttrafik Live integration."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import MidttrafikLiveClient, MidttrafikLiveError
from .api.models import TZ
from .const import CONF_ENTRY_TYPE, DOMAIN, FRONTEND_URL, TYPE_STOP
from .coordinator import (
    MidttrafikConfigEntry,
    StopCoordinator,
    VehicleCoordinator,
    departure_to_dict,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

STOP_PLATFORMS = [Platform.SENSOR]
VEHICLE_PLATFORMS = [Platform.SENSOR, Platform.GEO_LOCATION]


def _platforms(entry: MidttrafikConfigEntry) -> list[Platform]:
    return STOP_PLATFORMS if entry.data[CONF_ENTRY_TYPE] == TYPE_STOP else VEHICLE_PLATFORMS


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Lovelace cards and the integration's actions."""
    if hass.http is not None:
        integration = await async_get_integration(hass, DOMAIN)
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    FRONTEND_URL,
                    str(Path(__file__).parent / "frontend" / "midttrafik-live-card.js"),
                    cache_headers=False,
                )
            ]
        )
        await _async_register_card(hass, f"{FRONTEND_URL}?v={integration.version}")

    _register_services(hass)
    return True


async def _async_register_card(hass: HomeAssistant, url: str) -> None:
    """Add the cards as a Lovelace resource, updating the version on upgrades.

    The version query string makes browsers fetch the new file after an upgrade.
    """
    resources = hass.data[LOVELACE_DATA].resources
    if not isinstance(resources, ResourceStorageCollection):
        _LOGGER.info(
            "Lovelace resources are in YAML mode; add %s as a module resource to use the cards", url
        )
        return
    await resources.async_get_info()  # makes sure the collection is loaded
    for item in resources.async_items():
        if item["url"].split("?")[0] == FRONTEND_URL:
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})


async def async_setup_entry(hass: HomeAssistant, entry: MidttrafikConfigEntry) -> bool:
    client = MidttrafikLiveClient(async_get_clientsession(hass))
    if entry.data[CONF_ENTRY_TYPE] == TYPE_STOP:
        coordinator = StopCoordinator(hass, entry, client)
    else:
        coordinator = VehicleCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MidttrafikConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, _platforms(entry))


async def _async_reload_entry(hass: HomeAssistant, entry: MidttrafikConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    def client() -> MidttrafikLiveClient:
        return MidttrafikLiveClient(async_get_clientsession(hass))

    async def get_departures(call: ServiceCall) -> ServiceResponse:
        at: datetime | None = call.data.get("at")
        if at is not None and at.tzinfo is not None:
            # The API expects Danish local time; naive values are taken as such.
            at = at.astimezone(TZ)
        try:
            departures = await client().get_departures(call.data["stop_number"], at=at)
        except MidttrafikLiveError as err:
            raise HomeAssistantError(str(err)) from err
        return {"departures": [departure_to_dict(d) for d in departures]}

    async def get_journey(call: ServiceCall) -> ServiceResponse:
        try:
            stops = await client().get_journey_details(call.data["journey_ref"])
        except MidttrafikLiveError as err:
            raise HomeAssistantError(str(err)) from err
        return {
            "stops": [
                {
                    "number": s.number,
                    "name": s.name,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                    "scheduled_arrival": s.scheduled_arrival.isoformat() if s.scheduled_arrival else None,
                    "scheduled_departure": s.scheduled_departure.isoformat() if s.scheduled_departure else None,
                    "realtime_arrival": s.realtime_arrival.isoformat() if s.realtime_arrival else None,
                    "realtime_departure": s.realtime_departure.isoformat() if s.realtime_departure else None,
                    "passed": s.passed,
                    "cancelled": s.cancelled,
                }
                for s in stops
            ]
        }

    async def search(call: ServiceCall) -> ServiceResponse:
        try:
            result = await client().search(call.data["query"])
        except MidttrafikLiveError as err:
            raise HomeAssistantError(str(err)) from err
        return {
            "stops": [
                {
                    "name": g["name"],
                    "stop_numbers": [s["number"] for s in g.get("stops", [])],
                    "lines": [line["name"] for line in g.get("lines", [])],
                }
                for g in result.stops
            ],
            "lines": [
                {"line": r["line"], "direction": r.get("directionText"), "end_station": r.get("endStation")}
                for r in result.routes
            ],
        }

    hass.services.async_register(
        DOMAIN,
        "get_departures",
        get_departures,
        schema=vol.Schema(
            {vol.Required("stop_number"): cv.string, vol.Optional("at"): cv.datetime}
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_journey",
        get_journey,
        schema=vol.Schema({vol.Required("journey_ref"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "search",
        search,
        schema=vol.Schema({vol.Required("query"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
