"""HTTP CLI client for Fellow Stagg EKG+ / EKG Pro kettles.

The kettle exposes an unauthenticated plain-text debug CLI at
``GET http://<host>/cli?cmd=<command>``. Command vocabulary differs between
firmwares; this client sticks to commands verified on real hardware:

- ``ss S_Heat`` / ``ss S_Hold`` / ``ss S_Off`` — state-machine control
  (verified on the EKG Pro by the stagg-ekg-pro reverse-engineering effort).
- ``setsettingd settempr <F>`` — sets the *active* target temperature on the
  Pro. The older ``setsetting settempr`` variant only saves a preference on
  the EKG+, so it's kept as a fallback, followed by dial emulation.

DANGER — commands this client refuses to send (see FORBIDDEN_COMMANDS):
a bare ``ss`` reboots the kettle, ``adcsamples`` crashes the firmware, and
``reset`` reboots the device.
"""

import logging
import time
import requests
import re
from typing import Optional

from .parser import (  # noqa: F401 - errors re-exported for callers
    KettleResponseError,
    KettleTimeoutError,
    KettleTransientError,
    ParsedState,
    parse_fwinfo,
    parse_settings,
    parse_state,
    parse_wifiprt_mac,
)

_LOGGER = logging.getLogger(__name__)

# Backwards-compatible alias for the platform files' type hints.
KettleState = ParsedState

# Dial rotation constants
STEP_DELAY = 0.05        # 50ms between individual dial step commands
BATCH_SIZE = 20           # steps per batch before re-reading state
SETTLE_DELAY = 0.3        # 300ms pause before verification read
MAX_TOTAL_STEPS = 150     # safety cap (full range is ~120 steps, plus margin)

# Guide mode presets (Fahrenheit values, in dial order left-to-right)
GUIDE_PRESETS_F = (180, 195, 200, 205, 212)

# Command vocabulary. Only send commands from this list (or the dial/button
# primitives below); the firmware CLI includes destructive commands.
CMD_STATE = "state"
CMD_HEAT = "ss S_Heat"
CMD_HOLD = "ss S_Hold"
CMD_OFF = "ss S_Off"
# Active-target set, verified on the EKG Pro. Fahrenheit, one decimal.
CMD_SET_TARGET_DIRECT = "setsettingd settempr {temp_f:.1f}"
# Older EKG+ variant; on some firmwares this only saves a preference.
CMD_SET_TARGET_LEGACY = "setsetting settempr {temp_f:d}"
CMD_SET_HOLD_MINUTES = "setsetting hold {minutes:d}"
CMD_SET_GUIDE = "setsetting guide {enabled:d}"
CMD_PRTSETTINGS = "prtsettings"
CMD_FWINFO = "fwinfo"
CMD_WIFIPRT = "wifiprt"
CMD_UNITS_C = "setunitsc"
CMD_UNITS_F = "setunitsf"
CMD_DIAL_LEFT = "left"
CMD_DIAL_RIGHT = "right"
CMD_PRESS_DIAL = "2"
# Direct heater-element GPIO, bypassing the firmware state machine.
CMD_HEATER_GPIO_ON = "heaton"
CMD_HEATER_GPIO_OFF = "heatoff"

# Commands that damage or reboot the device. A bare "ss" (no argument)
# reboots the kettle, "adcsamples" crashes the firmware, and "reset"
# reboots it. Guarded in _send_command so no code path — present or
# future — can send them by accident.
FORBIDDEN_COMMANDS = frozenset({"ss", "adcsamples", "reset"})


