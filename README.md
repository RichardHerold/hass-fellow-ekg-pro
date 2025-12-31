# Fellow EKG Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License: Unlicense](https://img.shields.io/badge/License-Unlicense-blue.svg)](http://unlicense.org/)

A complete Home Assistant custom integration for Fellow EKG electric kettles (Stagg EKG, Stagg EKG+, Stagg EKG Pro, and Corvo EKG) with temperature control, automation support, and real-time monitoring.

Works with all Fellow kettles that have the HTTP CLI interface.


## Features

✨ **Complete Control**
- Turn kettle on/off from Home Assistant
- Set target temperature (40-100°C / 104-212°F)
- Monitor current water temperature in real-time
- View operating mode and heating status

🌡️ **Temperature Management**
- Choose between Celsius or Fahrenheit
- Syncs with kettle's LCD display
- Precise 0.5°C temperature steps
- Automatic temperature validation

🔒 **Safety Features**
- Low water detection warning
- Automatic power management
- Temperature range limits
- Safe heating cycle control

🤖 **Home Assistant Integration**
- 8 entities for complete control
- Water heater entity for climate integration
- Binary sensors for status monitoring
- Switches for direct control
- Full automation support

📡 **Local Control**
- No cloud connection required
- Works entirely on local network
- Fast response times
- Standalone Python API included

## Entities

| Entity | Type | Purpose |
|--------|------|---------|
| `water_heater.stagg_ekg_kettle` | Water Heater | Main control interface |
| `sensor.stagg_ekg_current_temperature` | Sensor | Real-time water temperature |
| `sensor.stagg_ekg_target_temperature` | Sensor | Target temperature setting |
| `sensor.stagg_ekg_mode` | Sensor | Operating mode (Off, Heat, Standby) |
| `switch.stagg_ekg_heating` | Switch | Heating element control |
| `switch.stagg_ekg_warming` | Switch | Warming mode control |
| `binary_sensor.stagg_ekg_power` | Binary Sensor | Power on/off status |
| `binary_sensor.stagg_ekg_low_water_warning` | Binary Sensor | Water detection alert |

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed
2. Add this repository as a custom repository:
   - Go to HACS → Integrations
   - Click the three dots in the top right
   - Select "Custom repositories"
   - Add repository URL: `https://github.com/rderewianko/fellow-ekg`
   - Category: Integration
3. Click "Install" on the Stagg EKG+ integration
4. Restart Home Assistant
5. Add the integration:
   - Go to Settings → Devices & Services → Add Integration
   - Search for "Fellow Stagg EKG+"
   - Enter your kettle's IP address
   - Choose temperature unit (Celsius or Fahrenheit)

### Manual Installation

1. Download the `custom_components/stagg_ekg` folder
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

## Configuration

### Finding Your Kettle's IP Address

The kettle connects to your WiFi network. Find its IP address:

1. Check your router's DHCP client list
2. Look for a device named "Stagg EKG" or similar
3. Note the IP address (e.g., `192.168.1.100`)

**Tip:** Set a static IP or DHCP reservation for your kettle to prevent the address from changing.

### Setup

1. Go to Settings → Devices & Services → Add Integration
2. Search for "Fellow Stagg EKG+"
3. Enter configuration:
   - **Host:** Your kettle's IP address
   - **Temperature Unit:** Choose Celsius or Fahrenheit
4. Click Submit

The integration will sync the temperature unit with your kettle's LCD display.

### Changing Temperature Units

1. Go to Settings → Devices & Services
2. Find "Stagg EKG+"
3. Click "CONFIGURE"
4. Select your preferred unit
5. Submit - the kettle display updates immediately

## Usage

### Basic Control

```yaml
# Heat water to 95°C
service: water_heater.turn_on
target:
  entity_id: water_heater.stagg_ekg_kettle
data:
  temperature: 95
```

### Automations

**Morning Coffee**
```yaml
automation:
  - alias: "Morning Coffee"
    trigger:
      platform: time
      at: "07:00:00"
    condition:
      # Only if water detected
      - condition: state
        entity_id: binary_sensor.stagg_ekg_low_water_warning
        state: "off"
    action:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.stagg_ekg_kettle
        data:
          temperature: 95
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.stagg_ekg_kettle
```

