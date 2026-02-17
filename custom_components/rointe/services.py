"""Services for Rointe integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN
from .coordinator import RointeDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

ATTR_DURATION = "duration"
ATTR_TEMPERATURE = "temperature"
ATTR_SCHEDULE = "schedule"

SERVICE_ACTIVATE_BOOST = "activate_boost"
SERVICE_DEACTIVATE_BOOST = "deactivate_boost"
SERVICE_SET_SCHEDULE = "set_schedule"

SERVICE_ACTIVATE_BOOST_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_DURATION, default=60): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=240)
        ),
        vol.Optional(ATTR_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=15, max=30)
        ),
    }
)

SERVICE_DEACTIVATE_BOOST_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
    }
)

SERVICE_SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_SCHEDULE): dict,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Rointe integration."""

    async def async_activate_boost(call: ServiceCall) -> None:
        """Activate boost mode."""
        entity_ids = call.data[ATTR_ENTITY_ID]
        duration = call.data[ATTR_DURATION]
        temperature = call.data.get(ATTR_TEMPERATURE)

        entity_registry = er.async_get(hass)

        for entity_id in entity_ids:
            entry = entity_registry.async_get(entity_id)
            if not entry:
                _LOGGER.warning("Entity %s not found", entity_id)
                continue

            # Find the coordinator for this device
            for coordinator in hass.data.get(DOMAIN, {}).values():
                if not isinstance(coordinator, RointeDataUpdateCoordinator):
                    continue

                # Extract device_id from entity unique_id
                # Format is typically "rointe-{device_id}-climate" or similar
                device_id = None
                for did, device in coordinator.devices.items():
                    if f"rointe-{did}" in (entry.unique_id or ""):
                        device_id = did
                        break

                if device_id is None:
                    continue

                device = coordinator.devices.get(device_id)
                if device is None:
                    continue

                _LOGGER.info(
                    "Activating boost for %s: %d minutes, temp=%s",
                    device.name,
                    duration,
                    temperature,
                )

                # Convert minutes to seconds
                duration_seconds = duration * 60

                await hass.async_add_executor_job(
                    _activate_boost,
                    coordinator.rointe_api,
                    device,
                    duration_seconds,
                    temperature,
                )

                await coordinator.async_request_refresh()
                break

    async def async_deactivate_boost(call: ServiceCall) -> None:
        """Deactivate boost mode."""
        entity_ids = call.data[ATTR_ENTITY_ID]

        entity_registry = er.async_get(hass)

        for entity_id in entity_ids:
            entry = entity_registry.async_get(entity_id)
            if not entry:
                continue

            for coordinator in hass.data.get(DOMAIN, {}).values():
                if not isinstance(coordinator, RointeDataUpdateCoordinator):
                    continue

                device_id = None
                for did, device in coordinator.devices.items():
                    if f"rointe-{did}" in (entry.unique_id or ""):
                        device_id = did
                        break

                if device_id is None:
                    continue

                device = coordinator.devices.get(device_id)
                if device is None:
                    continue

                _LOGGER.info("Deactivating boost for %s", device.name)

                await hass.async_add_executor_job(
                    _deactivate_boost,
                    coordinator.rointe_api,
                    device,
                )

                await coordinator.async_request_refresh()
                break

    async def async_set_schedule(call: ServiceCall) -> None:
        """Set the schedule."""
        entity_ids = call.data[ATTR_ENTITY_ID]
        schedule = call.data[ATTR_SCHEDULE]

        entity_registry = er.async_get(hass)

        for entity_id in entity_ids:
            entry = entity_registry.async_get(entity_id)
            if not entry:
                continue

            for coordinator in hass.data.get(DOMAIN, {}).values():
                if not isinstance(coordinator, RointeDataUpdateCoordinator):
                    continue

                device_id = None
                for did, device in coordinator.devices.items():
                    if f"rointe-{did}" in (entry.unique_id or ""):
                        device_id = did
                        break

                if device_id is None:
                    continue

                device = coordinator.devices.get(device_id)
                if device is None:
                    continue

                _LOGGER.info("Setting schedule for %s", device.name)

                await hass.async_add_executor_job(
                    _set_schedule,
                    coordinator.rointe_api,
                    device,
                    schedule,
                )

                await coordinator.async_request_refresh()
                break

    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVATE_BOOST,
        async_activate_boost,
        schema=SERVICE_ACTIVATE_BOOST_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DEACTIVATE_BOOST,
        async_deactivate_boost,
        schema=SERVICE_DEACTIVATE_BOOST_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        async_set_schedule,
        schema=SERVICE_SET_SCHEDULE_SCHEMA,
    )


def _activate_boost(api, device, duration_seconds: int, temperature: float | None) -> None:
    """Activate boost mode via API."""
    device_key = api._get_nexa_device_key(device)

    body: dict[str, Any] = {
        "boost_active": True,
        "boost_countdown": duration_seconds,
    }

    if temperature is not None:
        body["temp"] = temperature

    if api.use_nexa_ws:
        api._write_via_websocket(device_key, body)


def _deactivate_boost(api, device) -> None:
    """Deactivate boost mode via API."""
    device_key = api._get_nexa_device_key(device)

    body = {
        "boost_active": False,
        "boost_countdown": 0,
    }

    if api.use_nexa_ws:
        api._write_via_websocket(device_key, body)


def _set_schedule(api, device, schedule: dict) -> None:
    """Set the schedule via API."""
    device_key = api._get_nexa_device_key(device)

    # Validate schedule format
    validated_schedule = {}
    for day, hours in schedule.items():
        day_num = str(day)
        if not isinstance(hours, str) or len(hours) != 24:
            raise ValueError(f"Schedule for day {day} must be a 24-character string")
        # Validate characters
        for char in hours.upper():
            if char not in ("C", "E", "O"):
                raise ValueError(f"Invalid schedule character: {char}")
        validated_schedule[day_num] = hours.upper()

    if api.use_nexa_ws:
        api._write_via_websocket(device_key, {"schedule": validated_schedule})
