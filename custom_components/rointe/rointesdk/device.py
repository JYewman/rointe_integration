"""Device data model."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .utils import get_product_by_type_version

from . import utils
from .dto import EnergyConsumptionData
from .model import RointeProduct, ScheduleMode


class RointeDevice:
    """Represent a Rointe device from the API."""

    id: str
    name: str
    serialnumber: str
    type: str

    # This represents the model of a particular product. Not the FW version.
    product_version: str

    firmware_version: Optional[str]
    latest_firmware_version: Optional[str]
    hardware_version: Optional[str]

    nominal_power: int
    nominal_effective_power: int
    power: bool

    # Describes the preset: ICE, ECO, Comfort, None
    preset: str
    mode: str

    temp: float
    temp_calc: float
    temp_probe: float
    temp_surface: float
    temp_floor: float

    # preset temperatures
    comfort_temp: float
    eco_temp: float
    ice_temp: float

    # User mode
    um_max_temp: float
    um_min_temp: float
    user_mode: bool
    ice_mode: bool

    # Schedule
    schedule: list[str]
    schedule_day: int
    schedule_hour: int

    energy_data: EnergyConsumptionData

    last_sync_datetime_app: datetime
    last_sync_datetime_device: datetime

    hass_available: bool

    # Nexa heating status (0=off, 1=maintaining, 2=active heating)
    status_warming: int

    # Connectivity
    is_alive: bool
    wifi_signal: int
    wifi_ssid: str

    # Boost mode
    boost_active: bool
    boost_countdown: int

    # Timer mode
    timer_mode: bool
    timer_time: int
    timer_temp: float

    # Window detection
    windows_open_mode: bool
    windows_open_status: bool

    # Control locks
    block_local: bool
    block_remote: bool

    # Silent/quiet mode
    silence_mode: bool

    # Do not disturb
    dont_disturb_mode: bool
    dont_disturb_start: int
    dont_disturb_end: int

    # Presence detection (PIR)
    pir_mode: bool

    # Display settings
    backlight: int
    ledbar_on: int

    # Pilot wire mode
    pilot_mode: bool

    # Floor probe
    has_floor_probe: bool
    use_floor_probe: bool

    # Legionella protection (for water heaters)
    legionella_mode: int
    legionella_status: bool

    # Charging (storage heaters)
    charging: bool
    charge_percentage: int

    # Raw data storage for debugging and flexibility
    _data: dict

    def __init__(
        self,
        device_id: str,
        device_info: dict,
        energy_data: EnergyConsumptionData,
        latest_fw: str | None,
    ) -> None:
        """Initialize the device from the rointe's json blob."""
        self.id = device_id
        self.type = device_info["data"]["type"]
        self.product_version = str.lower(device_info["data"]["product_version"])
        self.serialnumber = device_info["serialnumber"]
        self._data = device_info.get("data", {})
        self.update_data(device_info, energy_data, latest_fw)

    def update_data(
        self,
        device_info: dict,
        energy_data: EnergyConsumptionData,
        latest_fw: str | None,
    ) -> None:
        """Update the device data from a Json object."""

        data = device_info["data"]
        self._data = data  # Keep raw data for debugging
        firmware_data = device_info.get("firmware")

        self.name = data.get("name", "")
        self.nominal_power = int(data.get("nominal_power", 0))
        self.nominal_effective_power = int(
            data.get("nominal_effective_power", self.nominal_power)
        )
        power_val = data.get("power", False)
        power_int: int | None
        try:
            power_int = int(power_val)
        except (TypeError, ValueError):
            power_int = None
        status = data.get("status", "none")
        if status == "off":
            self.power = False
        elif power_int is not None:
            # Nexa uses 1=standby/off, 2=on/heating.
            self.power = power_int == 2
        else:
            self.power = bool(power_val)
        self.preset = status
        mode_val = data.get("mode", "manual")
        if mode_val in (0, "0"):
            self.mode = "manual"
        elif mode_val in (1, "1"):
            self.mode = "auto"
        else:
            self.mode = mode_val

        self.temp = float(data.get("temp", 0))
        self.temp_calc = float(data.get("temp_calc", self.temp))
        self.temp_probe = float(data.get("temp_probe", self.temp))

        self.comfort_temp = float(data.get("comfort", self.temp))
        self.eco_temp = float(data.get("eco", self.temp))
        self.ice_temp = float(data.get("ice", self.temp))

        # User mode settings are only valid for V2 radiators.
        if self.product_version == "v2":
            self.um_max_temp = float(data.get("um_max_temp", 0))
            self.um_min_temp = float(data.get("um_min_temp", 0))
            self.user_mode = bool(data.get("user_mode", False))
        else:
            self.um_max_temp = 0
            self.um_min_temp = 0
            self.user_mode = False

        self.ice_mode = bool(data.get("ice_mode", False))
        self.schedule = data.get("schedule", [])
        self.schedule_day = data.get("schedule_day", 0)
        self.schedule_hour = data.get("schedule_hour", 0)

        # Nexa status_warming: 0=off, 1=maintaining, 2=active heating
        self.status_warming = int(data.get("status_warming", 0))

        # Surface and floor temperatures
        self.temp_surface = float(data.get("temp_surface", 0))
        self.temp_floor = float(data.get("temp_floor", 0))

        # Connectivity
        self.is_alive = bool(data.get("is_alive", True))
        self.wifi_signal = int(data.get("wifisignal", 0))
        self.wifi_ssid = str(data.get("wifissid", ""))

        # Boost mode
        self.boost_active = bool(data.get("boost_active", False))
        self.boost_countdown = int(data.get("boost_countdown", 0))

        # Timer mode
        self.timer_mode = bool(data.get("timer_mode", False))
        self.timer_time = int(data.get("timer_time", 0))
        self.timer_temp = float(data.get("timer_temp", self.temp))

        # Window detection
        self.windows_open_mode = bool(data.get("windows_open_mode", False))
        self.windows_open_status = bool(data.get("windows_open_status", False))

        # Control locks
        self.block_local = bool(data.get("block_local", False))
        self.block_remote = bool(data.get("block_remote", False))

        # Silent/quiet mode
        self.silence_mode = bool(data.get("silence_mode", False))

        # Do not disturb
        self.dont_disturb_mode = bool(data.get("dont_disturb_mode", False))
        self.dont_disturb_start = int(data.get("dont_disturb_start", 0))
        self.dont_disturb_end = int(data.get("dont_disturb_end", 0))

        # Presence detection (PIR)
        self.pir_mode = bool(data.get("pir_mode", False))

        # Display settings
        self.backlight = int(data.get("backlight", 0))
        self.ledbar_on = int(data.get("ledbar_on", 0))

        # Pilot wire mode
        self.pilot_mode = bool(data.get("pilot_mode", False))

        # Floor probe
        self.has_floor_probe = bool(data.get("has_floor_probe", False))
        self.use_floor_probe = bool(data.get("use_floor_probe", False))

        # Legionella protection (for water heaters)
        self.legionella_mode = int(data.get("legionella_mode", 0))
        self.legionella_status = bool(data.get("legionella_status", False))

        # Charging (storage heaters)
        self.charging = bool(data.get("charging", False))
        self.charge_percentage = int(data.get("charge_percentage", 0))

        self.energy_data = energy_data

        if data.get("last_sync_datetime_app"):
            self.last_sync_datetime_app = datetime.fromtimestamp(
                int(data["last_sync_datetime_app"]) / 1000.0
            )
        else:
            self.last_sync_datetime_app = datetime.now()

        if data.get("last_sync_datetime_device"):
            self.last_sync_datetime_device = datetime.fromtimestamp(
                int(data["last_sync_datetime_device"]) / 1000.0
            )
        else:
            self.last_sync_datetime_device = datetime.now()

        if firmware_data:
            self.firmware_version = str(firmware_data.get("firmware_version_device") or 
                                        firmware_data.get("firmware_version") or "")
            self.hardware_version = str(firmware_data.get("hardware_version") or "")
        else:
            self.firmware_version = None
            self.hardware_version = None

        self.latest_firmware_version = latest_fw
        self.hass_available = True

    def get_current_schedule_mode(self) -> ScheduleMode:
        """Return the current schedule mode for the device.

        Returns C for Comfort, E for Eco, O for no-schedule.
        Handles both list format (legacy) and dict format (Nexa API).
        """
        day_time = utils.now()
        day_of_week = day_time.weekday()  # 0 is Monday
        hour_index = day_time.hour

        # Guard against empty schedule
        if not self.schedule:
            return ScheduleMode.NONE

        # Handle dict format (Nexa API returns {"0": "CCCEEE...", "1": "...", ...})
        if isinstance(self.schedule, dict):
            day_key = str(day_of_week)
            if day_key not in self.schedule:
                return ScheduleMode.NONE
            day_schedule = self.schedule[day_key]
        # Handle list format (legacy API)
        elif isinstance(self.schedule, list):
            if len(self.schedule) <= day_of_week:
                return ScheduleMode.NONE
            day_schedule = self.schedule[day_of_week]
        else:
            return ScheduleMode.NONE

        # Validate day_schedule
        if not day_schedule or not isinstance(day_schedule, str):
            return ScheduleMode.NONE
        if len(day_schedule) <= hour_index:
            return ScheduleMode.NONE

        current_mode = day_schedule[hour_index]

        if current_mode == "C":
            return ScheduleMode.COMFORT
        elif current_mode == "E":
            return ScheduleMode.ECO
        else:
            return ScheduleMode.NONE

    def get_effective_target_temperature(self) -> float:
        """Return the effective target temperature based on current mode and schedule.

        In AUTO mode, returns the temperature based on the current schedule slot.
        In MANUAL mode, returns the current temp setpoint.
        """
        # If in manual mode, just return the current temp setpoint
        if self.mode == "manual":
            return self.temp

        # In auto mode, determine target from schedule
        schedule_mode = self.get_current_schedule_mode()

        if schedule_mode == ScheduleMode.COMFORT:
            return self.comfort_temp
        elif schedule_mode == ScheduleMode.ECO:
            return self.eco_temp
        elif schedule_mode == ScheduleMode.NONE:
            # "O" in schedule means off/frost protection
            return self.ice_temp

        # Fallback to current temp setpoint
        return self.temp

    @property
    def heating(self) -> bool:
        """Return True if the device is actively heating.

        Based on status_warming: 0=off, 1=maintaining, 2=active heating.
        """
        return self.status_warming == 2

    @property
    def target_temperature(self) -> float:
        """Return the current target temperature (alias for get_effective_target_temperature)."""
        return self.get_effective_target_temperature()

    def user_mode_supported(self) -> bool:
        """Return True if this device supports user mode."""
        return self.product_version == "v2"

    @property
    def rointe_product(self) -> RointeProduct | None:
        """Return the product name."""
        return get_product_by_type_version(self.type, self.product_version)