class StaggEKGClient:
    """Client for interacting with a Stagg EKG+ / EKG Pro kettle."""

    def __init__(
        self,
        host: str,
        port: int = 80,
        temp_method: str = "direct",
    ):
        """Initialize the client.

        temp_method controls how `set_temperature` reaches the target:
          - "direct": firmware set-target command with verification (fast)
          - "dial":   emulate physical dial (works on older/quirky firmwares)
        """
        self.host = host
        self.base_url = f"http://{host}:{port}"
        self.temp_method = temp_method
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'StaggEKG-HA/1.0'})

    def _send_command(self, cmd: str, retries: int = 1, timeout: float = 5.0) -> str:
        """Send a CLI command to the kettle, retrying on timeout.

        The kettle's HTTP server goes unresponsive for several seconds
        during mode transitions (especially when turning off), so a single
        read timeout is not a reliable signal that anything is wrong.
        Worst-case wall time with the defaults is ~10.5s (2 × 5s + 0.5s
        backoff). If the kettle is still unresponsive after the final
        attempt, raise KettleTimeoutError so callers can distinguish it
        from other request failures.
        """
        if cmd.strip() in FORBIDDEN_COMMANDS:
            raise ValueError(
                f"Refusing to send {cmd.strip()!r}: it reboots or crashes the kettle"
            )

        url = f"{self.base_url}/cli"
        params = {"cmd": cmd}

        last_timeout: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                return response.text
            except requests.exceptions.Timeout as e:
                last_timeout = e
                if attempt < retries:
                    _LOGGER.debug(
                        "Kettle timeout on '%s' (attempt %d/%d), retrying",
                        cmd, attempt + 1, retries + 1,
                    )
                    time.sleep(0.5)
            except requests.exceptions.RequestException as e:
                raise Exception(f"Failed to send command '{cmd}': {e}")

        raise KettleTimeoutError(
            f"Kettle did not respond to '{cmd}' after {retries + 1} attempts: {last_timeout}"
        )

    def get_state(self) -> ParsedState:
        """Get the current state of the kettle."""
        response = self._send_command(CMD_STATE)
        # The raw response is the primary diagnostic for firmware-format
        # differences between kettle models — always log it at debug level.
        _LOGGER.debug("Raw state response from %s: %r", self.host, response)
        return parse_state(response)

    def get_raw(self, cmd: str) -> str:
        """Send a read-only diagnostic command and return the raw text."""
        if cmd not in (CMD_STATE, CMD_PRTSETTINGS, CMD_FWINFO, CMD_WIFIPRT):
            raise ValueError(f"Not a read-only diagnostic command: {cmd!r}")
        return self._send_command(cmd)

    def get_firmware_info(self) -> dict:
        """Best-effort firmware metadata from fwinfo. Never raises."""
        try:
            return parse_fwinfo(self._send_command(CMD_FWINFO))
        except Exception as err:
            _LOGGER.debug("fwinfo unavailable: %s", err)
            return {}

    def get_mac(self) -> Optional[str]:
        """Best-effort MAC address from wifiprt. Never raises."""
        try:
            return parse_wifiprt_mac(self._send_command(CMD_WIFIPRT))
        except Exception as err:
            _LOGGER.debug("wifiprt unavailable: %s", err)
            return None

    def get_settings(self) -> dict:
        """Parsed prtsettings output."""
        return parse_settings(self._send_command(CMD_PRTSETTINGS))

    def start_heating(self) -> str:
        """Start a heating cycle via direct state command.

        `ss S_Heat` tells the firmware to enter the Heat state from any
        starting state, so we don't need to wake the kettle first. We still
        skip the command if the kettle is already heating to avoid
        unnecessary chatter.
        """
        state = self.get_state()
        if state.is_heating:
            _LOGGER.debug("Kettle already heating, skipping start command")
            return "already heating"
        return self._send_command(CMD_HEAT)

    def start_hold(self) -> str:
        """Enter Hold (keep-warm) mode via direct state command."""
        state = self.get_state()
        if state.is_holding:
            _LOGGER.debug("Kettle already holding, skipping hold command")
            return "already holding"
        return self._send_command(CMD_HOLD)

    def stop_heating(self, max_attempts: int = 3) -> str:
        """Stop heating or holding via direct state command.

        `ss S_Off` puts the firmware in the Off state directly. We retry
        and verify because some firmware revisions occasionally drop the
        first command during a state transition.
        """
        for attempt in range(max_attempts):
            state = self.get_state()
            if not state.is_heating and not state.is_holding:
                return "stopped"

            _LOGGER.debug(
                "Sending stop command (attempt %d/%d, mode=%s)",
                attempt + 1, max_attempts, state.mode,
            )
            self._send_command(CMD_OFF)
            time.sleep(0.5)

        # Final check
        state = self.get_state()
        if state.is_heating or state.is_holding:
            _LOGGER.error(
                "Failed to stop kettle after %d attempts (mode=%s)",
                max_attempts, state.mode,
            )
        return "stopped"

    def heat_on(self) -> str:
        """ADVANCED: switch the heater element GPIO on directly.

        This bypasses the firmware state machine and its safety logic —
        the display won't reflect it and the normal auto-shutoff behavior
        may not apply. Prefer start_heating(); use this only deliberately.
        """
        return self._send_command(CMD_HEATER_GPIO_ON)

    def heat_off(self) -> str:
        """ADVANCED: switch the heater element GPIO off directly.

        Counterpart of heat_on(); bypasses the firmware state machine.
        """
        return self._send_command(CMD_HEATER_GPIO_OFF)

    def set_hold_minutes(self, minutes: int) -> str:
        """Set the keep-warm hold duration (1-120 minutes)."""
        minutes = max(1, min(120, int(minutes)))
        return self._send_command(CMD_SET_HOLD_MINUTES.format(minutes=minutes))

    def _ensure_awake(self) -> ParsedState:
        """Wake the kettle if it's off via a dial press. Returns current state.

        The dial press ("2") is the only clean wake path; it also starts
        heating as a side effect. The kettle passes through transitional
        states (logo, S_StartupToTempr, possibly S_Heat+menu) before
        settling. Only used by the dial-emulation fallback.
        """
        state = self.get_state()
        if not state.is_off:
            return state

        _LOGGER.debug("Kettle is off — waking with a dial press")
        self._send_command(CMD_PRESS_DIAL)
        for _ in range(10):  # up to 5 seconds
            time.sleep(0.5)
            state = self.get_state()
            if not state.is_off:
                return state

        _LOGGER.warning("Kettle did not wake after dial press (mode=%s)", state.mode)
        return state

    def get_guide_mode(self) -> bool:
        """Check if guide mode is enabled."""
        response = self._send_command(CMD_PRTSETTINGS)
        match = re.search(r'guide=(\d+)', response)
        return bool(int(match.group(1))) if match else False

    def set_guide_mode(self, enabled: bool) -> str:
        """Enable or disable guide mode."""
        return self._send_command(CMD_SET_GUIDE.format(enabled=1 if enabled else 0))

    def set_temperature(self, target_celsius: float) -> float:
        """
        Set target temperature.

        Default ("direct") path: the firmware set-target command with a
        read-back verification, falling back to the legacy EKG+ command and
        finally to dial emulation. The "dial" method skips straight to dial
        emulation for firmwares where none of the set commands work.

        Args:
            target_celsius: Desired target temperature in Celsius (40-100).

        Returns:
            The actual target temperature (Celsius) achieved on the kettle.
        """
        target_celsius = max(40.0, min(100.0, target_celsius))

        if self.temp_method == "direct":
            return self._set_temperature_direct(target_celsius)

        guide_on = self.get_guide_mode()
        target_f = round(target_celsius * 9 / 5 + 32)
        preset_index = (
            GUIDE_PRESETS_F.index(target_f)
            if guide_on and target_f in GUIDE_PRESETS_F
            else None
        )

        if preset_index is not None:
            return self._set_temperature_preset(preset_index, target_f)

        return self._set_temperature_dial(target_celsius, guide_on)

    def _verify_target(self, target_f: float) -> Optional[float]:
        """Read back the target after a set command.

        Returns the achieved Celsius target when it matches the request
        (within the kettle's 1F display precision), else None.
        """
        time.sleep(SETTLE_DELAY)
        state = self.get_state()
        if state.target_temp_c is None:
            return None
        actual_f = state.target_temp_c * 9 / 5 + 32
        if abs(actual_f - target_f) <= 1.0:
            return state.target_temp_c
        return None

    def _set_temperature_direct(self, target_celsius: float) -> float:
        """Set the active target via firmware command, with fallbacks.

        1. `setsettingd settempr <F>` — sets the active target on the
           EKG Pro (verified).
        2. `setsetting settempr <F>` — older EKG+ variant; on some
           firmwares this only saves a preference for the next power-on.
        3. Dial emulation — works everywhere the dial works.
        """
        target_f = round(target_celsius * 9 / 5 + 32, 1)

        self._send_command(CMD_SET_TARGET_DIRECT.format(temp_f=target_f))
        achieved = self._verify_target(target_f)
        if achieved is not None:
            _LOGGER.debug(
                "setsettingd set target to %.1fF (%.1fC)", target_f, achieved
            )
            return achieved

        _LOGGER.debug(
            "setsettingd settempr not confirmed; trying legacy setsetting variant"
        )
        self._send_command(CMD_SET_TARGET_LEGACY.format(temp_f=round(target_f)))
        achieved = self._verify_target(target_f)
        if achieved is not None:
            _LOGGER.debug(
                "legacy settempr set target to %.1fF (%.1fC)", target_f, achieved
            )
            return achieved

        _LOGGER.warning(
            "Firmware set-target commands appear unsupported (asked %.1fF); "
            "falling back to dial emulation. Switch this device to the "
            "'dial' temperature-setting method in options to skip these "
            "probes in the future.",
            target_f,
        )
        guide_on = self.get_guide_mode()
        return self._set_temperature_dial(target_celsius, guide_on)

    def _set_temperature_preset(self, preset_index: int, target_f: int) -> float:
        """Navigate to a guide mode preset by index."""
        self._ensure_awake()

        # Reset to leftmost preset
        for _ in range(len(GUIDE_PRESETS_F)):
            self._send_command(CMD_DIAL_LEFT)
            time.sleep(STEP_DELAY)
        time.sleep(SETTLE_DELAY)

        # Navigate to target preset
        for _ in range(preset_index):
            self._send_command(CMD_DIAL_RIGHT)
            time.sleep(STEP_DELAY)
        time.sleep(SETTLE_DELAY)

        state = self.get_state()
        _LOGGER.debug(
            "Preset selected: %dF (index %d), actual=%s",
            target_f, preset_index, state.target_temp_c,
        )
        return state.target_temp_c if state.target_temp_c is not None else float(
            (target_f - 32) * 5 / 9
        )

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
                current_target_c = state.target_temp_c
                if current_target_c is None:
                    _LOGGER.warning(
                        "Kettle reports no target temperature; aborting dial set"
                    )
                    return target_celsius

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
                cmd = CMD_DIAL_RIGHT if steps_needed > 0 else CMD_DIAL_LEFT

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
                "Temperature set exhausted step budget (%d steps): target=%.1fC, actual=%s",
                total_steps_sent, target_celsius, final_state.target_temp_c,
            )
            return (
                final_state.target_temp_c
                if final_state.target_temp_c is not None
                else target_celsius
            )
        finally:
            if guide_on:
                _LOGGER.debug("Restoring guide mode")
                self.set_guide_mode(True)

    def rotate_dial_left(self, steps: int = 1) -> str:
        """Rotate dial left (decrease temperature)"""
        result = ""
        for _ in range(steps):
            result = self._send_command(CMD_DIAL_LEFT)
            if steps > 1:
                time.sleep(STEP_DELAY)
        return result

    def rotate_dial_right(self, steps: int = 1) -> str:
        """Rotate dial right (increase temperature)"""
        result = ""
        for _ in range(steps):
            result = self._send_command(CMD_DIAL_RIGHT)
            if steps > 1:
                time.sleep(STEP_DELAY)
        return result

    def set_units_fahrenheit(self) -> str:
        """Set the kettle's display units to Fahrenheit"""
        return self._send_command(CMD_UNITS_F)

    def set_units_celsius(self) -> str:
        """Set the kettle's display units to Celsius"""
        return self._send_command(CMD_UNITS_C)
