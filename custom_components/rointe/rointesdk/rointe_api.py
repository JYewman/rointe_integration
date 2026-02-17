"""Rointe API Client"""

from __future__ import annotations

from collections import namedtuple
import json
import logging
import ssl
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from requests.exceptions import RequestException

from .device import RointeDevice, ScheduleMode
from .dto import EnergyConsumptionData
from .settings import (
    AUTH_ACCT_INFO_URL,
    AUTH_HOST,
    AUTH_REFRESH_ENDPOINT,
    AUTH_TIMEOUT_SECONDS,
    AUTH_VERIFY_URL,
    ENERGY_STATS_MAX_TRIES,
    FIREBASE_APP_KEY,
    FIREBASE_DEFAULT_URL,
    FIREBASE_DEVICE_DATA_PATH_BY_ID,
    FIREBASE_DEVICE_ENERGY_PATH_BY_ID,
    FIREBASE_DEVICES_PATH_BY_ID,
    FIREBASE_GLOBAL_SETTINGS_PATH,
    FIREBASE_INSTALLATIONS_PATH,
    NEXA_FIREBASE_APP_KEY,
    NEXA_FIREBASE_AUTH_URL,
    NEXA_FIREBASE_DEFAULT_URL,
    NEXA_FIREBASE_WS_URL,
    NEXA_INSTALLATIONS_URL,
    NEXA_LOGIN_URL,
    NEXA_STATISTICS_URL,
)
from .utils import build_update_map

ApiResponse = namedtuple("ApiResponse", ["success", "data", "error_message"])
LOGGER = logging.getLogger(__name__)


