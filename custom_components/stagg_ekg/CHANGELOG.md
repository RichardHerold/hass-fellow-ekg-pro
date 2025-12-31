# Changelog

All notable changes to the Stagg EKG+ Home Assistant integration will be documented in this file.

## [1.0.0] - 2024-12-26

### Added
- Initial release of Stagg EKG+ Home Assistant integration
- Water heater entity for temperature control
- Temperature sensors (current and target)
- Mode sensor
- Heating and warming switches
- Configuration flow with temperature unit selection
- Options flow to change temperature units
- Support for both Celsius and Fahrenheit units
- Automatic sync of temperature units with kettle's display

### Features
- **Temperature Unit Configuration**: Choose between Celsius or Fahrenheit during setup
  - Syncs with kettle's physical display
  - Can be changed later via integration options
  - Units: 0 = Fahrenheit, 1 = Celsius (kettle's internal format)
- **Local Control**: No cloud connection required
- **Real-time Updates**: Polls kettle every 30 seconds
- **Full Kettle Control**: Heat, warm, temperature settings via Home Assistant

### Technical Details
- Uses HTTP CLI interface on firmware 1.1.76SSP
- Communicates with kettle at `http://[kettle-ip]/cli`
- Supports all CLI commands for advanced control
