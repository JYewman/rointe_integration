"""Binary sensor platform for Rointe devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RointeDataUpdateCoordinator
from .rointe_entity import RointeRadiatorEntity
from .rointesdk.device import RointeDevice


@dataclass
class RointeBinarySensorRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[RointeDevice], bool]


@dataclass
class RointeBinarySensorEntityDescription(
    BinarySensorEntityDescription, RointeBinarySensorRequiredKeysMixin
):
    """Describes a Rointe binary sensor entity."""

    available_fn: Callable[[RointeDevice], bool] = lambda _: True


BINARY_SENSOR_DESCRIPTIONS: tuple[RointeBinarySensorEntityDescription, ...] = (
    RointeBinarySensorEntityDescription(
        key="window_open",
        name="Window Open",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda device: device.windows_open_status,
        available_fn=lambda device: device.windows_open_mode,
    ),
    RointeBinarySensorEntityDescription(
        key="boost_active",
        name="Boost Active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: device.boost_active,
    ),
    RointeBinarySensorEntityDescription(
        key="timer_active",
        name="Timer Active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: device.timer_mode,
    ),
    RointeBinarySensorEntityDescription(
        key="heating",
        name="Heating",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda device: device.status_warming == 2,
    ),
    RointeBinarySensorEntityDescription(
        key="connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda device: device.is_alive,
    ),
    RointeBinarySensorEntityDescription(
        key="local_lock",
        name="Local Controls Locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda device: device.block_local,
    ),
    RointeBinarySensorEntityDescription(
        key="remote_lock",
        name="Remote Controls Locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda device: device.block_remote,
    ),
    RointeBinarySensorEntityDescription(
        key="presence_mode",
        name="Presence Detection",
        device_class=BinarySensorDeviceClass.MOTION,
        value_fn=lambda device: device.pir_mode,
    ),
    RointeBinarySensorEntityDescription(
        key="pilot_wire",
        name="Pilot Wire Mode",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda device: device.pilot_mode,
    ),
    RointeBinarySensorEntityDescription(
        key="charging",
        name="Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda device: device.charging,
        available_fn=lambda device: device.type == "storage_heater",
    ),
    RointeBinarySensorEntityDescription(
        key="legionella",
        name="Legionella Protection Running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda device: device.legionella_status,
        available_fn=lambda device: device.type == "water_heater",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rointe binary sensors from a config entry."""
    coordinator: RointeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[RointeBinarySensor] = []
    for device_id, device in coordinator.devices.items():
        for description in BINARY_SENSOR_DESCRIPTIONS:
            if description.available_fn(device):
                entities.append(
                    RointeBinarySensor(device, coordinator, description)
                )

    async_add_entities(entities)


class RointeBinarySensor(RointeRadiatorEntity, BinarySensorEntity):
    """Representation of a Rointe binary sensor."""

    entity_description: RointeBinarySensorEntityDescription

    def __init__(
        self,
        device: RointeDevice,
        coordinator: RointeDataUpdateCoordinator,
        description: RointeBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device, unique_id=device.id)
        self.entity_description = description
        self._attr_unique_id = f"{device.id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
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
