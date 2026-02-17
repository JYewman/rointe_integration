# Changelog

All notable changes to this project will be documented in this file.

## [3.0.0] - 2026-02-16

### Added
- Full Nexa platform support via WebSocket API
- Real-time device state updates
- Schedule-aware temperature display
- Effective power consumption sensors
- Energy consumption sensors for Energy Dashboard integration

### Changed
- Migrated from REST API to WebSocket for Nexa devices
- Improved state derivation from device schedules in AUTO mode
- Enhanced HVAC action detection based on temperature probe readings

### Fixed
- Temperature display now correctly reflects scheduled targets in AUTO mode
- Power state detection improved for accurate heating status

### Breaking Changes
- Entity IDs may change when migrating from v2.x
- Nexa Firebase data handling completely rewritten

## [2.2.0]

### Changed
- Updated to rointe-sdk 1.6.0
- Fixed linting errors in the library
- Improved API response error handling

## [2.1.0]

### Added
- Missing oval towel support (#15)

## [2.0.0]

### Changed
- Updated to Home Assistant 2024.01
- Various bug fixes

## [1.4.0]

### Added
- Support for Oval Towel

## [1.3.0]

### Added
- Support for sub-zones

## [1.2.7]

### Added
- Experimental support for Belize/Olympia radiators

## [1.2.6]

### Changed
- Extended debugging during setup

## [1.2.5]

### Fixed
- Various bug fixes

## [1.2.4]

### Changed
- Refresh from the main repository

## [1.2.0]

### Added
- Show device's real name (product name)

### Changed
- Take into account not all firmware upgrades are possible
- Forces updating the device registry

## [1.1.0]

### Added
- Improved code documentation
- Added climate icon

### Removed
- Dead code cleanup

### Fixed
- Model name capitalization

## [1.0.10]

### Added
- Added missing entity descriptors
- Configure scan interval
- Raise ConfigEntryNotReady if unable to initialize from config

### Changed
- Bump rointe-sdk to v1.0.9b1
- Decrease update messages log level

### Fixed
- Set devices as unavailable if communication errors occur
- Remove excessive error messages

## [1.0.8]

### Fixed
- Authentication refresh fix
- Setting HVAC mode to Auto now sets the temperature to Comfort
- Remove excessive logging
