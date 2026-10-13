"""Response parsing for the Fellow Stagg EKG kettle HTTP CLI.

This module is pure Python — no Home Assistant and no ``requests`` imports —
so the probe script (``examples/probe_kettle.py``) and the unit tests can use
it without installing Home Assistant.

The kettle's ``/cli`` endpoint returns free-form plain text whose exact shape
varies between models (Stagg EKG+ vs EKG Pro) and firmware builds. Known
variations that the parsers here must tolerate:

- Temperature fields may or may not carry a unit suffix
  (``tempr=85.0 C`` on the EKG+ vs ``tempr=185.0`` observed on the Pro).
- With no suffix, values may be Celsius or Fahrenheit depending on model and
  the ``units`` setting.
- Status flags live on a ``ketl=`` line (``ketl= ho 0 wd 0 nw 0 ...``) whose
  set of flags is not fixed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class KettleTransientError(Exception):
    """Base class for transient kettle failures the caller can ride out.

    The kettle briefly stops answering HTTP (or returns truncated data)
    when it transitions to Off and at other moments. Callers can treat
    any subclass as a non-fatal hiccup and keep their last known state.
    """


class KettleTimeoutError(KettleTransientError):
    """Raised when the kettle's HTTP server doesn't respond in time."""


class KettleResponseError(KettleTransientError):
    """Raised when the kettle's response can't be parsed (missing fields)."""


class KettleCliMutedError(KettleResponseError):
    """The kettle answered with its command form but no command output.

    Firmware 1.2.24 and later answer every ``/cli`` request this way: the
    command may still run, but its output never reaches HTTP. A one-off
    occurrence is treated like any other transient failure.
    """


class KettleCommandError(Exception):
    """A command could not be delivered for a non-transient reason."""


# Plausible water-temperature window (Celsius). Values outside it are
# treated as sentinels the firmware emits when the kettle is off the base
# or the ADC reads garbage.
PLAUSIBLE_TEMP_MIN_C = -5.0
PLAUSIBLE_TEMP_MAX_C = 120.0

MODE_RE = re.compile(r"\bmode\s*=\s*(\S+)")
SCREEN_RE = re.compile(r"\bscrname\s*=\s*(.+?)(?:\r?\n|$)")
# temprT/temprB must not be captured by the current-temperature pattern,
# hence the negative lookahead. The unit suffix is optional: the EKG+
# prints "tempr=85.0 C" while the Pro has been seen printing bare values.
CURRENT_TEMP_RE = re.compile(r"\btempr(?![TB])\s*=\s*(-?\d+(?:\.\d+)?)\s*([CFcf])?(?![A-Za-z])")
TARGET_TEMP_RE = re.compile(r"\btemprT\s*=\s*(-?\d+(?:\.\d+)?)\s*([CFcf])?(?![A-Za-z])")
BOIL_TEMP_RE = re.compile(r"\btemprB\s*=\s*(-?\d+(?:\.\d+)?)\s*([CFcf])?(?![A-Za-z])")
UNITS_RE = re.compile(r"\bunits\s*=\s*(\d+)")
CLOCK_RE = re.compile(r"\bclock\s*=\s*(\d+:\d+)")
BLE_RE = re.compile(r"\bble\s*conn\s*=\s*(\d+)")
# Flags are parsed only from the ketl= line, never from the whole response
# (the old loose patterns like r'ho\s+(\d+)' could match unrelated text).
KETL_LINE_RE = re.compile(r"\bketl\s*=\s*(.*)$", re.MULTILINE)
FLAG_PAIR_RE = re.compile(r"([A-Za-z]+)\s+(\d+)")

MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})")

# fwinfo output shape varies by firmware; scan for anything version-like.
FWINFO_PATTERNS = {
    "version": re.compile(r"(?im)^(?!.*\bidf\b).*?\b(?:app\s*)?version\s*[:=]?\s*(\S.*?)\s*$"),
    "project": re.compile(r"(?im)^.*?\bproject(?:\s*name)?\s*[:=]\s*(\S.*?)\s*$"),
    "compile_time": re.compile(r"(?im)^.*?\bcompile(?:d)?\s*(?:time|date)?\s*[:=]\s*(\S.*?)\s*$"),
    "idf": re.compile(r"(?im)^.*?\bidf\s*(?:version)?\s*[:=]?\s*(v?\d\S*)\s*$"),
}

SETTING_LINE_RE = re.compile(r"^\s*(?:st:\s*)?(\w+)\s*=\s*(.+?)\s*$", re.MULTILINE)

# Warn about magnitude-based unit inference only once per process — it means
# we're guessing and want a capture of the real response, but repeating the
# warning every 10s poll would flood the log.
_warned_magnitude_inference = False  # pylint: disable=invalid-name


def _to_celsius(
    value: float,
    suffix: Optional[str],
    units_field: Optional[int],
) -> float:
    """Convert a temperature field to Celsius.

    Resolution order: an explicit C/F suffix on the field wins; otherwise the
    response's ``units`` setting (0=Fahrenheit, 1=Celsius) decides; with
    neither, fall back to magnitude (a kettle can't be set above 100°C /
    212°F, so anything above 120 must be Fahrenheit).
    """
    global _warned_magnitude_inference

    if suffix:
        return value if suffix.upper() == "C" else (value - 32.0) * 5.0 / 9.0
    if units_field == 1:
        return value
    if units_field == 0:
        return (value - 32.0) * 5.0 / 9.0

    inferred_f = value > 120.0
    if not _warned_magnitude_inference:
        _warned_magnitude_inference = True
        _LOGGER.warning(
            "Kettle response has no temperature unit suffix and no units= "
            "field; inferring %s from magnitude (%.1f). Please capture the "
            "raw 'state' output with examples/probe_kettle.py and report it.",
            "Fahrenheit" if inferred_f else "Celsius",
            value,
        )
    return (value - 32.0) * 5.0 / 9.0 if inferred_f else value


def _plausible_or_none(temp_c: Optional[float]) -> Optional[float]:
    """Discard sentinel/garbage readings (kettle lifted, ADC noise)."""
    if temp_c is None:
        return None
    if PLAUSIBLE_TEMP_MIN_C <= temp_c <= PLAUSIBLE_TEMP_MAX_C:
        return round(temp_c, 2)
    return None


@dataclass
class ParsedState:
    """Parsed snapshot of the kettle's ``state`` response."""

    mode: str
    current_temp_c: Optional[float] = None
    target_temp_c: Optional[float] = None
    boil_temp_c: Optional[float] = None
    units: Optional[int] = None  # 0=Fahrenheit, 1=Celsius (display setting)
    clock: Optional[str] = None
    ble_connected: Optional[bool] = None
    flags: dict = field(default_factory=dict)
    screen_name: Optional[str] = None
    # True when a tempr= field existed in the response at all — lets callers
    # distinguish "kettle reports no plausible temperature" (lifted) from
    # "response didn't include the field" (parse anomaly / truncation).
    temp_field_present: bool = False
    raw: str = ""

    @property
    def is_heating(self) -> bool:
        """Heating cycle active (mode-based; includes menu-overlay variants)."""
        return self.mode.startswith("S_Heat") or self.mode == "S_StartupToTempr"

    @property
    def is_off(self) -> bool:
        return self.mode == "S_Off"

    @property
    def is_holding(self) -> bool:
        """Hold (keep-warm) mode active."""
        return self.mode.startswith("S_Hold")

    @property
    def is_powered_on(self) -> bool:
        return not self.is_off

    @property
    def is_in_menu(self) -> bool:
        return "menu" in self.mode.lower() if self.mode else False

    @property
    def warming(self) -> bool:
        """The ketl= line's `wd` flag, if reported.

        Documented as "wind-down" on the EKG Pro — NOT keep-warm; it can be
        set during ordinary heating. Entities key keep-warm off `is_holding`
        (Hold mode); this flag is exposed for diagnostics only.
        """
        return bool(self.flags.get("wd", 0))

    @property
    def is_docked(self) -> bool:
        """Whether the kettle is sitting on the base.

        Only meaningful when the response actually carried a temperature
        field; a truncated response must not read as "lifted".
        """
        return self.temp_field_present and self.current_temp_c is not None


