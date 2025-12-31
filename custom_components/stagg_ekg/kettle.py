"""Stagg EKG+ Kettle API Client"""

import requests
import re
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class KettleState:
    """Represents the current state of the kettle"""
    mode: str
    current_temp_c: Optional[float]
    set_temp_c: float
    set_temp_f: float
    units: int  # 0=Fahrenheit, 1=Celsius (kettle's internal representation)
    clock: str
    ble_connected: bool
    heating: bool
    warming: bool
    screen_name: Optional[str] = None  # Current screen showing

    @property
    def is_heating(self) -> bool:
        """Return if kettle is currently heating."""
        return self.heating

    @property
    def is_powered_on(self) -> bool:
        """Return if kettle is powered on (not in Off mode)."""
        return "Off" not in self.mode

    @property
    def is_in_menu(self) -> bool:
        """Return if kettle is showing a menu screen."""
        return "menu" in self.mode.lower() if self.mode else False

    @property
    def may_have_no_water(self) -> bool:
        """
        Return if kettle may not have water.
        If current temp is very low (< 30°C) and not increasing, may indicate no water.
        """
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
        temp_set_f_match = re.search(r'temps=(\d+)', response)
        units_match = re.search(r'units=(\d+)', response)
        clock_match = re.search(r'clock=(\d+:\d+)', response)
        ble_match = re.search(r'ble conn=(\d+)', response)
        heating_match = re.search(r'ho\s+(\d+)', response)
        warming_match = re.search(r'wd\s+(\d+)', response)

        # Parse set temp in Fahrenheit (stored in 2C units, so divide by 2)
        set_temp_f = int(temp_set_f_match.group(1)) / 2 if temp_set_f_match else 0

        return KettleState(
            mode=mode_match.group(1) if mode_match else "Unknown",
            screen_name=screen_match.group(1).strip() if screen_match else None,
            current_temp_c=float(temp_c_match.group(1)) if temp_c_match else None,
            set_temp_c=float(temp_set_c_match.group(1)) if temp_set_c_match else 0,
            set_temp_f=set_temp_f,
            units=int(units_match.group(1)) if units_match else 1,
            clock=clock_match.group(1) if clock_match else "00:00",
            ble_connected=bool(int(ble_match.group(1))) if ble_match else False,
            heating=bool(int(heating_match.group(1))) if heating_match else False,
            warming=bool(int(warming_match.group(1))) if warming_match else False,
        )

    def get_settings(self) -> Dict[str, Any]:
        """Get all kettle settings"""
        response = self._send_command("prtsettings")
        settings = {}

        # Parse settings
        for line in response.split('\n'):
            if line.startswith('st: '):
                match = re.search(r'st: (\w+)=(.+)', line)
                if match:
                    key, value = match.groups()
                    settings[key] = value.strip()

        return settings

    def heat_on(self) -> str:
        """Turn heating on"""
        return self._send_command("heaton")

    def heat_off(self) -> str:
        """Turn heating off"""
        return self._send_command("heatoff")

    def warm_on(self) -> str:
        """Turn warming on"""
        return self._send_command("warmon")

    def warm_off(self) -> str:
        """Turn warming off"""
        return self._send_command("warmoff")

    def press_button_1(self) -> str:
        """Simulate pressing button 1 (power/start)"""
        return self._send_command("1")

    def press_button_2(self) -> str:
        """Simulate pressing button 2 (hold temp)"""
        return self._send_command("2")

    def power_on(self) -> str:
        """
        Power on the kettle and wake the screen.
        This ensures the kettle is ready for operation.
        Button 2 is the dial button - pressing it wakes the kettle directly to main screen.
        """
        # Press button 2 (dial button) to wake and go to main screen
        return self._send_command("2")

    def start_heating(self) -> str:
        """
        Start a heating cycle.
        Wakes the kettle if needed and initiates heating.
        Button 2 (dial button) wakes the kettle and starts heating directly.
        """
        # Press button 2 (dial button) - wakes if off and starts heating
        return self._send_command("2")

    def stop_heating(self) -> str:
        """
        Stop heating and return to standby.
        """
        import time

        # Press button 2 to stop/cancel heating
        self._send_command("2")

        # Small delay to let kettle process the command
        time.sleep(0.5)

        # Also turn off heating element to ensure it's off
        return self.heat_off()

    def rotate_dial_left(self, steps: int = 1) -> str:
        """Rotate dial left (decrease temperature)"""
        result = ""
        for _ in range(steps):
            result = self._send_command("left")
        return result

    def rotate_dial_right(self, steps: int = 1) -> str:
        """Rotate dial right (increase temperature)"""
        result = ""
        for _ in range(steps):
            result = self._send_command("right")
        return result

    def set_units_fahrenheit(self) -> str:
        """Set temperature units to Fahrenheit"""
        return self._send_command("setunitsf")

    def set_units_celsius(self) -> str:
        """Set temperature units to Celsius"""
        return self._send_command("setunitsc")
