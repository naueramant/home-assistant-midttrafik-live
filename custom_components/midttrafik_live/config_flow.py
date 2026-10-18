"""Config flow for Midttrafik Live.

Three kinds of entries:
- stop: departure board for one stop (all its platforms, or a single one)
- line: live positions of every vehicle on one line in one direction
- area: live positions of every vehicle within a radius of a point
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_NAME, CONF_RADIUS
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import MidttrafikLiveClient, MidttrafikLiveError
from .const import (
    CONF_DEPARTURE_SENSORS,
    CONF_DIRECTION,
    CONF_END_STATION,
    CONF_ENTRY_TYPE,
    CONF_LINE,
    CONF_LINES,
    CONF_SCAN_INTERVAL,
    CONF_STOP_NAME,
    CONF_STOP_NUMBERS,
    DEFAULT_AREA_RADIUS,
    DEFAULT_DEPARTURE_SENSORS,
    DEFAULT_STOP_SCAN_INTERVAL,
    DEFAULT_VEHICLE_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    TYPE_AREA,
    TYPE_LINE,
    TYPE_STOP,
)

CONF_QUERY = "query"
CONF_CHOICE = "choice"
NEARBY_STOP_RADIUS = 500


def _dropdown(choices: dict[str, str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=k, label=v) for k, v in choices.items()],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class MidttrafikLiveConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        # choice key -> (title, data)
        self._choices: dict[str, tuple[str, dict[str, Any]]] = {}

    @property
    def _client(self) -> MidttrafikLiveClient:
        return MidttrafikLiveClient(async_get_clientsession(self.hass))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> MidttrafikOptionsFlow:
        return MidttrafikOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[TYPE_STOP, TYPE_LINE, TYPE_AREA])

    # --- Stop --------------------------------------------------------------

    async def async_step_stop(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            query = user_input.get(CONF_QUERY, "").strip()
            try:
                if query:
                    self._choices = await self._search_stops(query)
                else:
                    self._choices = await self._nearby_stops()
            except MidttrafikLiveError:
                errors["base"] = "cannot_connect"
            else:
                if self._choices:
                    return await self.async_step_stop_select()
                errors["base"] = "no_results"

        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema({vol.Optional(CONF_QUERY, default=""): TextSelector()}),
            errors=errors,
        )

    async def _search_stops(self, query: str) -> dict[str, tuple[str, dict[str, Any]]]:
        result = await self._client.search(query, self.hass.config.latitude, self.hass.config.longitude)
        choices: dict[str, tuple[str, dict[str, Any]]] = {}
        for group in result.stops:
            numbers = [s["number"] for s in group.get("stops", [])]
            if not numbers:
                continue
            name = group["name"]
            lines = ", ".join(line["name"] for line in group.get("lines", []))
            label = f"{name} ({lines})" if lines else name
            choices[",".join(numbers)] = (label, self._stop_data(name, numbers))
            if len(numbers) > 1:
                # Also offer each platform alone, e.g. to get only one direction.
                for i, number in enumerate(numbers, 1):
                    choices[number] = (
                        f"{name} – platform {i}/{len(numbers)} ({number})",
                        self._stop_data(f"{name} {i}", [number]),
                    )
        return choices

    async def _nearby_stops(self) -> dict[str, tuple[str, dict[str, Any]]]:
        stops = await self._client.get_stops_nearby(
            self.hass.config.latitude, self.hass.config.longitude, NEARBY_STOP_RADIUS
        )
        groups: dict[str, list] = {}
        for stop in stops:
            groups.setdefault(stop.name.strip(), []).append(stop)
        return {
            ",".join(s.number for s in group): (
                f"{name} ({group[0].distance:.0f} m)",
                self._stop_data(name, [s.number for s in group]),
            )
            for name, group in groups.items()
        }

    @staticmethod
    def _stop_data(name: str, numbers: list[str]) -> dict[str, Any]:
        return {CONF_ENTRY_TYPE: TYPE_STOP, CONF_STOP_NAME: name, CONF_STOP_NUMBERS: numbers}

    async def async_step_stop_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            title, data = self._choices[user_input[CONF_CHOICE]]
            await self.async_set_unique_id(f"stop_{'_'.join(sorted(data[CONF_STOP_NUMBERS]))}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=data[CONF_STOP_NAME],
                data=data,
                options={
                    CONF_DEPARTURE_SENSORS: DEFAULT_DEPARTURE_SENSORS,
                    CONF_SCAN_INTERVAL: DEFAULT_STOP_SCAN_INTERVAL,
                    CONF_LINES: [],
                },
            )
        return self.async_show_form(
            step_id="stop_select",
            data_schema=vol.Schema(
                {vol.Required(CONF_CHOICE): _dropdown({k: v[0] for k, v in self._choices.items()})}
            ),
        )

    # --- Line --------------------------------------------------------------

    async def async_step_line(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await self._client.search(user_input[CONF_QUERY].strip())
            except MidttrafikLiveError:
                errors["base"] = "cannot_connect"
            else:
                self._choices = {}
                for route in result.routes:
                    line, end, direction = route["line"], route["endStation"], route.get("directionText", "")
                    self._choices[f"{line}|{end}"] = (
                        f"{line} → {direction}",
                        {
                            CONF_ENTRY_TYPE: TYPE_LINE,
                            CONF_LINE: line,
                            CONF_END_STATION: end,
                            CONF_DIRECTION: direction,
                        },
                    )
                if self._choices:
                    return await self.async_step_line_select()
                errors["base"] = "no_results"

        return self.async_show_form(
            step_id="line",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): TextSelector()}),
            errors=errors,
        )

    async def async_step_line_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            title, data = self._choices[user_input[CONF_CHOICE]]
            await self.async_set_unique_id(f"line_{data[CONF_LINE]}_{data[CONF_END_STATION]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=title,
                data=data,
                options={CONF_SCAN_INTERVAL: DEFAULT_VEHICLE_SCAN_INTERVAL},
            )
        return self.async_show_form(
            step_id="line_select",
            data_schema=vol.Schema(
                {vol.Required(CONF_CHOICE): _dropdown({k: v[0] for k, v in self._choices.items()})}
            ),
        )

    # --- Area --------------------------------------------------------------

    async def async_step_area(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            loc = user_input[CONF_LOCATION]
            data = {
                CONF_ENTRY_TYPE: TYPE_AREA,
                CONF_LATITUDE: loc[CONF_LATITUDE],
                CONF_LONGITUDE: loc[CONF_LONGITUDE],
                CONF_RADIUS: int(loc.get(CONF_RADIUS, DEFAULT_AREA_RADIUS)),
            }
            await self.async_set_unique_id(
                f"area_{data[CONF_LATITUDE]:.4f}_{data[CONF_LONGITUDE]:.4f}_{data[CONF_RADIUS]}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=data,
                options={CONF_SCAN_INTERVAL: DEFAULT_VEHICLE_SCAN_INTERVAL, CONF_LINES: []},
            )

        home = self.hass.config
        return self.async_show_form(
            step_id="area",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Vehicles near home"): TextSelector(),
                    vol.Required(
                        CONF_LOCATION,
                        default={
                            CONF_LATITUDE: home.latitude,
                            CONF_LONGITUDE: home.longitude,
                            CONF_RADIUS: DEFAULT_AREA_RADIUS,
                        },
                    ): LocationSelector(LocationSelectorConfig(radius=True)),
                }
            ),
        )


class MidttrafikOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        entry = self.config_entry
        entry_type = entry.data[CONF_ENTRY_TYPE]
        opts = entry.options
        default_interval = (
            DEFAULT_STOP_SCAN_INTERVAL if entry_type == TYPE_STOP else DEFAULT_VEHICLE_SCAN_INTERVAL
        )
        schema: dict[Any, Any] = {
            vol.Required(
                CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, default_interval)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL, max=3600, step=1, unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }

        if entry_type == TYPE_STOP:
            schema[
                vol.Required(
                    CONF_DEPARTURE_SENSORS,
                    default=opts.get(CONF_DEPARTURE_SENSORS, DEFAULT_DEPARTURE_SENSORS),
                )
            ] = NumberSelector(NumberSelectorConfig(min=1, max=10, step=1, mode=NumberSelectorMode.BOX))

        if entry_type in (TYPE_STOP, TYPE_AREA):
            # Suggest lines currently seen; any other line can be typed in.
            coordinator = getattr(entry, "runtime_data", None)
            seen: set[str] = set(opts.get(CONF_LINES, []))
            if coordinator is not None and coordinator.data:
                items = coordinator.data if entry_type == TYPE_STOP else coordinator.data.values()
                seen.update(item.line for item in items)
            schema[vol.Optional(CONF_LINES, default=opts.get(CONF_LINES, []))] = SelectSelector(
                SelectSelectorConfig(
                    options=sorted(seen, key=lambda s: (len(s), s)),
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