# Every /cli reply carries this input form; real command output follows it.
_CLI_FORM_RE = re.compile(r"<form\b.*?</form>", re.IGNORECASE | re.DOTALL)


def cli_output_missing(text: str) -> bool:
    """True when a /cli reply is only the command form, with no output."""
    if not text or "CLI Command" not in text:
        return False
    return not _CLI_FORM_RE.sub("", text).strip()


def parse_state(text: str) -> ParsedState:
    """Parse a ``state`` response.

    Raises KettleResponseError when the response has no ``mode=`` field —
    there is no safe default for mode, and a truncated response should be
    treated like a transient failure. Every other field degrades to None.
    A reply that is only the command form raises KettleCliMutedError.
    """
    if cli_output_missing(text):
        raise KettleCliMutedError("Kettle replied with its command form but no output")

    mode_match = MODE_RE.search(text)
    if not mode_match:
        raise KettleResponseError(f"Kettle response missing 'mode' field: {text!r}")

    units_match = UNITS_RE.search(text)
    units = int(units_match.group(1)) if units_match else None

    def temp_field(regex: re.Pattern) -> tuple[Optional[float], bool]:
        match = regex.search(text)
        if not match:
            return None, False
        raw_value = float(match.group(1))
        return _plausible_or_none(_to_celsius(raw_value, match.group(2), units)), True

    current_temp_c, temp_field_present = temp_field(CURRENT_TEMP_RE)
    target_temp_c, _ = temp_field(TARGET_TEMP_RE)
    boil_temp_c, _ = temp_field(BOIL_TEMP_RE)

    flags: dict = {}
    ketl_match = KETL_LINE_RE.search(text)
    if ketl_match:
        flags = {
            name: int(value)
            for name, value in FLAG_PAIR_RE.findall(ketl_match.group(1))
        }

    screen_match = SCREEN_RE.search(text)
    clock_match = CLOCK_RE.search(text)
    ble_match = BLE_RE.search(text)

    return ParsedState(
        mode=mode_match.group(1),
        current_temp_c=current_temp_c,
        target_temp_c=target_temp_c,
        boil_temp_c=boil_temp_c,
        units=units,
        clock=clock_match.group(1) if clock_match else None,
        ble_connected=bool(int(ble_match.group(1))) if ble_match else None,
        flags=flags,
        screen_name=screen_match.group(1).strip() if screen_match else None,
        temp_field_present=temp_field_present,
        raw=text,
    )


