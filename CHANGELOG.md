# Changelog

All notable changes to this project will be documented in this file.

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
