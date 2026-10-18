"""Constants for the Midttrafik Live integration."""

from typing import Final

DOMAIN: Final = "midttrafik_live"
ATTRIBUTION: Final = "Data from Midttrafik Live"

CONF_ENTRY_TYPE: Final = "entry_type"
TYPE_STOP: Final = "stop"
TYPE_LINE: Final = "line"
TYPE_AREA: Final = "area"

# Stop entries
CONF_STOP_NAME: Final = "stop_name"
CONF_STOP_NUMBERS: Final = "stop_numbers"
CONF_DEPARTURE_SENSORS: Final = "departure_sensors"

# Line entries
CONF_LINE: Final = "line"
CONF_END_STATION: Final = "end_station"
CONF_DIRECTION: Final = "direction"

# Area entries use CONF_LATITUDE / CONF_LONGITUDE / CONF_RADIUS from homeassistant.const

# Options
CONF_LINES: Final = "lines"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_DEPARTURE_SENSORS: Final = 3
DEFAULT_STOP_SCAN_INTERVAL: Final = 60
DEFAULT_VEHICLE_SCAN_INTERVAL: Final = 20
DEFAULT_AREA_RADIUS: Final = 1000
MIN_SCAN_INTERVAL: Final = 10

LIGHT_RAIL_TRAFFIC_TYPE: Final = "070"

FRONTEND_URL: Final = "/midttrafik_live/midttrafik-live-card.js"
