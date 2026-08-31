# Fellow Stagg EKG+ Home Assistant Integration

Control your Fellow Stagg EKG+ electric kettle from Home Assistant!

## Features

- **Water Heater Entity**: Full control as a water heater device
  - Set target temperature
  - Turn on/off
  - View current temperature
  - Operation modes (off, heat, standby)

- **Sensors**:
  - Current temperature
  - Target temperature
  - Kettle mode

- **Switches**:
  - Heating control
  - Warming control

## Installation

1. Copy the `custom_components/fellow` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Configuration > Integrations
4. Click the "+ ADD INTEGRATION" button
5. Search for "Fellow"
6. Enter your kettle's IP address (find it in your router's client list)

## Requirements

Your Stagg EKG+ or EKG Pro must be on your WiFi network and expose the HTTP CLI interface (tested with EKG+ firmware 1.1.76SSP CLI; EKG Pro command differences are handled automatically).

## Usage

### Water Heater Card

Add a water heater card to your dashboard:

```yaml
type: thermostat
entity: water_heater.fellow_kettle
```

### Automation Example

Heat water to 90°C every morning:

```yaml
automation:
  - alias: "Morning Coffee Water"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.fellow_kettle
        data:
          temperature: 90
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.fellow_kettle
```

### Sensors in Lovelace

```yaml
type: entities
entities:
  - entity: sensor.fellow_current_temperature
  - entity: sensor.fellow_target_temperature
  - entity: sensor.fellow_mode
  - entity: switch.fellow_heating
  - entity: switch.fellow_warming
```

## Troubleshooting

### Cannot connect to kettle

1. Verify the kettle is powered on
2. Check that the kettle is connected to your WiFi network
3. Verify the IP address is correct
4. Try accessing `http://[kettle-ip]/cli?cmd=state` in a web browser

### Entities not updating

The integration polls the kettle every 10 seconds by default (configurable 5-60 in the options). You can manually refresh by reloading the integration.

## Credits

Based on reverse engineering of the Stagg EKG+ CLI interface; EKG Pro command set cross-checked against the stagg-ekg-pro project (https://github.com/montymhughes/stagg-ekg-pro).
