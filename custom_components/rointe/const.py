"""Constants for the Rointe Heaters integration."""

from enum import StrEnum
import logging

from homeassistant.const import Platform

LOGGER = logging.getLogger(__package__)

DOMAIN = "rointe"
DEVICE_DOMAIN = "climate"
PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]
CONF_USERNAME = "rointe_username"
CONF_PASSWORD = "rointe_password"
CONF_INSTALLATION = "rointe_installation"
CONF_API_TYPE = "rointe_api_type"

ROINTE_MANUFACTURER = "Rointe"

ROINTE_SUPPORTED_DEVICES = ["radiator", "towel", "therm", "radiatorb", "acs", "oval_towel"]

RADIATOR_DEFAULT_TEMPERATURE = 20

PRESET_ROINTE_ICE = "ice"

API_TYPE_AUTO = "auto"
API_TYPE_ROINTE = "rointe"
API_TYPE_NEXA = "nexa"
API_TYPE_OPTIONS = {
    API_TYPE_AUTO: "Auto (detect)",
    API_TYPE_ROINTE: "Rointe Connect",
    API_TYPE_NEXA: "Nexa",
}


class RointePreset(StrEnum):
    """Rointe radiators preset modes."""

    ECO = "eco"
    COMFORT = "comfort"
    ICE = "ice"
    NONE = "none"
    OFF = "off"


class RointeCommand(StrEnum):
    """Device commands."""

    SET_TEMP = "cmd_set_temp"
    SET_PRESET = "cmd_set_preset"
    SET_HVAC_MODE = "cmd_set_hvac_mode"


class RointeOperationMode(StrEnum):
    """Device operation mode."""

    AUTO = "auto"
    MANUAL = "manual"
