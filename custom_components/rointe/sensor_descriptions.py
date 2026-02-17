"""Sensor descriptions for Rointe."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.typing import StateType

from .rointesdk.device import RointeDevice


@dataclass
class RointeSensorEntityDescriptionMixin:
    """Define a description mixin for Rointe sensor entities."""

    value_fn: Callable[[RointeDevice], StateType]
    last_reset_fn: Callable[[RointeDevice], datetime | None]


@dataclass
class RointeSensorEntityDescription(
    SensorEntityDescription, RointeSensorEntityDescriptionMixin
):
    """Define an object to describe Rointe sensor entities."""

    available_fn: Callable[[RointeDevice], bool] = lambda _: True
    attributes_fn: Callable[[RointeDevice], dict[str, Any]] | None = None


def _get_heating_status(device: RointeDevice) -> str:
    """Get human-readable heating status."""
    # Cross-check with temperature to avoid stale status_warming
    target = device.get_effective_target_temperature()
    if device.temp_probe >= target:
        return "idle"
    if device.status_warming == 2:
        return "heating"
    elif device.status_warming == 1:
        return "maintaining"
    else:
        return "idle"


def _get_effective_power(device: RointeDevice) -> float:
    """Get effective power usage, accounting for stale Firebase data."""
    # If device is off or target temp reached, power is 0
    if not device.power:
        return 0
    
    target = device.get_effective_target_temperature()
    # If current temp >= target, not heating (regardless of stale status_warming)
    if device.temp_probe >= target:
        return 0
    
    # Check energy_data first
    if device.energy_data and device.energy_data.effective_power > 0:
        return device.energy_data.effective_power
    
    # Use status_warming only if temp check says we should be heating
    if device.status_warming == 2:
        return device.nominal_effective_power
    elif device.status_warming == 1:
        return device.nominal_effective_power * 0.5
    
    return 0


def _get_schedule_status(device: RointeDevice) -> str:
    """Get current schedule block."""
    from .rointesdk import utils
    day_time = utils.now()
    day_of_week = day_time.weekday()
    hour_index = day_time.hour
    
    if not device.schedule or len(device.schedule) <= day_of_week:
        return "unknown"
    
    day_schedule = device.schedule.get(str(day_of_week), "")
    if len(day_schedule) <= hour_index:
        return "unknown"
    
    mode_char = day_schedule[hour_index]
    if mode_char == "C":
        return "comfort"
    elif mode_char == "E":
        return "eco"
    elif mode_char == "O":
        return "off"
    return "unknown"


SENSOR_DESCRIPTIONS = [
    # Current room temperature sensor (probe value).
    RointeSensorEntityDescription(
        key="current_temperature",
        name="Current Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda radiator: radiator.temp_probe,
        last_reset_fn=lambda radiator: None,
    ),
    # Surface temperature
    RointeSensorEntityDescription(
        key="surface_temperature",
        name="Surface Temperature",
        icon="mdi:radiator",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radiator: radiator.temp_surface if radiator.temp_surface > 0 else None,
        last_reset_fn=lambda radiator: None,
    ),
    # Floor temperature (if floor probe available)
    RointeSensorEntityDescription(
        key="floor_temperature",
        name="Floor Temperature",
        icon="mdi:floor-plan",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radiator: radiator.temp_floor if radiator.has_floor_probe else None,
        last_reset_fn=lambda radiator: None,
        available_fn=lambda radiator: radiator.has_floor_probe,
    ),
    # Target temperature
    RointeSensorEntityDescription(
        key="target_temperature",
        name="Target Temperature",
        icon="mdi:thermometer-check",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda radiator: radiator.temp,
        last_reset_fn=lambda radiator: None,
    ),
    # Energy usage in kWh (for Energy Dashboard)
    RointeSensorEntityDescription(
        key="energy",
        name="Energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda radiator: radiator.energy_data.kwh
        if radiator.energy_data
        else None,
        last_reset_fn=lambda radiator: None,  # HA handles resets for total_increasing
    ),
    # Effective power usage in W
    RointeSensorEntityDescription(
        key="power",
        name="Effective Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radiator: _get_effective_power(radiator),
        last_reset_fn=lambda radiator: None,
    ),
    # Nominal power
    RointeSensorEntityDescription(
        key="nominal_power",
        name="Nominal Power",
        icon="mdi:flash",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radiator: radiator.nominal_power,
        last_reset_fn=lambda radiator: None,
    ),
    # Heating status (idle/maintaining/heating)
    RointeSensorEntityDescription(
        key="heating_status",
        name="Heating Status",
        icon="mdi:fire",
        value_fn=lambda radiator: _get_heating_status(radiator),
        last_reset_fn=lambda radiator: None,
    ),
    # Schedule status (comfort/eco/off)
    RointeSensorEntityDescription(
        key="schedule_status",
        name="Schedule Status",
        icon="mdi:calendar-clock",
        value_fn=lambda radiator: _get_schedule_status(radiator),
        last_reset_fn=lambda radiator: None,
        available_fn=lambda radiator: radiator.mode == "auto",
    ),
    # WiFi signal strength
    RointeSensorEntityDescription(
        key="wifi_signal",
        name="WiFi Signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radiator: radiator.wifi_signal if radiator.wifi_signal != 0 else None,
        last_reset_fn=lambda radiator: None,
        attributes_fn=lambda radiator: {"ssid": radiator.wifi_ssid} if radiator.wifi_ssid else None,
    ),
    # Boost countdown
    RointeSensorEntityDescription(
        key="boost_time_remaining",
        name="Boost Time Remaining",
        icon="mdi:rocket-launch",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda radiator: radiator.boost_countdown if radiator.boost_active else 0,
        last_reset_fn=lambda radiator: None,
        available_fn=lambda radiator: radiator.boost_active,
    ),
    # Timer countdown
    RointeSensorEntityDescription(
        key="timer_time_remaining",
        name="Timer Time Remaining",
        icon="mdi:timer",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda radiator: radiator.timer_time if radiator.timer_mode else 0,
        last_reset_fn=lambda radiator: None,
        available_fn=lambda radiator: radiator.timer_mode,
    ),
    # Charge percentage (storage heaters)
    RointeSensorEntityDescription(
        key="charge_percentage",
        name="Charge Level",
        icon="mdi:battery-charging",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda radiator: radiator.charge_percentage,
        last_reset_fn=lambda radiator: None,
        available_fn=lambda radiator: radiator.type == "storage_heater",
    ),
    # Firmware version
    RointeSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda radiator: radiator.firmware_version,
        last_reset_fn=lambda radiator: None,
    ),
]
