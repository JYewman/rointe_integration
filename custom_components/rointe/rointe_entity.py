"""Rointe devices entity model."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ROINTE_MANUFACTURER

if TYPE_CHECKING:
    from .coordinator import RointeDataUpdateCoordinator
    from .device_manager import RointeDeviceManager
    from .rointesdk.device import RointeDevice


class RointeHAEntity(CoordinatorEntity):
    """Rointe entity base class."""

    def __init__(
        self, coordinator: "RointeDataUpdateCoordinator", name: str, unique_id: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"rointe-{unique_id}"
        self._attr_name = name

    @property
    def device_manager(self) -> "RointeDeviceManager":
        """Return the device manager."""
        return self.coordinator.device_manager


class RointeRadiatorEntity(CoordinatorEntity):
    """Base class for entities that support a Radiator device.

    This supports two initialization patterns:
    1. Pass device_id only (new pattern) - device is looked up from coordinator
    2. Pass radiator object with name/unique_id (legacy pattern)
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: "RointeDataUpdateCoordinator",
        device_id_or_radiator: str | "RointeDevice",
        name: str | None = None,
        unique_id: str | None = None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

        # Support both patterns
        if isinstance(device_id_or_radiator, str):
            # New pattern: device_id only
            self._device_id = device_id_or_radiator
            self._radiator = coordinator.devices.get(device_id_or_radiator)
        else:
            # Legacy pattern: radiator object
            self._radiator = device_id_or_radiator
            self._device_id = device_id_or_radiator.id

        if name is not None:
            self._attr_name = name
        if unique_id is not None:
            self._attr_unique_id = f"rointe-{unique_id}"

    @property
    def device(self) -> "RointeDevice | None":
        """Return the current device data."""
        return self.coordinator.devices.get(self._device_id)

    @property
    def device_manager(self) -> "RointeDeviceManager":
        """Return the device manager."""
        return self.coordinator.device_manager

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        device = self.device or self._radiator
        if device is None:
            return DeviceInfo(identifiers={(DOMAIN, self._device_id)})

        if device.rointe_product:
            product_name = device.rointe_product.product_name
        else:
            product_name = (
                f"{device.type.capitalize()} {device.product_version.capitalize()}"
            )

        return DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            manufacturer=ROINTE_MANUFACTURER,
            name=device.name,
            model=product_name,
            sw_version=device.firmware_version,
            hw_version=getattr(device, 'hardware_version', None),
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        device = self.device or self._radiator
        if device is None:
            return False
        return super().available and device.hass_available
