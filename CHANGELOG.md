# Changelog

All notable changes to this integration are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Each release is also on the
GitHub releases page with the same notes.

## [Unreleased]

### Added

- Weekly Dependabot updates for the GitHub Actions the workflows use.

## [0.2.1] - 2026-11-10

### Removed

- The Touch control and Zigbee radio switches and the Motor speed number. Their setter
  payloads are not documented, so the integration no longer writes them. They may come back
  in a later release once the payloads are verified.

## [0.2.0] - 2026-11-07

### Added

- More numbers, buttons and sensors (see "What you get" in the README).
- A brand icon and logo for the HACS and Home Assistant UI.
- Tests for the entity names.

### Changed

- More reliable connection handling in the coordinator and the device layer.

## [0.1.0] - 2026-09-08

First public release: control SOMA Smart Shades 3 motors over Bluetooth LE from Home
Assistant, directly or through ESPHome Bluetooth proxies, with no vendor cloud.

### Added

- Cover: open, close, stop and set position.
- Calibration without the vendor app: set and save the open and closed limits, and the
  `soma_ble.jog` service to reach the true top and bottom.
- A Needs calibration sensor; a move on an uncalibrated shade fails with an error that says
  how to fix it.
- Controls: motor speed, touch control, the Zigbee radio switch, identify by beep, restart.
- Diagnostics: battery percent and voltage, input voltage, external power, driver
  temperature, light level, move and boot counts, charger status and fault, and per-move
  telemetry (duration, peak RPM, peak PWM, stall events, under-voltage events).
- Requires Home Assistant 2024.11.0 or newer.

[Unreleased]: https://github.com/pete-jorgensen/soma-ble/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/pete-jorgensen/soma-ble/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/pete-jorgensen/soma-ble/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/pete-jorgensen/soma-ble/releases/tag/v0.1.0