class RointeAPI:
    """Rointe API Communication. Handles low level calls to the API."""

    def __init__(self, username: str, password: str, api_type: Optional[str] = None):
        """Initializes the API"""

        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.api_type = (api_type or "auto").lower()

        self.refresh_token = None
        self.auth_token = None
        self.auth_token_expire_date: Optional[datetime] = None
        self.local_id = None
        self.nexa_token: Optional[str] = None
        self.nexa_refresh_token: Optional[str] = None
        self.firebase_base_url = FIREBASE_DEFAULT_URL
        self.firebase_ws_url: Optional[str] = None
        self.firebase_app_key = FIREBASE_APP_KEY
        self.use_nexa_ws = False
        self._nexa_device_cache: Dict[str, Dict[str, Any]] = {}
        self._nexa_zone_device_map: Dict[str, List[str]] = {}  # zone_id -> [device_serials]
        self._nexa_device_zone_map: Dict[str, str] = {}  # device_serial -> zone_id
        self._nexa_installation_energy: Optional[Dict[str, Any]] = None  # cached stats

    def initialize_authentication(self) -> ApiResponse:
        """
        Initializes the refresh token and cleans
        the original credentials.
        """

        LOGGER.debug("Initializing authentication (api_type=%s)", self.api_type)
        login_data: ApiResponse = self._login_user()

        if not login_data.success:
            LOGGER.error("Authentication failed: %s", login_data.error_message)
            self.auth_token = None
            self.refresh_token = None
            return login_data

        self.auth_token = login_data.data["auth_token"]
        self.refresh_token = login_data.data["refresh_token"]
        self.auth_token_expire_date = login_data.data["expires"]
        self.local_id = login_data.data["local_id"]
        self.nexa_token = login_data.data.get("nexa_token")
        self.nexa_refresh_token = login_data.data.get("nexa_refresh_token")
        self.firebase_base_url = login_data.data.get(
            "firebase_base_url", FIREBASE_DEFAULT_URL
        )
        self.firebase_ws_url = login_data.data.get("firebase_ws_url")
        self.firebase_app_key = login_data.data.get("firebase_app_key", FIREBASE_APP_KEY)
        self.use_nexa_ws = bool(login_data.data.get("use_nexa_ws", False))
        LOGGER.debug(
            "Authentication complete. Nexa=%s, firebase_base_url=%s",
            self.use_nexa_ws,
            self.firebase_base_url,
        )

        self._clean_credentials()

        return ApiResponse(True, None, None)

    def _clean_credentials(self) -> None:
        """Cleans authentication values"""
        self.username = None
        self.password = None

    def is_logged_in(self) -> bool:
        """Check if the login was successful."""
        return self.auth_token is not None and self.refresh_token is not None

    def _ensure_valid_auth(self) -> bool:
        """Ensure there is a valid authentication token present."""

        now = datetime.now()

        if not self.auth_token or (
            self.auth_token_expire_date and self.auth_token_expire_date < now
        ):
            if not self._refresh_token():
                return False

        return True

    def _refresh_token(self) -> bool:
        """Refreshes authentication."""

        payload = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}

        try:
            response = requests.post(
                f"{AUTH_REFRESH_ENDPOINT}?key={self.firebase_app_key}",
                data=payload,
                timeout=AUTH_TIMEOUT_SECONDS,
            )
        except RequestException:
            return False

        if not response:
            return False

        if response.status_code != 200:
            return False

        response_json = response.json()

        if not response_json or "id_token" not in response_json:
            return False

        self.auth_token = response_json["id_token"]
        self.auth_token_expire_date = datetime.now() + timedelta(
            seconds=int(response_json["expires_in"])
        )
        self.refresh_token = response_json["refresh_token"]

        return True

    def _login_user(self) -> ApiResponse:
        """Log the user in."""

        if self.api_type == "nexa":
            return self._login_user_nexa()

        payload = {
            "email": self.username,
            "password": self.password,
            "returnSecureToken": True,
        }

        try:
            response = requests.post(
                f"{AUTH_HOST}{AUTH_VERIFY_URL}?key={FIREBASE_APP_KEY}",
                data=payload,
                timeout=AUTH_TIMEOUT_SECONDS,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response.status_code != 200:
            if self.api_type == "rointe":
                if response.status_code == 400:
                    return ApiResponse(
                        False,
                        None,
                        "Authentication returned 400 (Bad Request)",
                    )
                return ApiResponse(
                    False, None, "Authentication returned: " + str(response.status_code)
                )
            LOGGER.debug(
                "Legacy auth failed (status=%s), attempting Nexa login",
                response.status_code,
            )
            nexa_response = self._login_user_nexa()
            if nexa_response.success:
                return nexa_response
            if response.status_code == 400:
                return ApiResponse(
                    False,
                    None,
                    "Authentication returned 400 (Bad Request)",
                )
            return ApiResponse(
                False, None, "Authentication returned: " + str(response.status_code)
            )

        response_json = response.json()

        if not response_json or "idToken" not in response_json:
            return ApiResponse(
                False, None, "Authentication returned invalid or empty response"
            )

        data = {
            "auth_token": response_json["idToken"],
            "expires": datetime.now()
            + timedelta(seconds=int(response_json["expiresIn"])),
            "refresh_token": response_json["refreshToken"],
            "local_id": response_json["localId"],
            "firebase_base_url": FIREBASE_DEFAULT_URL,
            "firebase_app_key": FIREBASE_APP_KEY,
            "use_nexa_ws": False,
        }

        return ApiResponse(True, data, None)

    def _login_user_nexa(self) -> ApiResponse:
        """Log the user in via Nexa API, then authenticate with Firebase."""

        LOGGER.debug("Attempting Nexa login")
        try:
            response = requests.post(
                NEXA_LOGIN_URL,
                json={
                    "email": self.username,
                    "password": self.password,
                    "push": "",
                    "migrate": False,
                },
                timeout=AUTH_TIMEOUT_SECONDS,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response.status_code != 200:
            LOGGER.error("Nexa login failed: %s", response.status_code)
            return ApiResponse(
                False, None, f"Nexa login returned {response.status_code}"
            )

        try:
            response_json = response.json()
            LOGGER.debug("Nexa login response keys: %s", list(response_json.keys()))
            if isinstance(response_json.get("data"), dict):
                LOGGER.debug(
                    "Nexa login data keys: %s", list(response_json["data"].keys())
                )
            user_id = response_json["data"]["user"]["id"]
            token_block = response_json["data"].get("token", response_json["data"])
            if isinstance(token_block, dict):
                nexa_token = token_block.get("accessToken") or token_block.get(
                    "access_token"
                )
            else:
                nexa_token = None
            if not nexa_token:
                nexa_token = response_json["data"].get("token")
            nexa_refresh_token = response_json["data"].get("refreshToken")
        except (KeyError, TypeError, ValueError):
            LOGGER.error("Nexa login response missing user id")
            return ApiResponse(False, None, "Invalid Nexa login response")

        try:
            firebase_response = requests.post(
                f"{NEXA_FIREBASE_AUTH_URL}?key={NEXA_FIREBASE_APP_KEY}",
                json={
                    "returnSecureToken": True,
                    "email": f"{user_id}@rointe.com",
                    "password": user_id,
                    "clientType": "CLIENT_TYPE_WEB",
                },
                timeout=AUTH_TIMEOUT_SECONDS,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if firebase_response.status_code != 200:
            LOGGER.error(
                "Nexa Firebase auth failed: %s", firebase_response.status_code
            )
            return ApiResponse(
                False,
                None,
                f"Nexa Firebase auth returned {firebase_response.status_code}",
            )

        firebase_json = firebase_response.json()
        if not firebase_json or "idToken" not in firebase_json:
            LOGGER.error("Nexa Firebase auth response missing token")
            return ApiResponse(False, None, "Nexa Firebase auth returned no token")

        LOGGER.debug("Nexa Firebase auth success")
        if nexa_token:
            LOGGER.debug("Nexa token length: %s", len(nexa_token))
        if nexa_refresh_token:
            LOGGER.debug("Nexa refresh token length: %s", len(nexa_refresh_token))
        data = {
            "auth_token": firebase_json["idToken"],
            "expires": datetime.now()
            + timedelta(seconds=int(firebase_json["expiresIn"])),
            "refresh_token": firebase_json["refreshToken"],
            "local_id": firebase_json["localId"],
            "nexa_token": nexa_token,
            "nexa_refresh_token": nexa_refresh_token,
            "firebase_base_url": NEXA_FIREBASE_DEFAULT_URL,
            "firebase_ws_url": NEXA_FIREBASE_WS_URL,
            "firebase_app_key": NEXA_FIREBASE_APP_KEY,
            "use_nexa_ws": True,
        }

        return ApiResponse(True, data, None)

    def get_local_id(self) -> ApiResponse:
        """Retrieve user local_id value."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        payload = {"idToken": self.auth_token}

        try:
            response = requests.post(
                f"{AUTH_HOST}{AUTH_ACCT_INFO_URL}?key={self.firebase_app_key}",
                data=payload,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response is None:
            return ApiResponse(
                False, None, "No response from API call to get_local_id()"
            )

        if response.status_code != 200:
            return ApiResponse(
                False, None, f"get_local_id() returned {response.status_code}"
            )

        response_json = response.json()

        return ApiResponse(True, response_json["users"][0]["localId"], None)

    def get_installation_devices(self, installation_id: str) -> ApiResponse:
        """Retrieve all devices present in an installation."""
        installation_response = self.get_installation_by_id(installation_id)

        if not installation_response.success:
            return installation_response

        data = installation_response.data
        if self.use_nexa_ws:
            LOGGER.debug(
                "Nexa installation data type=%s keys=%s",
                type(data).__name__,
                list(data.keys()) if isinstance(data, dict) else None,
            )
            zones = None
            if isinstance(data, dict) and "zones" in data:
                zones = data.get("zones")
            elif isinstance(data, dict) and "rooms" in data:
                zones = data.get("rooms")
            else:
                zones = data
            devices = self._extract_devices_any(zones)
            unique_devices = list(dict.fromkeys(devices))
            LOGGER.debug(
                "Nexa installation devices found=%s sample=%s",
                len(unique_devices),
                unique_devices[:5],
            )
            return ApiResponse(True, unique_devices, None)

        detected_devices: List[str] = []
        for zone_key in data["zones"]:
            detected_devices.extend(self._extract_devices(data["zones"].get(zone_key)))

        return ApiResponse(True, detected_devices, None)

    def _extract_devices(self, zone_data: dict[str, Any]) -> List[str]:
        """Parses a single zone block recursively."""

        if not zone_data:
            return []

        zone_devices: List[str] = []

        if devices := zone_data.get("devices"):
            zone_devices.extend(list(devices.keys()))

        if sub_zones := zone_data.get("zones"):
            for sub_zone_key in sub_zones:
                zone_devices.extend(self._extract_devices(sub_zones.get(sub_zone_key)))

        return zone_devices

    def _extract_devices_any(self, zone_data: Any) -> List[str]:
        """Parse devices from dict/list structures (Nexa)."""

        if not zone_data:
            return []

        devices: List[str] = []

        if isinstance(zone_data, list):
            for item in zone_data:
                devices.extend(self._extract_devices_any(item))
            return devices

        if isinstance(zone_data, dict):
            devices_block = (
                zone_data.get("devices")
                or zone_data.get("radiators")
                or zone_data.get("items")
            )
            if isinstance(devices_block, dict):
                for dev_id, dev_info in devices_block.items():
                    if isinstance(dev_info, dict):
                        self._cache_nexa_device(dev_id, dev_info)
                devices.extend(list(devices_block.keys()))
            elif isinstance(devices_block, list):
                for dev in devices_block:
                    if not isinstance(dev, dict):
                        continue
                    dev_id = (
                        dev.get("id")
                        or dev.get("_id")
                        or dev.get("uuid")
                        or dev.get("device_id")
                    )
                    if dev_id:
                        self._cache_nexa_device(dev_id, dev)
                        devices.append(dev_id)

            sub_zones = zone_data.get("zones") or zone_data.get("rooms")
            devices.extend(self._extract_devices_any(sub_zones))

        return devices

    def _cache_nexa_device(self, device_id: str, dev: Dict[str, Any]) -> None:
        """Cache Nexa device metadata for later use."""

        if not device_id or device_id in self._nexa_device_cache:
            return
        cached = {
            "id": device_id,
            "name": dev.get("name"),
            "serialNumber": dev.get("serialNumber"),
        }
        self._nexa_device_cache[device_id] = cached

    def get_installation_by_id(self, installation_id: str) -> ApiResponse:
        """Retrieve a specific installation by ID."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        if self.use_nexa_ws:
            nexa_response = self._get_installation_by_id_nexa(installation_id)
            return nexa_response

        args = {
            "auth": self.auth_token,
            "orderBy": '"userid"',
            "equalTo": f'"{self.local_id}"',
        }

        url = f"{self.firebase_base_url}{FIREBASE_INSTALLATIONS_PATH}"

        try:
            response = requests.get(url, params=args)
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response is None:
            return ApiResponse(
                False, None, "No response from API in get_installation_by_id()"
            )

        if response.status_code != 200:
            return ApiResponse(
                False, None, f"get_installation_by_id() returned {response.status_code}"
            )

        reponse_json = response.json()

        if len(reponse_json) == 0 or installation_id not in reponse_json:
            return ApiResponse(False, None, "No Rointe installation found.")

        return ApiResponse(True, reponse_json[installation_id], None)

    def get_latest_firmware(self) -> ApiResponse:
        """Retrieves the latest firmware available for each device type.

        Note: This endpoint doesn't exist for Nexa users, so we return empty for them.
        """

        # Nexa doesn't have a global_settings endpoint - skip firmware check
        if self.use_nexa_ws:
            LOGGER.debug("Skipping firmware check for Nexa (endpoint not available)")
            return ApiResponse(True, {}, None)

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        url = f"{self.firebase_base_url}{FIREBASE_GLOBAL_SETTINGS_PATH}"
        args = {"auth": self.auth_token}

        try:
            response = requests.get(
                url,
                params=args,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response is None:
            return ApiResponse(
                False, None, "No response from API in get_latest_firmware()"
            )

        if response.status_code != 200:
            return ApiResponse(
                False, None, f"get_latest_firmware() returned {response.status_code}"
            )

        data = response.json()

        if len(data) == 0:
            return ApiResponse(False, None, "Global Settings is empty.")

        return ApiResponse(True, build_update_map(data), None)

    def get_installations(self) -> ApiResponse:
        """Retrieve the client's installations."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        if self.use_nexa_ws:
            nexa_response = self._get_installations_nexa()
            return nexa_response

        args = {
            "auth": self.auth_token,
            "orderBy": '"userid"',
            "equalTo": f'"{self.local_id}"',
        }
        url = f"{self.firebase_base_url}{FIREBASE_INSTALLATIONS_PATH}"

        try:
            response = requests.get(url, params=args)
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response is None:
            return ApiResponse(
                False, None, "No response from API in get_installations()"
            )

        if response.status_code != 200:
            return ApiResponse(
                False, None, f"get_installations() returned {response.status_code}"
            )

        reponse_json = response.json()

        if len(reponse_json) == 0:
            return ApiResponse(False, None, "No Rointe installations found.")

        installations = {}

        for key in reponse_json.keys():
            installations[key] = reponse_json[key]["location"]

        return ApiResponse(True, installations, None)

    def get_device(self, device_id: str) -> ApiResponse:
        """Retrieve device data."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        args = {"auth": self.auth_token}
        if self.use_nexa_ws:
            LOGGER.debug("Nexa get_device id=%s", device_id)
            meta = self._nexa_device_cache.get(device_id, {})
            serial = meta.get("serialNumber")
            paths = []
            if serial:
                paths.extend((f"/devices/{serial}/data", f"/devices/{serial}"))
            paths.extend((f"/devices/{device_id}/data", f"/devices/{device_id}"))
            for path in paths:
                ws_data = self._read_via_websocket(path)
                if ws_data is None:
                    continue
                if isinstance(ws_data, dict):
                    if "data" in ws_data:
                        return ApiResponse(True, ws_data, None)
                    if meta:
                        LOGGER.debug(
                            "Nexa device cache hit for %s: %s",
                            device_id,
                            list(meta.keys()),
                        )
                    data_block = dict(ws_data)
                    if meta.get("name") and "name" not in data_block:
                        data_block["name"] = meta.get("name")
                    result = {"data": data_block}
                    if meta.get("serialNumber"):
                        result["serialnumber"] = meta.get("serialNumber")
                    firmware_data = None
                    if serial:
                        firmware_data = self._read_via_websocket(
                            f"/devices/{serial}/firmware"
                        )
                    if isinstance(firmware_data, dict):
                        if (
                            "firmware_version_device" not in firmware_data
                            and "firmware_version" in firmware_data
                        ):
                            firmware_data["firmware_version_device"] = firmware_data[
                                "firmware_version"
                            ]
                        result["firmware"] = firmware_data
                    return ApiResponse(True, result, None)

            LOGGER.error("Nexa get_device websocket read failed for %s", device_id)
            return ApiResponse(False, None, "WebSocket read failed")

        try:
            response = requests.get(
                "{}{}".format(
                    self.firebase_base_url,
                    FIREBASE_DEVICES_PATH_BY_ID.format(device_id),
                ),
                params=args,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response is None:
            return ApiResponse(False, None, "No response from API in get_device()")

        if response.status_code != 200:
            if self.use_nexa_ws:
                LOGGER.error(
                    "Nexa get_device failed: status=%s response=%s",
                    response.status_code,
                    response.text[:200],
                )
            return ApiResponse(
                False, None, f"get_device() returned {response.status_code}"
            )

        return ApiResponse(True, response.json(), None)

    def get_latest_energy_stats(
        self, device_id: str, installation_id: Optional[str] = None
    ) -> ApiResponse:
        """Retrieve the latest energy consumption values."""

        # For Nexa devices, use the REST API statistics endpoint
        if self.use_nexa_ws:
            if not installation_id:
                return ApiResponse(
                    False, None, "Installation ID required for Nexa energy stats"
                )
            # Map device_id to serial number if needed
            device_serial = device_id
            cached = self._nexa_device_cache.get(device_id, {})
            if cached.get("serialNumber"):
                device_serial = cached["serialNumber"]
            return self.get_device_energy_from_nexa_stats(device_serial, installation_id)

        result: ApiResponse
        now = datetime.now()

        # Attempt to retrieve the latest value. If not found, go back one hour. Max 5 tries.
        attempts = ENERGY_STATS_MAX_TRIES
        target_date = now.replace(
            minute=0, second=0, microsecond=0
        )  # Strip minutes, seconds and microseconds.

        while attempts > 0:
            result = self._retrieve_hour_energy_stats(
                device_id, target_date
            )

            if result.error_message == "No energy stats found.":
                # Try again.
                attempts = attempts - 1
                target_date = target_date - timedelta(hours=1)
            else:
                # It's either a success or an error message, return the ApiResponse.
                return result

        return ApiResponse(False, None, "Max tries exceeded.")

    def _retrieve_hour_energy_stats(
        self, device_id: str, target_date: datetime
    ) -> ApiResponse:
        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        # Sample URL /history_statistics/device_id/daily/2022/01/21/energy/010000.json
        args = {"auth": self.auth_token}
        url = "{}{}{}/energy/{}0000.json".format(
            self.firebase_base_url,
            FIREBASE_DEVICE_ENERGY_PATH_BY_ID.format(device_id),
            target_date.strftime("%Y/%m/%d"),
            target_date.strftime("%H"),
        )

        try:
            response = requests.get(url, params=args)
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response is None:
            return ApiResponse(
                False, None, "No response from API in _retrieve_hour_energy_stats()"
            )

        if response.status_code != 200:
            return ApiResponse(
                False,
                None,
                f"_retrieve_hour_energy_stats() returned {response.status_code}",
            )

        response_json = response.json()

        if not response_json or len(response_json) == 0:
            return ApiResponse(False, None, "No energy stats found.")

        data = EnergyConsumptionData(
            created=datetime.now(),
            start=target_date,
            end=target_date + timedelta(hours=1),
            kwh=float(response_json["kw_h"]),
            effective_power=float(response_json["effective_power"]),
        )

        return ApiResponse(True, data, None)

    def set_device_temp(self, device: RointeDevice, new_temp: float) -> ApiResponse:
        """Set the device target temperature."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        device_id = device.id
        if self.use_nexa_ws:
            device_key = self._get_nexa_device_key(device)
            body = {"temp": new_temp, "mode": 0, "power": 2, "status": "none"}
            LOGGER.debug("Nexa set temp: %s -> %s", device_key, body)
            return self._write_via_websocket(device_key, body)

        args = {"auth": self.auth_token}
        body = {"temp": new_temp, "mode": "manual", "power": True}

        url = "{}{}".format(
            self.firebase_base_url, FIREBASE_DEVICE_DATA_PATH_BY_ID.format(device_id)
        )

        return self._send_patch_request(url, args, body)

    def set_device_preset(self, device: RointeDevice, preset_mode: str) -> ApiResponse:
        """Set the preset."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        device_id = device.id
        if self.use_nexa_ws:
            device_key = self._get_nexa_device_key(device)
            if preset_mode == "comfort":
                target_temp = device.comfort_temp
            elif preset_mode == "eco":
                target_temp = device.eco_temp
            elif preset_mode == "ice":
                target_temp = device.ice_temp
            else:
                return ApiResponse(False, None, f"Invalid preset {preset_mode}.")

            body = {"temp": target_temp, "mode": 0, "power": 2, "status": "none"}
            LOGGER.debug("Nexa set preset: %s -> %s", device_key, body)
            return self._write_via_websocket(device_key, body)

        args = {"auth": self.auth_token}
        body: Dict[str, Any] = {}

        url = "{}{}".format(
            self.firebase_base_url,
            FIREBASE_DEVICE_DATA_PATH_BY_ID.format(device_id),
        )

        if preset_mode == "comfort":
            body = {
                "power": True,
                "mode": "manual",
                "temp": device.comfort_temp,
                "status": "comfort",
            }

        elif preset_mode == "eco":
            body = {
                "power": True,
                "mode": "manual",
                "temp": device.eco_temp,
                "status": "eco",
            }
        elif preset_mode == "ice":
            body = {
                "power": True,
                "mode": "manual",
                "temp": device.ice_temp,
                "status": "ice",
            }

        return self._send_patch_request(url, args, body)

    def set_device_mode(self, device: RointeDevice, hvac_mode: str) -> ApiResponse:
        """Set the HVAC mode."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        device_id = device.id
        LOGGER.debug("set_device_mode called with hvac_mode=%s (type=%s)", hvac_mode, type(hvac_mode).__name__)
        if self.use_nexa_ws:
            device_key = self._get_nexa_device_key(device)
            LOGGER.debug("Using Nexa WS, device_key=%s", device_key)
            if hvac_mode == "off":
                body = {"power": 1, "mode": 0, "status": "off"}
                LOGGER.debug("Nexa set hvac off: %s -> %s", device_key, body)
                return self._write_via_websocket(device_key, body)
            if hvac_mode == "heat":
                body = {
                    "temp": device.comfort_temp,
                    "mode": 0,
                    "power": 2,
                    "status": "none",
                }
                LOGGER.debug("Nexa set hvac heat: %s -> %s", device_key, body)
                return self._write_via_websocket(device_key, body)
            if hvac_mode == "auto":
                # Set to auto mode (mode=1) - don't send temp, let radiator follow its schedule
                body = {
                    "mode": 1,
                    "power": 2,
                    "status": "none",
                }
                LOGGER.debug("Nexa set hvac auto: %s -> %s", device_key, body)
                return self._write_via_websocket(device_key, body)
            return ApiResponse(False, None, f"Invalid HVAC Mode {hvac_mode}.")

        args = {"auth": self.auth_token}
        body: Dict[str, Any] = {}

        url = "{}{}".format(
            self.firebase_base_url,
            FIREBASE_DEVICE_DATA_PATH_BY_ID.format(device_id),
        )

        if hvac_mode == "off":
            # This depends if the device is in Auto or Manual modes.
            if device.mode == "auto":
                body = {"power": False, "mode": "auto", "status": "off"}
                return self._send_patch_request(url, args, body)
            else:
                # When turning the device off, we need to set the temperature first.
                set_mode_response = self._send_patch_request(url, args, {"temp": 20})

                if not set_mode_response.success:
                    return set_mode_response

                # Then we can turn the device off.
                body = {"power": False, "mode": "manual", "status": "off"}
                return self._send_patch_request(url, args, body)

        elif hvac_mode == "heat":
            set_mode_response = self._send_patch_request(
                url, args, {"temp": device.comfort_temp}
            )

            if not set_mode_response.success:
                return set_mode_response

            body = {"mode": "manual", "power": True, "status": "none"}
            return self._send_patch_request(url, args, body)

        elif hvac_mode == "auto":
            current_mode: ScheduleMode = device.get_current_schedule_mode()

            # When changing modes we need to send the proper
            # temperature also.
            if current_mode == ScheduleMode.COMFORT:
                body = {"temp": device.comfort_temp}
            elif current_mode == ScheduleMode.ECO:
                body = {"temp": device.eco_temp}
            elif device.ice_mode:
                body = {"temp": device.ice_temp}
            else:
                body = {"temp": 20}

            set_mode_response = self._send_patch_request(url, args, body)

            if not set_mode_response.success:
                return set_mode_response

            # and then set AUTO mode.
            request_mode_status = self._send_patch_request(
                url, args, {"mode": "auto", "power": True}
            )

            return request_mode_status
        else:
            return ApiResponse(False, None, f"Invalid HVAC Mode {hvac_mode}.")

    def _send_patch_request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict] = None,
    ) -> ApiResponse:
        """Send a patch request."""

        if not body:
            body = {}

        body["last_sync_datetime_app"] = round(datetime.now().timestamp() * 1000)

        try:
            response = requests.patch(
                url,
                params=params,
                json=body,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Communications error {e}")

        if not response:
            return ApiResponse(False, None, None)

        if response.status_code != 200:
            return ApiResponse(False, None, None)

        return ApiResponse(True, None, None)

    def _get_installations_nexa(self) -> ApiResponse:
        """Retrieve installations from Nexa API."""

        if not self.nexa_token and not self.nexa_refresh_token and not self.auth_token:
            return ApiResponse(False, None, "Nexa token missing")

        tokens_to_try = []
        if self.nexa_token:
            tokens_to_try.append(("nexa", self.nexa_token))
        if self.nexa_refresh_token:
            tokens_to_try.append(("nexa_refresh", self.nexa_refresh_token))
        if self.auth_token:
            tokens_to_try.append(("firebase", self.auth_token))

        header_templates = [
            # Nexa API uses the 'token' header (not Authorization)
            ("token-header", lambda t: {"token": t}),
            ("bearer", lambda t: {"Authorization": f"Bearer {t}"}),
            ("token", lambda t: {"Authorization": t}),
            ("x-access-token", lambda t: {"x-access-token": t}),
            (
                "bearer+x-access-token",
                lambda t: {"Authorization": f"Bearer {t}", "x-access-token": t},
            ),
            ("token+x-access-token", lambda t: {"Authorization": t, "x-access-token": t}),
        ]

        response = None
        for token_name, token_value in tokens_to_try:
            for header_name, header_builder in header_templates:
                headers = {"Accept": "application/json"}
                headers.update(header_builder(token_value))
                try:
                    response = requests.get(
                        NEXA_INSTALLATIONS_URL,
                        headers=headers,
                        timeout=AUTH_TIMEOUT_SECONDS,
                    )
                except RequestException as e:
                    return ApiResponse(False, None, f"Network error {e}")

                if response is not None and response.status_code != 401:
                    LOGGER.debug(
                        "Nexa get_installations using %s token with %s headers",
                        token_name,
                        header_name,
                    )
                    break

                LOGGER.debug(
                    "Nexa get_installations 401 using %s token with %s headers",
                    token_name,
                    header_name,
                )
            if response is not None and response.status_code != 401:
                break

        if response is None:
            return ApiResponse(
                False, None, "No response from Nexa API in get_installations()"
            )

        if response.status_code != 200:
            LOGGER.error(
                "Nexa get_installations failed: status=%s", response.status_code
            )
            LOGGER.debug(
                "Nexa get_installations response: %s", response.text[:200]
            )
            return ApiResponse(
                False,
                None,
                f"Nexa get_installations returned {response.status_code}",
            )

        try:
            response_json = response.json()
        except ValueError:
            return ApiResponse(False, None, "Nexa get_installations invalid JSON")

        data = response_json.get("data", response_json)
        installations: Dict[str, str] = {}

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                install_id = (
                    item.get("id")
                    or item.get("_id")
                    or item.get("uuid")
                    or item.get("installation_id")
                )
                if not install_id:
                    continue
                name = (
                    item.get("location")
                    or item.get("name")
                    or item.get("address")
                    or install_id
                )
                installations[install_id] = name
        elif isinstance(data, dict):
            for key, item in data.items():
                if isinstance(item, dict):
                    name = item.get("location") or item.get("name") or key
                else:
                    name = str(item)
                installations[key] = name
        else:
            return ApiResponse(False, None, "Nexa get_installations unknown format")

        if not installations:
            return ApiResponse(False, None, "Nexa get_installations empty result")

        return ApiResponse(True, installations, None)

    def _get_installation_by_id_nexa(self, installation_id: str) -> ApiResponse:
        """Retrieve a Nexa installation by ID."""

        if not self.nexa_token and not self.nexa_refresh_token and not self.auth_token:
            return ApiResponse(False, None, "Nexa token missing")

        tokens_to_try = []
        if self.nexa_token:
            tokens_to_try.append(("nexa", self.nexa_token))
        if self.nexa_refresh_token:
            tokens_to_try.append(("nexa_refresh", self.nexa_refresh_token))
        if self.auth_token:
            tokens_to_try.append(("firebase", self.auth_token))

        header_templates = [
            # Nexa API uses the 'token' header (not Authorization)
            ("token-header", lambda t: {"token": t}),
            ("bearer", lambda t: {"Authorization": f"Bearer {t}"}),
            ("token", lambda t: {"Authorization": t}),
            ("x-access-token", lambda t: {"x-access-token": t}),
            (
                "bearer+x-access-token",
                lambda t: {"Authorization": f"Bearer {t}", "x-access-token": t},
            ),
            ("token+x-access-token", lambda t: {"Authorization": t, "x-access-token": t}),
        ]

        response = None
        for token_name, token_value in tokens_to_try:
            for header_name, header_builder in header_templates:
                headers = {"Accept": "application/json"}
                headers.update(header_builder(token_value))
                try:
                    response = requests.get(
                        f"{NEXA_INSTALLATIONS_URL}/{installation_id}",
                        headers=headers,
                        timeout=AUTH_TIMEOUT_SECONDS,
                    )
                except RequestException as e:
                    return ApiResponse(False, None, f"Network error {e}")

                if response is not None and response.status_code != 401:
                    LOGGER.debug(
                        "Nexa get_installation_by_id using %s token with %s headers",
                        token_name,
                        header_name,
                    )
                    break
                LOGGER.debug(
                    "Nexa get_installation_by_id 401 using %s token with %s headers",
                    token_name,
                    header_name,
                )
            if response is not None and response.status_code != 401:
                break

        if response is None:
            return ApiResponse(
                False, None, "No response from Nexa API in get_installation_by_id()"
            )

        if response.status_code != 200:
            LOGGER.error(
                "Nexa get_installation_by_id failed: status=%s", response.status_code
            )
            LOGGER.debug(
                "Nexa get_installation_by_id response: %s", response.text[:200]
            )
            return ApiResponse(
                False,
                None,
                f"Nexa get_installation_by_id returned {response.status_code}",
            )

        try:
            response_json = response.json()
        except ValueError:
            return ApiResponse(False, None, "Nexa get_installation_by_id invalid JSON")

        data = response_json.get("data", response_json)
        if not isinstance(data, dict):
            return ApiResponse(False, None, "Nexa get_installation_by_id invalid format")

        # Cache zone-device mappings for energy attribution
        self._build_zone_device_map(data)

        return ApiResponse(True, data, None)

    def _build_zone_device_map(self, installation_data: Dict[str, Any]) -> None:
        """Build zone-to-device mappings from installation data."""

        zones = installation_data.get("zones", [])
        if not isinstance(zones, list):
            return

        for zone in zones:
            if not isinstance(zone, dict):
                continue
            zone_id = zone.get("id")
            if not zone_id:
                continue

            device_serials: List[str] = []
            devices = zone.get("devices", [])
            if isinstance(devices, list):
                for dev in devices:
                    if isinstance(dev, dict):
                        serial = dev.get("serialNumber") or dev.get("mac")
                        if serial:
                            device_serials.append(serial)
                            self._nexa_device_zone_map[serial] = zone_id

            self._nexa_zone_device_map[zone_id] = device_serials
            LOGGER.debug(
                "Zone %s (%s) has devices: %s",
                zone.get("name"),
                zone_id[:8],
                device_serials,
            )

    def get_nexa_energy_stats(self, installation_id: str) -> ApiResponse:
        """Retrieve energy statistics from Nexa API."""

        if not self.nexa_token:
            return ApiResponse(False, None, "Nexa token not available")

        headers = {"token": self.nexa_token, "Accept": "application/json"}
        params = {"installation": installation_id}

        try:
            response = requests.get(
                NEXA_STATISTICS_URL,
                headers=headers,
                params=params,
                timeout=AUTH_TIMEOUT_SECONDS,
            )
        except RequestException as e:
            return ApiResponse(False, None, f"Network error {e}")

        if response.status_code != 200:
            LOGGER.error(
                "Nexa statistics failed: status=%s", response.status_code
            )
            return ApiResponse(
                False,
                None,
                f"Nexa statistics returned {response.status_code}",
            )

        try:
            response_json = response.json()
        except ValueError:
            return ApiResponse(False, None, "Nexa statistics invalid JSON")

        data = response_json.get("data", response_json)
        if not isinstance(data, dict):
            return ApiResponse(False, None, "Nexa statistics invalid format")

        # Cache for later use
        self._nexa_installation_energy = data
        LOGGER.debug(
            "Nexa statistics: energy=%.3f kWh, cost=%.2f, zones=%d",
            data.get("energy", 0),
            data.get("cost", 0),
            len(data.get("zones", [])),
        )

        return ApiResponse(True, data, None)

    def get_device_energy_from_nexa_stats(
        self, device_serial: str, installation_id: str
    ) -> ApiResponse:
        """Estimate device energy from Nexa installation statistics.

        Uses zone cost proportions to estimate per-device energy.
        """

        # First, ensure we have statistics
        if not self._nexa_installation_energy:
            stats_response = self.get_nexa_energy_stats(installation_id)
            if not stats_response.success:
                return stats_response

        stats = self._nexa_installation_energy
        if not stats:
            return ApiResponse(False, None, "No statistics available")

        total_energy = stats.get("energy", 0)
        total_cost = stats.get("cost", 0)
        zones = stats.get("zones", [])

        if total_cost <= 0 or not zones:
            return ApiResponse(False, None, "No cost data to estimate energy")

        # Find which zone this device belongs to
        zone_id = self._nexa_device_zone_map.get(device_serial)
        if not zone_id:
            LOGGER.warning(
                "Device %s not found in zone map, returning total energy",
                device_serial[:8],
            )
            # Fall back to total energy divided by device count
            total_devices = sum(
                len(devs) for devs in self._nexa_zone_device_map.values()
            )
            if total_devices > 0:
                estimated_energy = total_energy / total_devices
            else:
                estimated_energy = total_energy
            return ApiResponse(
                True,
                EnergyConsumptionData(
                    created=datetime.now(),
                    start=datetime.now() - timedelta(hours=24),
                    end=datetime.now(),
                    kwh=estimated_energy,
                    effective_power=0,
                ),
                None,
            )

        # Find zone cost
        zone_cost = 0
        for zone in zones:
            if zone.get("id") == zone_id:
                zone_cost = zone.get("cost", 0)
                break

        if zone_cost <= 0:
            return ApiResponse(False, None, "Zone has no cost data")

        # Calculate energy proportion
        zone_energy = (zone_cost / total_cost) * total_energy if total_cost > 0 else 0

        # Divide among devices in zone
        devices_in_zone = self._nexa_zone_device_map.get(zone_id, [device_serial])
        device_count = len(devices_in_zone) if devices_in_zone else 1
        device_energy = zone_energy / device_count

        LOGGER.debug(
            "Device %s energy estimate: %.3f kWh (zone %s: %.3f kWh, %d devices)",
            device_serial[:8],
            device_energy,
            zone_id[:8],
            zone_energy,
            device_count,
        )

        return ApiResponse(
            True,
            EnergyConsumptionData(
                created=datetime.now(),
                start=datetime.now() - timedelta(hours=24),
                end=datetime.now(),
                kwh=device_energy,
                effective_power=0,
            ),
            None,
        )

    def _write_via_websocket(
        self, device_id: str, data: Dict[str, Any]
    ) -> ApiResponse:
        """Write data to Firebase via WebSocket (Nexa)."""

        if not self._ensure_valid_auth():
            return ApiResponse(False, None, "Invalid authentication.")

        if not self.firebase_ws_url:
            return ApiResponse(False, None, "No WebSocket URL configured.")

        try:
            import websocket  # type: ignore
        except ImportError:
            return ApiResponse(
                False, None, "websocket-client is required for Nexa devices."
            )

        fields_to_write: List[tuple[str, Any]] = []

        for key in ("temp", "comfort", "eco", "ice"):
            if key in data:
                fields_to_write.append((key, float(data[key])))

        if "status" in data and data["status"] in ("off", "none"):
            fields_to_write.append(("status", data["status"]))

        if "mode" in data:
            fields_to_write.append(("mode", int(data["mode"])))

        if "power" in data:
            fields_to_write.append(("power", int(data["power"])))

        if not fields_to_write:
            return ApiResponse(True, None, None)

        results: Dict[int, Any] = {}
        errors: List[str] = []
        request_id = [1]
        expected_responses = [0]
        ws_done = threading.Event()
        ws_connected = threading.Event()
        closing = [False]

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                if msg.get("t") == "d" and "d" in msg:
                    data_block = msg["d"]
                    req_id = data_block.get("r")
                    if req_id and "b" in data_block:
                        results[req_id] = data_block["b"].get("s")
                        if len(results) >= expected_responses[0]:
                            ws_done.set()
            except Exception:
                pass

        def on_error(ws, error):
            if not closing[0] and error:
                error_str = str(error)
                if "NoneType" not in error_str:
                    errors.append(error_str)
                    ws_done.set()

        def on_close(ws, code, msg):
            ws_done.set()

        def on_open(ws):
            ws_connected.set()
            try:
                request_id[0] += 1
                ws.send(
                    json.dumps(
                        {
                            "t": "d",
                            "d": {
                                "r": request_id[0],
                                "a": "auth",
                                "b": {"cred": self.auth_token},
                            },
                        }
                    )
                )
                expected_responses[0] += 1
                time.sleep(0.3)

                for field, value in fields_to_write:
                    request_id[0] += 1
                    ws.send(
                        json.dumps(
                            {
                                "t": "d",
                                "d": {
                                    "r": request_id[0],
                                    "a": "p",
                                    "b": {
                                        "p": f"/devices/{device_id}/data/{field}",
                                        "d": value,
                                    },
                                },
                            }
                        )
                    )
                    expected_responses[0] += 1
                    time.sleep(0.1)
            except Exception as e:
                errors.append(str(e))
                ws_done.set()

        def safe_close(ws):
            closing[0] = True
            try:
                if ws and hasattr(ws, "sock") and ws.sock:
                    ws.close()
            except Exception:
                pass

        ws = websocket.WebSocketApp(
            self.firebase_ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        ws_thread = threading.Thread(
            target=lambda: ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}),
            daemon=True,
        )
        ws_thread.start()

        if not ws_connected.wait(timeout=5):
            safe_close(ws)
            return ApiResponse(False, None, "Connection timeout")

        ws_done.wait(timeout=8)
        safe_close(ws)
        ws_thread.join(timeout=2)

        if errors:
            return ApiResponse(False, None, "; ".join(errors))

        return ApiResponse(True, results, None)

    def _get_nexa_device_key(self, device: RointeDevice) -> str:
        """Resolve the Nexa device key for Firebase paths."""

        if device.serialnumber:
            return device.serialnumber
        cached = self._nexa_device_cache.get(device.id, {})
        if cached.get("serialNumber"):
            return cached["serialNumber"]
        return device.id

    def _read_via_websocket(self, path: str) -> Any:
        """Read data from Firebase via WebSocket (Nexa)."""

        if not self._ensure_valid_auth():
            return None

        if not self.firebase_ws_url:
            return None

        try:
            import websocket  # type: ignore
        except ImportError:
            LOGGER.error("websocket-client is required for Nexa devices.")
            return None

        result_holder: dict[str, Any] = {"data": None}
        errors: List[str] = []
        request_id = [1]
        ws_done = threading.Event()
        ws_connected = threading.Event()
        closing = [False]

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                if msg.get("t") == "d" and "d" in msg:
                    data_block = msg["d"]
                    if data_block.get("r") == request_id[0] and "b" in data_block:
                        result_holder["data"] = data_block["b"].get("d")
                        if isinstance(result_holder["data"], dict):
                            LOGGER.debug(
                                "WebSocket read keys for %s: %s",
                                path,
                                list(result_holder["data"].keys()),
                            )
                        else:
                            LOGGER.error(
                                "WebSocket read unexpected type for %s: %s (%s)",
                                path,
                                type(result_holder["data"]).__name__,
                                str(result_holder["data"])[:200],
                            )
                        ws_done.set()
            except Exception:
                pass

        def on_error(ws, error):
            if not closing[0] and error:
                error_str = str(error)
                if "NoneType" not in error_str:
                    errors.append(error_str)
                    ws_done.set()

        def on_close(ws, code, msg):
            ws_done.set()

        def on_open(ws):
            ws_connected.set()
            try:
                request_id[0] += 1
                ws.send(
                    json.dumps(
                        {
                            "t": "d",
                            "d": {
                                "r": request_id[0],
                                "a": "auth",
                                "b": {"cred": self.auth_token},
                            },
                        }
                    )
                )
                time.sleep(0.3)

                request_id[0] += 1
                ws.send(
                    json.dumps(
                        {
                            "t": "d",
                            "d": {
                                "r": request_id[0],
                                "a": "g",
                                "b": {"p": path},
                            },
                        }
                    )
                )
            except Exception as e:
                errors.append(str(e))
                ws_done.set()

        def safe_close(ws):
            closing[0] = True
            try:
                if ws and hasattr(ws, "sock") and ws.sock:
                    ws.close()
            except Exception:
                pass

        ws = websocket.WebSocketApp(
            self.firebase_ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        ws_thread = threading.Thread(
            target=lambda: ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}),
            daemon=True,
        )
        ws_thread.start()

        if not ws_connected.wait(timeout=5):
            safe_close(ws)
            return None

        ws_done.wait(timeout=8)
        safe_close(ws)
        ws_thread.join(timeout=2)

        if errors:
            LOGGER.error("WebSocket read error: %s", "; ".join(errors))
            return None

        return result_holder["data"]