# The water counts as ready within this margin of the target (the kettle's
# own display precision is 1F ≈ 0.6C, and readings wobble a little).
READY_MARGIN_C = 1.0


def is_water_ready(state: "ParsedState") -> bool:
    """Whether an active heat/hold cycle has reached its target.

    True only during an active cycle: a cold kettle whose target happens to
    be low, or an off kettle with hot water in it, is not "ready" — ready
    means the kettle is doing something and the water is at temperature.
    """
    if not (state.is_heating or state.is_holding):
        return False
    if state.current_temp_c is None or state.target_temp_c is None:
        return False
    return state.current_temp_c >= state.target_temp_c - READY_MARGIN_C


# Display-state options for the Kettle State enum sensor (Ember-mug-style
# lifecycle: one glanceable value instead of a raw firmware mode).
KETTLE_STATE_OPTIONS = ["off", "heating", "at_temperature", "keeping_warm"]


def kettle_display_state(state: "ParsedState") -> str:
    """Collapse the firmware state into a user-facing lifecycle value.

    "at_temperature" wins over heating/keeping_warm: an active cycle whose
    water is at target is the ready state, whether the mode is Heat or
    Hold. Unknown/transitional modes read as "off", matching the water
    heater's fallback.
    """
    if is_water_ready(state):
        return "at_temperature"
    if state.is_heating:
        return "heating"
    if state.is_holding:
        return "keeping_warm"
    return "off"


def state_problems(state: "ParsedState") -> list:
    """Explain why a parsed state is not good enough to run the integration.

    Used by the config flow to refuse setup when the kettle answered but
    the response couldn't be understood — connecting is not enough, since
    every temperature entity would be broken. Returns a list of
    human-readable problem strings; empty means the state is usable.
    """
    problems = []
    if not state.temp_field_present:
        problems.append("no 'tempr=' (current temperature) field in response")
    elif state.current_temp_c is None:
        problems.append(
            "current temperature is implausible (kettle may be off its base)"
        )
    if state.target_temp_c is None:
        problems.append("no usable 'temprT=' (target temperature) in response")
    return problems


# Tokens kept fully uppercase when prettifying firmware model names.
_UPPER_TOKENS = {"EKG", "SSP", "WIFI"}


