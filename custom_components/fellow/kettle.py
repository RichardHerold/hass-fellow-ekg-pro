"""Stagg EKG+ Kettle API Client"""

import logging
import time
import requests
import re
from typing import Optional
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

# Dial rotation constants
STEP_DELAY = 0.05        # 50ms between individual dial step commands
BATCH_SIZE = 20           # steps per batch before re-reading state
SETTLE_DELAY = 0.3        # 300ms pause before verification read
MAX_TOTAL_STEPS = 150     # safety cap (full range is ~120 steps, plus margin)

# Guide mode presets (Fahrenheit values, in dial order left-to-right)
GUIDE_PRESETS_F = (180, 195, 200, 205, 212)


@dataclass
class KettleState:
    """Represents the current state of the kettle"""
    mode: str
    current_temp_c: Optional[float]
    set_temp_c: float
    units: int  # 0=Fahrenheit, 1=Celsius (kettle's internal representation)
    clock: str
    ble_connected: bool
    heating: bool
    warming: bool
    screen_name: Optional[str] = None  # Current screen showing

    @property
    def is_heating(self) -> bool:
        """Return if kettle is in a heating cycle (based on mode, not GPIO)."""
        return self.mode in ("S_Heat", "S_StartupToTempr", "S_Heat+menu")

    @property
    def is_off(self) -> bool:
        """Return if kettle is in Off mode."""
        return self.mode == "S_Off"

    @property
    def is_holding(self) -> bool:
        """Return if kettle is in Hold (keep-warm) mode."""
        return self.mode == "S_Hold"

    @property
    def is_powered_on(self) -> bool:
        """Return if kettle is powered on (not in Off mode)."""
        return not self.is_off

    @property
    def is_in_menu(self) -> bool:
        """Return if kettle is showing a menu screen."""
        return "menu" in self.mode.lower() if self.mode else False

    @property
    def is_docked(self) -> bool:
        """Whether the kettle is sitting on the base."""
        return self.current_temp_c is not None

    @property
    def may_have_no_water(self) -> bool:
        """Return if kettle may not have water (temp < 30C heuristic)."""
        if self.current_temp_c is None:
            return True
        return self.current_temp_c < 30

    @property
    def current_temperature(self) -> Optional[float]:
        """Return current temperature in Celsius."""
        return self.current_temp_c

    @property
    def target_temperature(self) -> float:
        """Return target temperature in Celsius."""
        return self.set_temp_c