**Water Ready Notification**
```yaml
automation:
  - alias: "Water Ready Notification"
    trigger:
      - platform: template
        value_template: >
          {{ states('sensor.stagg_ekg_current_temperature')|float >=
             states.water_heater.stagg_ekg_kettle.attributes.temperature|float - 2 }}
    condition:
      - condition: state
        entity_id: water_heater.stagg_ekg_kettle
        attribute: current_operation
        state: "heat"
    action:
      - service: notify.mobile_app
        data:
          message: "Kettle water is ready!"
          title: "☕ Coffee Time"
```

**Tea Temperature Presets**
```yaml
script:
  heat_green_tea:
    alias: "Heat for Green Tea"
    sequence:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.stagg_ekg_kettle
        data:
          temperature: 75
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.stagg_ekg_kettle

  heat_black_tea:
    alias: "Heat for Black Tea"
    sequence:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.stagg_ekg_kettle
        data:
          temperature: 95
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.stagg_ekg_kettle
```

### Dashboard Card

```yaml
type: thermostat
entity: water_heater.stagg_ekg_kettle
name: Coffee Kettle
```

## Standalone Python API

The repository includes a standalone Python API (`stagg_ekg_api.py`) for use outside Home Assistant.

### Quick Start

```python
from stagg_ekg_api import StaggEKGClient

# Initialize
kettle = StaggEKGClient(host="192.168.1.100")

# Heat water to 95°C
kettle.heat_to_temperature(95)

# Check status
state = kettle.get_state()
print(f"Current: {state.current_temp_c}°C / Target: {state.set_temp_c}°C")
```

See [PYTHON_API_EXAMPLES.md](PYTHON_API_EXAMPLES.md) for complete usage examples.

## Technical Details

### Kettle Information

- **Firmware:** 1.1.76SSP CLI (May 9, 2024)
- **Platform:** ESP32 (Espressif)
- **Protocol:** HTTP
- **Port:** 80
- **API:** CLI interface at `/cli?cmd=<command>`

### Temperature Control

- **Range:** 40-100°C (104-212°F)
- **Step Size:** 0.5°C per dial click
- **Internal Format:** "2C" (temperature × 2)
- **Control Method:** Dial rotation (no direct API)

### Physical Buttons

The kettle has two buttons:
- **Button 1:** Separate button on base (opens menus)
- **Button 2:** The dial itself is pressable (wakes and starts heating)

The integration uses Button 2 for power/start operations.

### Update Frequency

- **Automatic polling:** Every 30 seconds
- **Command response:** Immediate refresh after control actions
- **Typical latency:** 1-2 seconds for commands

See [KETTLE_SPECS.md](KETTLE_SPECS.md) for complete technical documentation.

## Troubleshooting

### Kettle Not Responding

1. Verify the kettle is powered on and WiFi is enabled
2. Check the IP address hasn't changed
3. Ensure Home Assistant can reach the kettle's network
4. Try pinging the kettle: `ping 192.168.1.100`

### Low Water Warning Always On

- Warning triggers when temperature < 30°C
- If water is present but cold, warning will clear as temp rises
- This is a temperature-based heuristic, not a physical sensor

### Temperature Unit Mismatch

- Check integration configuration (Settings → Integrations → Stagg EKG → Configure)
- Changing units in HA updates the kettle's LCD display
- Restart integration if sync fails

### Screen Doesn't Turn On

- The integration automatically wakes the screen
- Commands may take 1-2 seconds to complete
- Check entity state updates after a moment

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This is free and unencumbered software released into the public domain. See the [LICENSE](LICENSE) file for details.

Anyone is free to copy, modify, publish, use, compile, sell, or distribute this software for any purpose, commercial or non-commercial, and by any means.

## Acknowledgments

- Built for [Fellow EKG electric kettles](https://fellowproducts.com/) (Stagg EKG, Stagg EKG+, Stagg EKG Pro, Corvo EKG)
- Uses the kettle's built-in HTTP CLI interface
- Developed and tested with firmware version 1.1.76SSP CLI on Home Assistant 2025.12.5
- **Created with AI assistance** - This integration was developed using Claude Code

## Disclaimer

This is an unofficial integration not affiliated with Fellow Products. Use at your own risk.

---

**Enjoy your smart kettle!** ☕

If you find this integration helpful, consider starring the repository!
