# Stagg EKG+ Integration - Latest Updates

## New Features Added

### 1. **Temperature Unit Configuration** ✅
- Choose between Celsius or Fahrenheit during setup
- Change units later via integration options
- **Syncs with kettle's physical display** - changing the unit in Home Assistant also changes it on the kettle's LCD
- Temperature units:
  - `units=1` → Celsius (°C)
  - `units=0` → Fahrenheit (°F)

### 2. **Improved Power Control** ✅
- New `power_on()` function to properly wake the kettle screen
- New `start_heating()` function that:
  - Wakes the kettle if it's off
  - Exits any menu screens automatically
  - Starts the heating cycle
- New `stop_heating()` function for clean shutdown
- Water heater's `turn_on` now uses `start_heating()` for reliable operation

### 3. **Water Detection** ✅
- **Low Water Warning** binary sensor
  - Alerts when temperature is below 30°C (may indicate no water)
  - Prevents accidental dry heating
  - Shows current temperature in attributes
- Log warning when attempting to heat with possibly no water

### 4. **New Binary Sensors**
- **Power sensor**: Shows if kettle is powered on or in standby
  - Attributes: mode, screen name, in_menu status
- **Low Water Warning sensor**: Alerts when kettle may be empty
  - Attributes: current temperature, warning note

### 5. **Enhanced State Detection**
- Track screen name (main screen vs menus)
- Detect if kettle is in menu mode
- Detect if kettle is powered on
- Better mode parsing (S_Off, S_Standby, S_Heat, S_HeatOff, etc.)

## Entities Now Available

| Entity | Type | Description |
|--------|------|-------------|
| `water_heater.stagg_ekg_kettle` | Water Heater | Main control, temperature settings |
| `sensor.stagg_ekg_current_temperature` | Sensor | Current water temperature |
| `sensor.stagg_ekg_target_temperature` | Sensor | Target temperature setting |
| `sensor.stagg_ekg_mode` | Sensor | Current operating mode |
| `switch.stagg_ekg_heating` | Switch | Direct heating element control |
| `switch.stagg_ekg_warming` | Switch | Warming mode control |
| `binary_sensor.stagg_ekg_power` | Binary Sensor | Power on/off status |
| `binary_sensor.stagg_ekg_low_water_warning` | Binary Sensor | Water level warning |

## Configuration

### Initial Setup
```yaml
# During integration setup, you'll be asked for:
- IP Address: 10.1.1.177 (default)
- Temperature Unit: Celsius or Fahrenheit
```

### Changing Temperature Units
1. Go to Settings → Devices & Services
2. Find "Stagg EKG+"
3. Click "CONFIGURE"
4. Select preferred unit
5. Submit - kettle display updates immediately

## Safety Features

### Water Detection
The integration monitors temperature to detect if water is present:
- If temperature < 30°C when trying to heat, a warning is logged
- Binary sensor `binary_sensor.stagg_ekg_low_water_warning` will be ON
- Helps prevent dry heating accidents

### Smart Power Management
- Automatically wakes kettle before heating
- Exits menu screens to ensure proper operation
- Clean shutdown when turning off

## Usage Examples

### Basic Heating
```yaml
service: water_heater.turn_on
target:
  entity_id: water_heater.stagg_ekg_kettle
data:
  temperature: 95  # Uses configured unit (C or F)
```

### With Water Check
```yaml
automation:
  - alias: "Morning Coffee - Safe"
    trigger:
      - platform: time
        at: "07:00:00"
    condition:
      - condition: state
        entity_id: binary_sensor.stagg_ekg_low_water_warning
        state: "off"  # Only run if water detected
    action:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.stagg_ekg_kettle
        data:
          temperature: 95
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.stagg_ekg_kettle
      - service: notify.mobile_app
        data:
          message: "Heating water for coffee"
```

### Temperature Alert
```yaml
automation:
  - alias: "Water Ready Notification"
    trigger:
      - platform: numeric_state
        entity_id: sensor.stagg_ekg_current_temperature
        above: 94  # Close to target
    condition:
      - condition: state
        entity_id: water_heater.stagg_ekg_kettle
        attribute: current_operation
        state: "heat"
    action:
      - service: notify.mobile_app
        data:
          message: "Kettle water is ready!"
          title: "Coffee Time"
```

## Python API Updates

The standalone `stagg_ekg_api.py` script now includes:

### New Methods
```python
kettle = StaggEKGClient(host="10.1.1.177")

# Power management
kettle.power_on()           # Wake screen and prepare kettle
kettle.start_heating()      # Smart heating start
kettle.stop_heating()       # Clean shutdown

# State properties
state = kettle.get_state()
state.is_powered_on         # True if not in Off mode
state.is_in_menu            # True if showing a menu
state.may_have_no_water     # True if temp < 30°C
state.screen_name           # Current screen ("wnd", "menu - hold.png", etc.)
```

### Enhanced Output
```python
state = kettle.get_state()
print(state)
# Output: Mode: S_Standby, Current: 46.0°C, Target: 100.0°C (46.0°F),
#         Time: 21:54, Display Unit: °C [LOW WATER WARNING]
```

## Technical Details

### Temperature Unit Sync
When you change units in Home Assistant:
1. Integration calls `setunitsc` or `setunitsf` on the kettle
2. Kettle's LCD updates to show new unit
3. All temperature displays in HA update
4. Setting is saved in config entry

### Power-On Sequence
```
1. Check current mode
2. If "Off" in mode: press button 1 (wake)
3. Press button 2 (exit menus, show main screen)
4. Press button 1 (start heating)
```

### Water Detection Logic
```python
may_have_no_water = current_temp_c < 30 or current_temp_c is None
```

This is a heuristic - if water temperature is very low, it likely means:
- No water in kettle
- Kettle sat idle for long time
- Sensor issue

## Known Behaviors

- **Menu Navigation**: Kettle has complex menu system; integration auto-exits menus before heating
- **Temperature Reading**: Current temp may show low values when cold; this is normal
- **Heating Flag**: The `ho` (heating on) flag in CLI may not immediately reflect GPIO state
- **Mode States**: Common modes include:
  - `S_Off` - Powered off
  - `S_Standby` - Standby (screen may be off)
  - `S_Heat` - Actively heating
  - `S_HeatOff` - Heat cycle finished
  - Modes with `+menu` indicate menu is showing

## Troubleshooting

### "Low Water Warning" always on
- Check if kettle actually has water
- If it does, water may be very cold - warning will clear as temp rises
- Sensor threshold is 30°C

### Screen doesn't turn on
- Use `kettle.power_on()` or the water heater's turn_on
- Integration now handles this automatically
- If stuck in menu, integration will exit it

### Temperature unit mismatch
- Check integration config (Settings → Integrations → Stagg EKG → Configure)
- Changing it will update both HA and kettle
- May need to restart integration if sync fails

## Files Updated

- `custom_components/stagg_ekg/kettle.py` - Added power_on, start_heating, stop_heating, water detection
- `custom_components/stagg_ekg/water_heater.py` - Uses new heating methods, water warnings
- `custom_components/stagg_ekg/binary_sensor.py` - NEW: Power and water sensors
- `custom_components/stagg_ekg/config_flow.py` - Temperature unit selection
- `custom_components/stagg_ekg/const.py` - Temperature unit constants
- `custom_components/stagg_ekg/__init__.py` - Unit sync on setup
- `stagg_ekg_api.py` - Standalone script with all new features
