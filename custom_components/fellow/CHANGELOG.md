# Changelog

All notable changes to this project will be documented in this file.

## [3.0.0] - 2026-08-31

Reliability rework targeting the Stagg EKG Pro, whose firmware formats
responses and takes commands differently from the EKG+ this integration was
originally written against.

### Fixed
- **Temperature parsing on the EKG Pro**: the parser no longer requires a
  literal `C` suffix after temperature values. It now accepts suffixed or
  bare values and resolves the unit from the suffix, the `units=` field, or
  magnitude — this was the root cause of broken temperature entities on the
  Pro.
- Setting the temperature now uses `setsettingd settempr` (sets the
  *active* target, verified on the Pro), then falls back to the legacy
  `setsetting settempr`, then to dial emulation — each verified by
  read-back.
- A missing target temperature reads as unknown instead of 0°C.
- A truncated response can no longer masquerade as a lifted kettle.
- Config entries now have a unique ID (kettle MAC, host fallback), so the
  same kettle can't be added twice and IP changes update the existing entry.
- Status flags are parsed only from the `ketl=` line instead of matching
  `ho`/`wd` anywhere in the response.
- Documentation now matches the code (polling default, IP examples).

### Changed
- Keep-warm uses Hold mode (`ss S_Hold`); the unverified `warmon`/`warmoff`
  commands are gone.
- Setup no longer writes the display units to the kettle; unit syncing is
  an opt-in option.
- Device info (model, firmware version, MAC) is read from the kettle
  instead of being hardcoded.
- Default poll interval is 10 seconds, configurable 5–60 in options.
- Setup starts with manual IP entry; the /24 network scan runs only when
  explicitly chosen.
- Low Water Warning is now the firmware's `nw` flag (was a temperature
  heuristic) and, like Lifted, is disabled by default until verified.

### Added
- Diagnostics platform: download the last parsed state plus raw firmware
  responses from the device page.
- `examples/probe_kettle.py`: stdlib-only, read-only capture tool that
  prints raw responses and per-field parser PASS/FAIL.
- Advanced disabled-by-default "Heater Element (Direct)" switch exposing
  `heaton`/`heatoff` GPIO control.
- Boil Threshold diagnostic sensor (`temprB`).
- Parser unit tests (`pytest tests/`) covering EKG+ and Pro response
  shapes; no Home Assistant install needed.

### Safety
- The client refuses to send commands known to reboot or crash the kettle
  (bare `ss`, `adcsamples`, `reset`); the example script's `reset()`
  wrapper is removed.

## [2.0.0] - 2026-01-03

### Breaking Changes
- **Domain renamed from `stagg_ekg` to `fellow`** to match Home Assistant brands repository and support all Fellow EKG models
- **Entity IDs have changed**:
  - `water_heater.stagg_ekg_kettle` → `water_heater.fellow_kettle`
  - `sensor.stagg_ekg_current_temperature` → `sensor.fellow_current_temperature`
  - `sensor.stagg_ekg_target_temperature` → `sensor.fellow_target_temperature`
  - `sensor.stagg_ekg_mode` → `sensor.fellow_mode`
  - `switch.stagg_ekg_heating` → `switch.fellow_heating`
  - `switch.stagg_ekg_warming` → `switch.fellow_warming`
  - `binary_sensor.stagg_ekg_power` → `binary_sensor.fellow_power`
  - `binary_sensor.stagg_ekg_low_water_warning` → `binary_sensor.fellow_low_water_warning`
- **Directory renamed**: `custom_components/stagg_ekg/` → `custom_components/fellow/`

### Migration Instructions
1. Remove the old integration from Home Assistant (Settings → Devices & Services)
2. Delete the `custom_components/stagg_ekg` folder
3. Install v2.0.0 with the new `custom_components/fellow` folder
4. Re-add the integration
5. Update all automations, scripts, and dashboard cards to use new entity IDs

### Added
- Added `issue_tracker` to manifest.json for better HACS compliance
- GitHub Actions for HACS and Hassfest validation

### Fixed
- Fixed HACS validation errors (removed invalid keys from hacs.json)
- Fixed manifest key ordering to meet Home Assistant requirements
- Integration now aligns with Home Assistant brands repository entry

## [1.0.0] - 2025-12-27

### Added
- Initial release of Fellow Stagg EKG+ Home Assistant integration
- Water heater entity for main temperature control
- Temperature sensors (current and target)
- Operating mode sensor
- Heating and warming switches
- Power status binary sensor
- Low water warning binary sensor
- Temperature unit selection (Celsius/Fahrenheit) with LCD sync
- Standalone Python API (`stagg_ekg_api.py`)
- Comprehensive documentation and examples
- HACS compatibility

### Features
- Local control (no cloud required)
- Temperature range: 40-100°C (104-212°F)
- Precise 0.5°C temperature steps
- Automatic screen wake and power management
- Water detection heuristic (temperature-based)
- Real-time status monitoring (30-second polling)
- Full automation support

### Technical Details
- Discovered correct temperature field mappings (tempr vs temprT)
- Implemented dial rotation for temperature setting (only method available)
- Identified two physical buttons (base button and dial button)
- Button 2 (dial button) used for optimal power/start behavior
- Added delays for reliable command execution
- Fixed step calculation (0.5°C per step, not 5.5°C)

### Documentation
- README.md with installation and usage
- KETTLE_SPECS.md with complete technical reference
- PYTHON_API_EXAMPLES.md with 10 real-world examples
- Automation examples for common use cases

### Notes
- Tested with firmware version 1.1.76SSP CLI
- No direct temperature setting API exists (must use dial rotation)
- Temperature unit changes sync with kettle's LCD display
- Integration uses local HTTP CLI interface on port 80
