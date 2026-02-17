"""Support for Rointe Climate."""

from __future__ import annotations

from typing import Any

from .rointesdk.device import RointeDevice

from homeassistant.components.climate import (
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER, RointeCommand, RointeOperationMode, RointePreset
from .coordinator import RointeDataUpdateCoordinator
from .entity import RointeRadiatorEntity

AVAILABLE_HVAC_MODES: list[HVACMode] = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
AVAILABLE_PRESETS: list[str] = [
    RointePreset.ECO,
    RointePreset.COMFORT,
    RointePreset.ICE,
]

ROINTE_HASS_MAP = {
    RointePreset.ECO: PRESET_ECO,
    RointePreset.COMFORT: PRESET_COMFORT,
    RointePreset.ICE: RointePreset.ICE,
}

RADIATOR_TEMP_STEP = 0.5
RADIATOR_TEMP_MIN = 7.0
RADIATOR_TEMP_MAX = 40.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the radiator climate entity from the config entry."""
    coordinator: RointeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Register the Entity classes and platform on the coordinator.
    coordinator.add_entities_for_seen_keys(
        async_add_entities, [RointeHaClimate], "climate"
    )


class RointeHaClimate(RointeRadiatorEntity, ClimateEntity):
    """Climate entity."""

    _attr_icon = "mdi:radiator"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_target_temperature_step = RADIATOR_TEMP_STEP
    _attr_hvac_modes = AVAILABLE_HVAC_MODES
    _attr_preset_modes = AVAILABLE_PRESETS

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        radiator: RointeDevice,
        coordinator: RointeDataUpdateCoordinator,
    ) -> None:
        """Init the Climate entity."""

        super().__init__(coordinator, radiator, unique_id=radiator.id)

    @property
    def target_temperature(self) -> float | None:
        """Return the current target temperature or None if the device is off."""

        # Check if device is off
        if not self._radiator.power:
            return None

        # In AUTO mode, use the schedule-aware effective target temperature
        if self._radiator.mode == RointeOperationMode.AUTO:
            return self._radiator.get_effective_target_temperature()

        # In MANUAL mode, return the current temp setpoint
        return self._radiator.temp

    @property
    def current_temperature(self) -> float:
        """Get current temperature (Probe)."""
        return self._radiator.temp_probe

    @property
    def max_temp(self) -> float:
        """Max selectable temperature."""
        if self._radiator.user_mode_supported() and self._radiator.user_mode:
            return self._radiator.um_max_temp

        return RADIATOR_TEMP_MAX

    @property
    def min_temp(self) -> float:
        """Minimum selectable temperature."""
        if self._radiator.user_mode_supported() and self._radiator.user_mode:
            return self._radiator.um_min_temp

        return RADIATOR_TEMP_MIN

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        if not self._radiator.power:
            return HVACMode.OFF

        if self._radiator.mode == RointeOperationMode.AUTO:
            return HVACMode.AUTO

        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current HVAC action.

        Note: Firebase status_warming can be stale, so we derive the action
        from the temperature differential rather than trusting the device state.
        """

        # Forced to off, either on Manual or Auto mode.
        if not self._radiator.power:
            return HVACAction.OFF

        # Get the effective target temperature (schedule-aware in AUTO mode)
        target = self._radiator.get_effective_target_temperature()
        current = self._radiator.temp_probe

        # If current temp is at or above target, we're idle
        if current >= target:
            return HVACAction.IDLE

        # Target is above current temp - the radiator should be heating
        # Don't trust stale status_warming from Firebase; derive from temps
        return HVACAction.HEATING

    @property
    def preset_mode(self) -> str | None:
        """Convert the device's preset to HA preset modes.

        In AUTO mode, derives the preset from the current schedule slot.
        In MANUAL mode, uses the device's stored preset.
        """
        from .rointesdk.model import ScheduleMode

        # In AUTO mode, derive preset from schedule
        if self._radiator.mode == RointeOperationMode.AUTO:
            schedule_mode = self._radiator.get_current_schedule_mode()
            if schedule_mode == ScheduleMode.COMFORT:
                return PRESET_COMFORT
            elif schedule_mode == ScheduleMode.ECO:
                return PRESET_ECO
            elif schedule_mode == ScheduleMode.NONE:
                # "O" in schedule means frost/ice protection
                return RointePreset.ICE
            return None

        # In MANUAL mode, use the device's stored preset
        return ROINTE_HASS_MAP.get(self._radiator.preset)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""

        target_temperature = kwargs["temperature"]

        LOGGER.debug("Setting temperature to %s", target_temperature)

        if not RADIATOR_TEMP_MIN <= target_temperature <= RADIATOR_TEMP_MAX:
            raise HomeAssistantError(
                f"Invalid set_temperature value (must be in range {RADIATOR_TEMP_MIN}, {RADIATOR_TEMP_MAX}): {target_temperature}"
            )

        # Round to the nearest half value.
        rounded_temp = round(target_temperature * 2) / 2

        if not await self.device_manager.send_command(
            self._radiator, RointeCommand.SET_TEMP, rounded_temp
        ):
            raise HomeAssistantError(
                f"Failed to set temperature for {self._radiator.name}"
            )

        await self._signal_thermostat_update()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""

        LOGGER.debug("Setting HVAC mode to %s", hvac_mode)

        if not await self.device_manager.send_command(
            self._radiator, RointeCommand.SET_HVAC_MODE, hvac_mode
        ):
            raise HomeAssistantError(
                f"Failed to set HVAC mode for {self._radiator.name}"
            )

        await self._signal_thermostat_update()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        LOGGER.debug("Setting preset mode: %s", preset_mode)

        if not await self.device_manager.send_command(
            self._radiator, RointeCommand.SET_PRESET, preset_mode
        ):
            raise HomeAssistantError(
                f"Failed to set HVAC preset for {self._radiator.name}"
            )

        await self._signal_thermostat_update()

    async def _signal_thermostat_update(self):
        """Signal a radiator change."""

        # Update the data
        await self.coordinator.async_refresh()
