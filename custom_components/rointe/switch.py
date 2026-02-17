"""Switch platform for Rointe devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RointeDataUpdateCoordinator
from .rointe_entity import RointeRadiatorEntity
from .rointesdk.device import RointeDevice


@dataclass
class RointeSwitchRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[RointeDevice], bool]
    field_name: str  # The API field name to write


@dataclass
class RointeSwitchEntityDescription(
    SwitchEntityDescription, RointeSwitchRequiredKeysMixin
):
    """Describes a Rointe switch entity."""

    available_fn: Callable[[RointeDevice], bool] = lambda _: True
    icon_on: str | None = None
    icon_off: str | None = None


SWITCH_DESCRIPTIONS: tuple[RointeSwitchEntityDescription, ...] = (
    RointeSwitchEntityDescription(
        key="window_detection",
        name="Window Detection",
        icon="mdi:window-open-variant",
        field_name="windows_open_mode",
        value_fn=lambda device: device.windows_open_mode,
    ),
    RointeSwitchEntityDescription(
        key="silence_mode",
        name="Silence Mode",
        icon="mdi:volume-off",
        field_name="silence_mode",
        value_fn=lambda device: device.silence_mode,
    ),
    RointeSwitchEntityDescription(
        key="local_lock",
        name="Lock Local Controls",
        icon="mdi:lock",
        field_name="block_local",
        value_fn=lambda device: device.block_local,
    ),
    RointeSwitchEntityDescription(
        key="remote_lock",
        name="Lock Remote Controls",
        icon="mdi:lock-outline",
        field_name="block_remote",
        value_fn=lambda device: device.block_remote,
    ),
    RointeSwitchEntityDescription(
        key="presence_detection",
        name="Presence Detection",
        icon="mdi:motion-sensor",
        field_name="pir_mode",
        value_fn=lambda device: device.pir_mode,
    ),
    RointeSwitchEntityDescription(
        key="do_not_disturb",
        name="Do Not Disturb",
        icon="mdi:minus-circle",
        field_name="dont_disturb_mode",
        value_fn=lambda device: device.dont_disturb_mode,
    ),
    RointeSwitchEntityDescription(
        key="ice_mode",
        name="Frost Protection",
        icon="mdi:snowflake",
        field_name="ice_mode",
        value_fn=lambda device: device.ice_mode,
    ),
    RointeSwitchEntityDescription(
        key="user_mode",
        name="User Mode",
        icon="mdi:account-cog",
        field_name="user_mode",
        value_fn=lambda device: device.user_mode,
        available_fn=lambda device: device.user_mode_supported(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rointe switches from a config entry."""
    coordinator: RointeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[RointeSwitch] = []
    for device_id, device in coordinator.devices.items():
        for description in SWITCH_DESCRIPTIONS:
            if description.available_fn(device):
                entities.append(
                    RointeSwitch(device, coordinator, description)
                )

    async_add_entities(entities)


class RointeSwitch(RointeRadiatorEntity, SwitchEntity):
    """Representation of a Rointe switch."""

    entity_description: RointeSwitchEntityDescription

    def __init__(
        self,
        device: RointeDevice,
        coordinator: RointeDataUpdateCoordinator,
        description: RointeSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device, unique_id=device.id)
        self.entity_description = description
        self._attr_unique_id = f"{device.id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if self._radiator is None:
            return None
        return self.entity_description.value_fn(self._radiator)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if self._radiator is None:
            return False
        return (
            super().available
            and self._radiator.hass_available
            and self.entity_description.available_fn(self._radiator)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self._radiator is None:
            return

        await self.hass.async_add_executor_job(
            self._set_value, self._radiator, True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self._radiator is None:
            return

        await self.hass.async_add_executor_job(
            self._set_value, self._radiator, False
        )
        await self.coordinator.async_request_refresh()

    def _set_value(self, device: RointeDevice, value: bool) -> None:
        """Set the switch value via API."""
        api = self.coordinator.rointe_api
        field_name = self.entity_description.field_name

        # For Nexa devices, use WebSocket
        if api.use_nexa_ws:
            device_key = api._get_nexa_device_key(device)
            # Convert bool to int for Nexa API
            int_value = 1 if value else 0
            # Some fields use bool directly
            if field_name in ("ice_mode", "user_mode"):
                api._write_via_websocket(device_key, {field_name: value})
            else:
                api._write_via_websocket(device_key, {field_name: int_value})