class StaggEKGClient:
    """Client for interacting with Stagg EKG+ kettle"""

    def __init__(self, host: str = "10.1.1.177", port: int = 80):
        """Initialize the client"""
        self.base_url = f"http://{host}:{port}"
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'StaggEKG-HA/1.0'})

    def _send_command(self, cmd: str) -> str:
        """Send a CLI command to the kettle"""
        url = f"{self.base_url}/cli"
        params = {"cmd": cmd}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to send command '{cmd}': {e}")

    def get_state(self) -> KettleState:
        """Get the current state of the kettle"""
        response = self._send_command("state")

        # Parse the response
        mode_match = re.search(r'mode=(\S+)', response)
        screen_match = re.search(r'scrname=(.+?)(?:\n|$)', response)
        # tempr = current water temperature
        # temprT = target temperature (set via dial)
        temp_c_match = re.search(r'tempr=([\d.]+)\s*C', response)
        temp_set_c_match = re.search(r'temprT=([\d.]+)\s*C', response)
        units_match = re.search(r'units=(\d+)', response)
        clock_match = re.search(r'clock=(\d+:\d+)', response)
        ble_match = re.search(r'ble conn=(\d+)', response)
        heating_match = re.search(r'ho\s+(\d+)', response)
        warming_match = re.search(r'wd\s+(\d+)', response)

        return KettleState(
            mode=mode_match.group(1) if mode_match else "Unknown",
            screen_name=screen_match.group(1).strip() if screen_match else None,
            current_temp_c=float(temp_c_match.group(1)) if temp_c_match else None,
            set_temp_c=float(temp_set_c_match.group(1)) if temp_set_c_match else 0,
            units=int(units_match.group(1)) if units_match else 1,
            clock=clock_match.group(1) if clock_match else "00:00",
            ble_connected=bool(int(ble_match.group(1))) if ble_match else False,
            heating=bool(int(heating_match.group(1))) if heating_match else False,
            warming=bool(int(warming_match.group(1))) if warming_match else False,
        )

    def heat_on(self) -> str:
        """Turn heating element on (direct GPIO)"""
        return self._send_command("heaton")

    def heat_off(self) -> str:
        """Turn heating element off (direct GPIO)"""
        return self._send_command("heatoff")

    def warm_on(self) -> str:
        """Turn warming on"""
        return self._send_command("warmon")

    def warm_off(self) -> str:
        """Turn warming off"""
        return self._send_command("warmoff")

    def press_button_1(self) -> str:
        """Simulate pressing button 1 (base button - opens menus)"""
        return self._send_command("1")

    def press_button_2(self) -> str:
        """Simulate pressing button 2 (dial press - wakes & starts heating)"""
        return self._send_command("2")

    def start_heating(self) -> str:
        """
        Start a heating cycle.

        State-aware: only sends the wake/heat command if the kettle isn't
        already heating. This avoids the button-2 toggle problem where
        pressing it while heating would stop it.
        """
        state = self.get_state()
        if state.is_heating:
            _LOGGER.debug("Kettle already heating, skipping start command")
            return "already heating"
        # Button 2 wakes the kettle (if off) and starts heating
        return self._send_command("2")

    def stop_heating(self, max_attempts: int = 3) -> str:
        """
        Stop heating or holding by telling the firmware to exit.

        Uses button 2 (the same way a human would cancel) rather than
        direct GPIO commands, so the firmware state machine stays
        consistent. Verifies the kettle actually stopped after each attempt.
        """
        for attempt in range(max_attempts):
            state = self.get_state()
            if not state.is_heating and not state.is_holding:
                return "stopped"

            _LOGGER.debug(
                "Sending stop command (attempt %d/%d, mode=%s)",
                attempt + 1, max_attempts, state.mode,
            )
            self._send_command("2")
            time.sleep(0.5)

        # Final check
        state = self.get_state()
        if state.is_heating or state.is_holding:
            _LOGGER.error(
                "Failed to stop kettle after %d attempts (mode=%s)",
                max_attempts, state.mode,
            )
        return "stopped"

    def set_warming(self, on: bool) -> str:
        """Enable or disable keep-warm mode."""
        if on:
            return self.warm_on()
        else:
            return self.warm_off()

    def _ensure_awake(self) -> KettleState:
        """Wake the kettle if it's off via button 2. Returns current state.

        Button 2 is the only clean wake path; it also starts heating as a
        side effect. The kettle passes through transitional states (logo,
        S_StartupToTempr, possibly S_Heat+menu) before settling.
        """
        state = self.get_state()
        if not state.is_off:
            return state

        _LOGGER.debug("Kettle is off — waking with button 2")
        self._send_command("2")
        for _ in range(10):  # up to 5 seconds
            time.sleep(0.5)
            state = self.get_state()
            if not state.is_off:
                return state

        _LOGGER.warning("Kettle did not wake after button 2 (mode=%s)", state.mode)
        return state

    def get_guide_mode(self) -> bool:
        """Check if guide mode is enabled."""
        response = self._send_command("prtsettings")
        match = re.search(r'guide=(\d+)', response)
        return bool(int(match.group(1))) if match else False

    def set_guide_mode(self, enabled: bool) -> str:
        """Enable or disable guide mode."""
        return self._send_command(f"setsetting guide {1 if enabled else 0}")

    def set_temperature(self, target_celsius: float) -> float:
        """
        Set target temperature, respecting guide mode when possible.

        If guide mode is on and the target matches a preset, navigates to
        that preset via dial rotation (left to reset, right to select).

        If guide mode is on but the target doesn't match a preset,
        temporarily disables guide mode, uses batched dial rotation, then
        re-enables guide mode.

        If guide mode is off, uses batched dial rotation directly.

        Wakes the kettle if it's off (which also starts heating as a side
        effect — there's no way to wake without heating).

        Args:
            target_celsius: Desired target temperature in Celsius (40-100).

        Returns:
            The actual target temperature (Celsius) achieved on the kettle.
        """
        target_celsius = max(40.0, min(100.0, target_celsius))
        target_f = round(target_celsius * 9 / 5 + 32)

        guide_on = self.get_guide_mode()
        preset_index = (
            GUIDE_PRESETS_F.index(target_f)
            if guide_on and target_f in GUIDE_PRESETS_F
            else None
        )

        if preset_index is not None:
            return self._set_temperature_preset(preset_index, target_f)

        return self._set_temperature_dial(target_celsius, guide_on)

    def _set_temperature_preset(self, preset_index: int, target_f: int) -> float:
        """Navigate to a guide mode preset by index."""
        self._ensure_awake()

        # Reset to leftmost preset
        for _ in range(len(GUIDE_PRESETS_F)):
            self._send_command("left")
            time.sleep(STEP_DELAY)
        time.sleep(SETTLE_DELAY)

        # Navigate to target preset
        for _ in range(preset_index):
            self._send_command("right")
            time.sleep(STEP_DELAY)
        time.sleep(SETTLE_DELAY)

        state = self.get_state()
        _LOGGER.debug(
            "Preset selected: %dF (index %d), actual=%.1fC",
            target_f, preset_index, state.set_temp_c,
        )
        return state.set_temp_c

    def _set_temperature_dial(self, target_celsius: float, guide_on: bool) -> float:
        """Set temperature using batched dial rotation with verification."""
        if guide_on:
            _LOGGER.debug("Target doesn't match a preset — temporarily disabling guide mode")
            self.set_guide_mode(False)
            time.sleep(0.3)

        try:
            self._ensure_awake()

            total_steps_sent = 0

            while total_steps_sent < MAX_TOTAL_STEPS:
                state = self.get_state()
                current_target_c = state.set_temp_c

                if state.units == 0:
                    # Fahrenheit mode: each dial step is 1F
                    target_f = round(target_celsius * 9 / 5 + 32)
                    current_f = round(current_target_c * 9 / 5 + 32)
                    steps_needed = target_f - current_f
                else:
                    # Celsius mode: each dial step is 0.5C
                    steps_needed = int(round((target_celsius - current_target_c) * 2))

                if steps_needed == 0:
                    _LOGGER.debug(
                        "Temperature set complete: target=%.1fC, actual=%.1fC, total_steps=%d",
                        target_celsius, current_target_c, total_steps_sent,
                    )
                    return current_target_c

                # Send up to BATCH_SIZE steps
                batch = min(abs(steps_needed), BATCH_SIZE)
                cmd = "right" if steps_needed > 0 else "left"

                _LOGGER.debug(
                    "Sending %d dial steps (%s): current=%.1fC, target=%.1fC, remaining=%d",
                    batch, cmd, current_target_c, target_celsius, abs(steps_needed),
                )

                for _ in range(batch):
                    self._send_command(cmd)
                    time.sleep(STEP_DELAY)

                total_steps_sent += batch
                time.sleep(SETTLE_DELAY)

            # Exhausted step budget - return whatever we achieved
            final_state = self.get_state()
            _LOGGER.warning(
                "Temperature set exhausted step budget (%d steps): target=%.1fC, actual=%.1fC",
                total_steps_sent, target_celsius, final_state.set_temp_c,
            )
            return final_state.set_temp_c
        finally:
            if guide_on:
                _LOGGER.debug("Restoring guide mode")
                self.set_guide_mode(True)

    def rotate_dial_left(self, steps: int = 1) -> str:
        """Rotate dial left (decrease temperature)"""
        result = ""
        for _ in range(steps):
            result = self._send_command("left")
            if steps > 1:
                time.sleep(STEP_DELAY)
        return result

    def rotate_dial_right(self, steps: int = 1) -> str:
        """Rotate dial right (increase temperature)"""
        result = ""
        for _ in range(steps):
            result = self._send_command("right")
            if steps > 1:
                time.sleep(STEP_DELAY)
        return result

    def set_units_fahrenheit(self) -> str:
        """Set temperature units to Fahrenheit"""
        return self._send_command("setunitsf")

    def set_units_celsius(self) -> str:
        """Set temperature units to Celsius"""
        return self._send_command("setunitsc")