def prettify_model_name(raw: Optional[str]) -> Optional[str]:
    """Turn a firmware project identifier into a human device name.

    e.g. 'stagg_ekg_pro' -> 'Stagg EKG Pro'. Returns None for blank or
    unusable input so callers can fall back to a generic name.
    """
    if not raw:
        return None
    cleaned = "".join(ch for ch in raw if ch.isprintable()).strip()
    words = [w for w in re.split(r"[\s_\-]+", cleaned) if w]
    if not words:
        return None
    pretty = " ".join(
        w.upper() if w.upper() in _UPPER_TOKENS else w.capitalize() for w in words
    )
    return pretty[:40].strip()


def parse_fwinfo(text: str) -> dict:
    """Extract whatever firmware metadata is recognizable in fwinfo output."""
    info: dict = {}
    for key, pattern in FWINFO_PATTERNS.items():
        match = pattern.search(text)
        if match:
            info[key] = match.group(1)
    return info


def parse_wifiprt_mac(text: str) -> Optional[str]:
    """Extract the first MAC address from wifiprt output, if any."""
    match = MAC_RE.search(text)
    return match.group(1) if match else None


def parse_settings(text: str) -> dict:
    """Parse prtsettings output into a key/value dict.

    Lines look like ``st: hold=15`` on some firmwares and ``hold=15`` on
    others; both are accepted.
    """
    return dict(SETTING_LINE_RE.findall(text))


# First firmware known to stop returning /cli output (Fellow's automatic
# update of October 2026); 1.2.26 behaves the same.
CLI_MUTED_SINCE = (1, 2, 24)

# Version page fields. Values are matched within their own line so an empty
# field (e.g. "Last invalid partition:") can't swallow the next line.
_ROOT_CURRENT_RE = re.compile(r"Current version:[ \t]*([^\s<]+)")
_ROOT_RUNNING_RE = re.compile(r"Running partition:[ \t]*(\w+)")
_ROOT_BOOT_RE = re.compile(r"Boot partition:[ \t]*(\w+)")
_ROOT_SLOT_RE = re.compile(
    r"partition[ \t]+'(\w+)'[^\n]*?\bstate[ \t]+(\S+)[ \t]+fw version[ \t]+([^\s<]+)"
)


def version_key(version: Optional[str]) -> tuple:
    """Comparable key for firmware versions like ``1.1.76SSP`` or ``1.2.26``."""
    return tuple(int(part) for part in re.findall(r"\d+", version or ""))


@dataclass
class FirmwareSlot:
    """One firmware partition as listed on the kettle's version page."""

    name: str
    state: str
    version: str


@dataclass
class FirmwareStatus:
    """The kettle's version page: running firmware and each slot's contents."""

    current_version: str
    running: str
    boot: Optional[str] = None
    slots: dict = field(default_factory=dict)

    @property
    def cli_muted(self) -> bool:
        """Whether the running firmware is one that silences /cli output."""
        return version_key(self.current_version) >= CLI_MUTED_SINCE

    def rollback_slot(self) -> Optional[FirmwareSlot]:
        """The other OTA slot, if it holds older firmware the kettle can boot.

        Only firmware from before CLI_MUTED_SINCE counts — switching to
        another muted version wouldn't help. A slot listed as ``undef`` is
        still bootable (intact images show that after switching back and
        forth); ``invalid`` and ``aborted`` are not.
        """
        for slot in self.slots.values():
            key = version_key(slot.version)
            if (
                slot.name.startswith("ota_")
                and slot.name != self.running
                and slot.state not in ("invalid", "aborted")
                and key
                and key < CLI_MUTED_SINCE
            ):
                return slot
        return None


def parse_root_page(text: str) -> Optional[FirmwareStatus]:
    """Parse the kettle's version page (``GET /``); None if it isn't one.

    Unlike /cli, this page still answers on firmware that mutes CLI output.
    """
    page = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    current = _ROOT_CURRENT_RE.search(page)
    running = _ROOT_RUNNING_RE.search(page)
    if not current or not running:
        return None
    boot = _ROOT_BOOT_RE.search(page)
    slots = {
        match.group(1): FirmwareSlot(match.group(1), match.group(2), match.group(3))
        for match in _ROOT_SLOT_RE.finditer(page)
    }
    return FirmwareStatus(
        current_version=current.group(1),
        running=running.group(1),
        boot=boot.group(1) if boot else None,
        slots=slots,
    )
