"""Number platform for Rointe devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RointeDataUpdateCoordinator
from .rointe_entity import RointeRadiatorEntity
from .rointesdk.device import RointeDevice


@dataclass
class RointeNumberRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[RointeDevice], float]
    field_name: str  # The API field name to write


@dataclass
class RointeNumberEntityDescription(
    NumberEntityDescription, RointeNumberRequiredKeysMixin
):
    """Describes a Rointe number entity."""

    available_fn: Callable[[RointeDevice], bool] = lambda _: True
    min_value_fn: Callable[[RointeDevice], float] = lambda _: 7
    max_value_fn: Callable[[RointeDevice], float] = lambda _: 30


NUMBER_DESCRIPTIONS: tuple[RointeNumberEntityDescription, ...] = (
    RointeNumberEntityDescription(
        key="comfort_temperature",
        name="Comfort Temperature",
        icon="mdi:sun-thermometer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=7,
        native_max_value=30,
        native_step=0.5,
        mode=NumberMode.SLIDER,
        field_name="comfort",
        value_fn=lambda device: device.comfort_temp,
        min_value_fn=lambda device: device.um_min_temp if device.user_mode else 7,
        max_value_fn=lambda device: device.um_max_temp if device.user_mode else 30,
    ),
    RointeNumberEntityDescription(
        key="eco_temperature",
        name="Eco Temperature",
        icon="mdi:leaf",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=7,
        native_max_value=30,
        native_step=0.5,
        mode=NumberMode.SLIDER,
        field_name="eco",
        value_fn=lambda device: device.eco_temp,
        min_value_fn=lambda device: device.um_min_temp if device.user_mode else 7,
        max_value_fn=lambda device: device.um_max_temp if device.user_mode else 30,
    ),
    RointeNumberEntityDescription(
        key="ice_temperature",
        name="Frost Protection Temperature",
        icon="mdi:snowflake-thermometer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=15,
        native_step=0.5,
        mode=NumberMode.SLIDER,
        field_name="ice",
        value_fn=lambda device: device.ice_temp,
    ),
    RointeNumberEntityDescription(
        key="max_temperature",
        name="Maximum Temperature Limit",
        icon="mdi:thermometer-chevron-up",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=15,
        native_max_value=35,
        native_step=1,
        mode=NumberMode.BOX,
        field_name="um_max_temp",
        value_fn=lambda device: device.um_max_temp,
        available_fn=lambda device: device.user_mode_supported(),
    ),
    RointeNumberEntityDescription(
        key="min_temperature",
        name="Minimum Temperature Limit",
        icon="mdi:thermometer-chevron-down",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=20,
        native_step=1,
        mode=NumberMode.BOX,
        field_name="um_min_temp",
        value_fn=lambda device: device.um_min_temp,
        available_fn=lambda device: device.user_mode_supported(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rointe number entities from a config entry."""
    coordinator: RointeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[RointeNumber] = []
    for device_id, device in coordinator.devices.items():
        for description in NUMBER_DESCRIPTIONS:
            if description.available_fn(device):
                entities.append(
                    RointeNumber(device, coordinator, description)
                )

    async_add_entities(entities)


class RointeNumber(RointeRadiatorEntity, NumberEntity):
    """Representation of a Rointe number entity."""

    entity_description: RointeNumberEntityDescription

    def __init__(
        self,
        device: RointeDevice,
        coordinator: RointeDataUpdateCoordinator,
        description: RointeNumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, device, unique_id=device.id)
        self.entity_description = description
        self._attr_unique_id = f"{device.id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if self._radiator is None:
            return None
        return self.entity_description.value_fn(self._radiator)

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        if self._radiator is None:
            return self.entity_description.native_min_value or 7
        return self.entity_description.min_value_fn(self._radiator)

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        if self._radiator is None:
            return self.entity_description.native_max_value or 30
        return self.entity_description.max_value_fn(self._radiator)

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

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        if self._radiator is None:
            return

        await self.hass.async_add_executor_job(
            self._set_value, self._radiator, value
        )
        await self.coordinator.async_request_refresh()

    def _set_value(self, device: RointeDevice, value: float) -> None:
        """Set the value via API."""
        api = self.coordinator.rointe_api
        field_name = self.entity_description.field_name

        # For Nexa devices, use WebSocket
        if api.use_nexa_ws:
            device_key = api._get_nexa_device_key(device)
            api._write_via_websocket(device_key, {field_name: value})
