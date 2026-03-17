# Changelog

## v3.0.1 (2026-03-17)

### Fixed
- **Nexa WebSocket commands now include `last_sync_datetime_app` timestamp** — radiators were ignoring commands sent via WebSocket because the sync timestamp was missing, causing them to treat updates as stale data rather than fresh commands from the app.
- **WebSocket auth response verification** — both read and write operations now properly wait for and verify the Firebase auth response before sending commands, instead of blindly proceeding after a 300ms delay.
- **Automatic re-authentication on token expiry** — when the Firebase refresh token expires, the integration now performs a full re-login using stored credentials instead of silently failing with "Permission denied" errors.
- **Permission denied retry logic** — if a WebSocket read or write gets a "Permission denied" response, the integration forces a token refresh and retries once before giving up.

## v3.0.0 (2026-02-17)

### Added
- Full Nexa API support (Rointe's new cloud platform)
- Auto-detection of legacy vs Nexa accounts
- WebSocket-based real-time communication for Nexa devices
- Binary sensors (window open, boost active, timer active, heating, connected, etc.)
- Number entities for comfort/eco/frost protection temperatures
- Switch entities for window detection, silence mode, lock controls, etc.
- Schedule-aware target temperature in AUTO mode
- Energy consumption tracking via Nexa statistics API
- Firmware update detection

### Changed
- Derive HVAC action from temperature differential instead of stale Firebase status
- Improved device discovery and zone mapping
- Better error handling throughout

## v2.2.2

- Bug fixes and stability improvements

## v2.2.1-1

- Minor fixes

## v2.1.0

- Added additional sensor entities
- Improved error handling
