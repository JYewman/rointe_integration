# Rointe Heaters

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/JYewman/rointe_integration?style=flat-square)](https://github.com/JYewman/rointe_integration/releases)
[![GitHub Issues](https://img.shields.io/github/issues/JYewman/rointe_integration?style=flat-square)](https://github.com/JYewman/rointe_integration/issues)

Home Assistant integration for Rointe electric radiators. Control your Rointe heating devices directly from Home Assistant with full climate entity support.

## How It Works

This integration connects to Rointe's cloud infrastructure to control your radiators. It supports two different API backends depending on your device generation.

### Architecture

```
Home Assistant  ←→  Rointe Integration  ←→  Rointe Cloud  ←→  Your Radiators
                         │
                         ├── Nexa API (WebSocket)
                         │   └── Real-time state updates via Firebase
                         │
                         └── Legacy API (REST)
                             └── Polling-based updates
```

### Nexa Platform (Newer Devices)

The Nexa platform uses Firebase Realtime Database for device state synchronisation:

1. **Authentication** - The integration authenticates with Rointe's servers using your account credentials
2. **WebSocket Connection** - Establishes a persistent WebSocket connection to Firebase for real-time updates
3. **State Synchronisation** - Device states (temperature, power, schedules) are synced automatically when they change
4. **Command Dispatch** - When you adjust settings in Home Assistant, commands are sent to Firebase which pushes them to your devices

**Schedule-Aware Temperature Display**: In AUTO mode, the integration reads the device's schedule to determine the current target temperature (Comfort/Eco/Off) based on the time of day, rather than relying on potentially stale cached values.

### Legacy Platform (Older Devices)

The Legacy platform uses traditional REST API polling:

1. **Authentication** - OAuth-style authentication with Rointe's servers
2. **Polling** - Device states are fetched periodically (configurable interval)
3. **Commands** - Settings changes are sent via REST API calls

### Data Flow

| Direction | Nexa | Legacy |
|-----------|------|--------|
| State updates | Real-time (WebSocket) | Polling (30-60s) |
| Commands | Instant | Instant |
| Schedule data | Synced from device | Synced from device |

### Heating State Detection

The integration determines whether a radiator is actively heating based on temperature differential rather than device-reported state (which can be stale):

- **Heating**: Target temperature > Current temperature (and power is on)
- **Idle**: Current temperature ≥ Target temperature
- **Off**: Device power is off

This approach ensures the UI accurately reflects what the radiator is doing, even when cloud data is delayed.

## Supported Devices

- Series-D Radiators
- Belize and Olympia Radiators (Nexa)
- Series-D Towel Rails
- Oval Towels (Nexa)
- Thermostats

## Features

- **Climate Control** - Set target temperatures, switch between heating modes
- **Presets** - Use Eco, Comfort, or Manual modes
- **Temperature Sensors** - Monitor current room temperature from each device
- **Power Monitoring** - Track current power consumption and energy usage
- **Firmware Updates** - Get notified when device firmware updates are available
- **Schedule Support** - Works with the device's built-in scheduling system

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner
3. Select **Custom repositories**
4. Add the repository URL: `https://github.com/JYewman/rointe_integration`
5. Select **Integration** as the category
6. Click **Add**
7. Search for "Rointe" in HACS and install it
8. Restart Home Assistant

### Manual Installation

1. Download the [latest release](https://github.com/JYewman/rointe_integration/releases)
2. Extract the `custom_components/rointe` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Adding the Integration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **Rointe Heaters**
4. Follow the configuration steps:
   - Enter your Rointe account email
   - Enter your Rointe account password
   - Select your API type (Nexa or Legacy)

### API Types

| API Type | Description |
|----------|-------------|
| **Nexa** | For newer Rointe devices using the Nexa platform. Uses WebSocket for real-time updates. |
| **Legacy** | For older Rointe devices using the original REST API. |

If you're unsure which to use, try Nexa first. If your devices don't appear, reconfigure with Legacy.

## Entities

After setup, the following entities are created for each radiator:

### Climate

| Entity | Description |
|--------|-------------|
| `climate.{device_name}` | Main climate control entity |

**Supported Features:**

- Set target temperature
- Switch HVAC modes (Heat, Off)
- Select presets (Eco, Comfort, Manual)

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.{device_name}_temperature` | Current room temperature |
| `sensor.{device_name}_power` | Current power consumption (W) |
| `sensor.{device_name}_energy` | Total energy consumption (kWh) |
| `sensor.{device_name}_effective_power` | Real-time power draw |

### Binary Sensors

| Entity | Description |
|--------|-------------|
| `binary_sensor.{device_name}_heating` | Whether the radiator is actively heating |
| `binary_sensor.{device_name}_window_open` | Window open detection (if supported) |

### Switches

| Entity | Description |
|--------|-------------|
| `switch.{device_name}_power` | Turn radiator on/off |
| `switch.{device_name}_lock` | Child lock |

### Update

| Entity | Description |
|--------|-------------|
| `update.{device_name}_firmware` | Firmware update availability |

## Services

The integration provides custom services for advanced control:

### `rointe.set_preset`

Set a specific preset mode on a device.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `entity_id` | Yes | Climate entity to control |
| `preset` | Yes | Preset name (eco, comfort, manual) |

### `rointe.set_temperature`

Set the target temperature for a specific mode.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `entity_id` | Yes | Climate entity to control |
| `temperature` | Yes | Target temperature |
| `mode` | No | Mode to set temperature for |

## Energy Dashboard

The integration provides energy sensors compatible with Home Assistant's Energy Dashboard.

To add your radiators to the Energy Dashboard:

1. Go to **Settings** → **Dashboards** → **Energy**
2. Click **Add Consumption**
3. Select `sensor.{device_name}_energy` for each radiator

## Troubleshooting

### Devices not appearing

- Verify your Rointe account credentials are correct
- Try switching between Nexa and Legacy API types
- Check the Home Assistant logs for error messages

### Connection issues

- The integration uses cloud polling; ensure your Home Assistant instance has internet access
- Check if the Rointe servers are accessible (try logging into the Rointe app)

### Entity states show "unavailable"

- This usually indicates a temporary connection issue
- The integration will automatically reconnect when the connection is restored

### Debug Logging

To enable debug logging, add this to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.rointe: debug
```

## Migration from Previous Versions

If you previously used an older version of this integration:

1. Remove the old integration from **Settings** → **Devices & Services**
2. Delete the `custom_components/rointe` folder
3. Delete any `custom_components/rointesdk` folder if present
4. Install the new version via HACS
5. Restart Home Assistant
6. Add the integration again

**Note:** Entity IDs may change after migration. Update any automations, scripts, or dashboards that reference the old entity IDs.

## Issues

Found a bug or have a feature request? Please open an issue on GitHub:

**[Open an Issue](https://github.com/JYewman/rointe_integration/issues)**

When reporting a bug, please include:

- Home Assistant version
- Integration version
- Debug logs (see [Debug Logging](#debug-logging))
- Steps to reproduce the issue

## Contributing

Contributions are welcome via pull requests.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

**[View Open Pull Requests](https://github.com/JYewman/rointe_integration/pulls)**

### Development Setup

```bash
# Clone your fork
git clone https://github.com/JYewman/rointe_integration.git

# Copy to HA custom_components for testing
cp -r custom_components/rointe /path/to/ha/config/custom_components/

# Restart Home Assistant to test changes
```

## License

This project is licensed under the MIT License.

## Acknowledgements

- Thanks to all contributors who have helped improve this integration
- Rointe for manufacturing quality electric radiators
- tggm for the original HCAS integration
