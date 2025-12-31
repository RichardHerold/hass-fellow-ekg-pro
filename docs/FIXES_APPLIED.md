# Fixes Applied to Stagg EKG+ Integration

## Date: 2025-12-26

### Issue Summary
After extensive testing, we discovered two critical issues with the Home Assistant integration:

1. **Incorrect Temperature Field Parsing**
2. **Incorrect Dial Step Calculation**

---

## 1. Temperature Field Parsing Fix

### Problem
The integration was reading the wrong temperature fields from the kettle's state response.

### Root Cause
Initial assumption about field meanings was incorrect:
```
❌ OLD (Incorrect):
- temprT = current water temperature
- temprB = target temperature

✅ NEW (Correct):
- tempr  = current water temperature (actual water temp)
- temprT = target temperature (set via dial)
- temprB = maximum temperature (typically 100°C)
```

### Verification
Test conducted: Set kettle to 85°C via dial rotation
```
State before: value=80, temprT=40°C, tempr=~20°C
State after:  value=170, temprT=85°C, tempr=59°C (heating up)
```

This proved:
- `temprT` changed to 85°C (our target) ✓
- `tempr` showed actual water temp (59°C while heating) ✓
- `temprB` stayed at 100°C (maximum) ✓

### Files Changed
1. **custom_components/stagg_ekg/kettle.py**
   - Line 89: Changed from `temprT` to `tempr` for current_temp_c
   - Line 90: Changed from `temprB` to `temprT` for set_temp_c

2. **stagg_ekg_api.py**
   - Line 103: Changed from `temprT` to `tempr` for current_temp_c
   - Line 104: Changed from `temprB` to `temprT` for set_temp_c

---

## 2. Dial Step Calculation Fix

### Problem
Temperature changes were calculated with wrong step size (5.5°C vs actual 0.5°C).

### Root Cause
Misunderstanding of the "2C" format and dial rotation behavior.

### Verification
Test conducted: Rotate dial from 40°C to 85°C
```
Temperature difference: 85°C - 40°C = 45°C
Steps executed: 90 rotations
Actual step size: 45°C ÷ 90 steps = 0.5°C per step
```

Each dial rotation increases the internal "value" by 1, which equals 0.5°C:
```
value = temperature_celsius × 2

Example:
- 40°C → value 80
- 85°C → value 170
- Difference: 170 - 80 = 90 steps
- 90 steps × 0.5°C = 45°C ✓
```

### Files Changed
1. **custom_components/stagg_ekg/water_heater.py**
   ```python
   # OLD (Incorrect):
   steps = int(round(temp_diff / 5.5))

   # NEW (Correct):
   steps = int(round(temp_diff * 2))  # Each step = 0.5°C
   ```

---

## 3. Documentation Updates

### KETTLE_SPECS.md
Updated to reflect correct field meanings and calculations:
- Fixed temperature field descriptions
- Corrected dial step calculation (0.5°C per click)
- Updated example code to use proper formula
- Added verified test results

---

## Testing Results

### Before Fixes
- Setting 85°C would require ~8 steps (45°C ÷ 5.5 = 8.18)
- Would only reach ~44°C instead of 85°C
- Reading wrong temperature values (showing target as current, etc.)

### After Fixes
- Setting 85°C requires 90 steps (45°C × 2 = 90)
- Successfully reaches exactly 85°C ✓
- Correctly displays current water temp vs target temp ✓

### Verification Command
```bash
curl -s 'http://10.1.1.177/cli?cmd=state' | grep -E "(tempr=|temprT=|value=)"
```

Expected output when set to 85°C:
```
value=170           # Dial position (85 × 2)
tempr=XX.XX C       # Actual water temperature (varies)
temprT=85.000000 C  # Target temperature
```

---

## Impact

✅ **Home Assistant Integration** - Now correctly sets and displays temperatures
✅ **Standalone API** - Now correctly parses all temperature fields
✅ **Documentation** - Accurately reflects kettle behavior
✅ **User Experience** - Temperature control works as expected

---

## Key Takeaways

1. **Always verify against actual hardware behavior** - Don't trust initial assumptions
2. **Test end-to-end** - Setting 85°C revealed both issues simultaneously
3. **The kettle firmware has no direct "set temperature" API** - Dial rotation is the only method
4. **Temperature format is "2C"** - All values are Celsius × 2

---

---

## 4. Operation Mode and Button Discovery Fix

### Problem
Setting operation mode to "heat" or "standby" in Home Assistant would activate the kettle but not turn on the display, or would get stuck in menus.

### Root Cause
**Critical Discovery:** The kettle has TWO different buttons:
- **Button 1**: Separate button on the base (opens startup menu when pressed from off)
- **Button 2**: The dial itself is pressable (wakes and starts heating directly)

The original code was using button 1, which opened menus instead of starting heating.

### Solution
Updated all power management to use button 2 (dial button):

```python
# OLD (Incorrect - used button 1):
def start_heating(self) -> str:
    if "Off" in state.mode:
        self._send_command("1")  # Opens menu!
    self._send_command("2")
    return self._send_command("1")

# NEW (Correct - uses button 2):
def start_heating(self) -> str:
    # Press button 2 (dial button) - wakes if off and starts heating
    return self._send_command("2")
```

Now:
- **HEAT mode** → Uses `start_heating()` which presses button 2 (dial button)
- **STANDBY mode** → Uses `power_on()` which presses button 2 (dial button)
- **OFF mode** → Uses `stop_heating()` (proper shutdown)
- **Heating switch ON** → Presses button 2 (dial button)

### Files Changed
- `/custom_components/stagg_ekg/water_heater.py` - Fixed async_set_operation_mode function
- `/custom_components/stagg_ekg/switch.py` - Fixed heating and warming switches

### Specific Switch Changes

**Heating Switch:**
- `async_turn_on`: Changed from `heat_on()` to `start_heating()` (wakes screen + starts heating)
- `async_turn_off`: Changed from `heat_off()` to `stop_heating()` (proper shutdown)

**Warming Switch:**
- `async_turn_on`: Now calls `power_on()` first to wake screen, then `warm_on()`
- `async_turn_off`: Unchanged (just calls `warm_off()`)

---

## Files Modified Summary

1. `/custom_components/stagg_ekg/kettle.py` - Fixed temperature field parsing
2. `/custom_components/stagg_ekg/water_heater.py` - Fixed step calculation + operation mode
3. `/custom_components/stagg_ekg/switch.py` - Fixed heating/warming switches to wake screen
4. `/stagg_ekg_api.py` - Fixed temperature field parsing
5. `/KETTLE_SPECS.md` - Updated documentation with correct information
