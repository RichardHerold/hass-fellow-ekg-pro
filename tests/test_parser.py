"""Unit tests for custom_components.fellow.parser.

These run against synthetic fixtures covering the response shapes seen on the
Stagg EKG+ (unit-suffixed Celsius) and the Stagg EKG Pro (bare values,
internally Fahrenheit), plus degraded/truncated responses. No Home Assistant
installation is required: run with plain `pytest tests/`.
"""
# pylint: disable=missing-class-docstring, protected-access


import importlib.util
import sys
from pathlib import Path

import pytest

# Load parser.py directly by path: importing the custom_components.fellow
# package would pull in Home Assistant, which these tests don't need.
_PARSER_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "fellow"
    / "parser.py"
)
_spec = importlib.util.spec_from_file_location("fellow_parser", _PARSER_PATH)
parser = importlib.util.module_from_spec(_spec)
sys.modules["fellow_parser"] = parser
_spec.loader.exec_module(parser)

KettleResponseError = parser.KettleResponseError
parse_fwinfo = parser.parse_fwinfo
parse_settings = parser.parse_settings
parse_state = parser.parse_state
parse_wifiprt_mac = parser.parse_wifiprt_mac
state_problems = parser.state_problems


@pytest.fixture(autouse=True)
def _reset_inference_warning():
    parser._warned_magnitude_inference = False


# EKG+ shape: unit-suffixed Celsius values (matches the original firmware
# 1.1.76SSP output the upstream repo was written against).
EKG_PLUS_HEATING = """\
mode=S_Heat
scrname=heat_screen
tempr=85.0 C
temprT=95.0 C
units=1
clock=12:34
ble conn=1
ketl= ho 1 wd 0 nw 0 ipb 0 bf 0 tr 0
"""

# EKG Pro shape: no unit suffix, values in Fahrenheit, units=0 (F display).
EKG_PRO_HEATING_F = """\
mode=S_Heat
tempr=185.0
temprT=203.0
temprB=212.0
units=0
clock=22:56
ble conn=0
ketl= ho 1 wd 0 nw 0 ipb 0 bf 0 tr 0
"""

# Pro-style output with explicit F suffixes.
SUFFIX_F = """\
mode=S_Off
tempr=104.0 F
temprT=212.0 F
units=1
"""

# No suffix and no units field at all — magnitude inference territory.
NO_UNITS_FIELD_F = """\
mode=S_Off
tempr=185.0
temprT=203.0
"""

NO_UNITS_FIELD_C = """\
mode=S_Off
tempr=21.5
temprT=95.0
"""

OFF_IDLE = """\
mode=S_Off
tempr=21.19 C
temprT=95.0 C
units=1
clock=08:15
ble conn=0
ketl= ho 0 wd 0 nw 0 ipb 0 bf 0 tr 0
"""

# Lifted off the base: firmware emits a sentinel temperature.
LIFTED_SENTINEL = """\
mode=S_Heat
tempr=32767
temprT=95.0 C
units=1
ketl= ho 1 wd 0 nw 0 ipb 0 bf 0 tr 0
"""

TRUNCATED_NO_MODE = "tempr=85.0 C\ntemprT=95.0 C\n"

TRUNCATED_NO_TEMP = "mode=S_Heat\nunits=1\n"

HOLD_MODE = """\
mode=S_Hold
tempr=95.0 C
temprT=95.0 C
units=1
ketl= ho 0 wd 1 nw 0 ipb 0 bf 0 tr 0
"""

MENU_MODE = "mode=S_Heat+menu\ntempr=90.0 C\ntemprT=95.0 C\nunits=1\n"


class TestParseStateShapes:
    def test_ekg_plus_shape(self):
        state = parse_state(EKG_PLUS_HEATING)
        assert state.mode == "S_Heat"
        assert state.current_temp_c == 85.0
        assert state.target_temp_c == 95.0
        assert state.units == 1
        assert state.clock == "12:34"
        assert state.ble_connected is True
        assert state.screen_name == "heat_screen"
        assert state.is_heating
        assert state.is_docked
        assert state.temp_field_present
        assert state.flags == {"ho": 1, "wd": 0, "nw": 0, "ipb": 0, "bf": 0, "tr": 0}
        assert state.raw == EKG_PLUS_HEATING

    def test_ekg_pro_shape_bare_fahrenheit(self):
        state = parse_state(EKG_PRO_HEATING_F)
        assert state.mode == "S_Heat"
        # 185F = 85C, 203F = 95C, 212F = 100C
        assert state.current_temp_c == pytest.approx(85.0, abs=0.01)
        assert state.target_temp_c == pytest.approx(95.0, abs=0.01)
        assert state.boil_temp_c == pytest.approx(100.0, abs=0.01)
        assert state.units == 0
        assert state.is_heating
        assert state.is_docked

    def test_explicit_f_suffix_beats_units_field(self):
        # units=1 says Celsius display, but the explicit F suffix wins.
        state = parse_state(SUFFIX_F)
        assert state.current_temp_c == pytest.approx(40.0, abs=0.01)
        assert state.target_temp_c == pytest.approx(100.0, abs=0.01)

    def test_magnitude_inference_fahrenheit(self):
        state = parse_state(NO_UNITS_FIELD_F)
        assert state.current_temp_c == pytest.approx(85.0, abs=0.01)
        assert state.target_temp_c == pytest.approx(95.0, abs=0.01)

    def test_magnitude_inference_celsius(self):
        state = parse_state(NO_UNITS_FIELD_C)
        assert state.current_temp_c == pytest.approx(21.5, abs=0.01)
        assert state.target_temp_c == pytest.approx(95.0, abs=0.01)

    def test_off_idle(self):
        state = parse_state(OFF_IDLE)
        assert state.is_off
        assert not state.is_heating
        assert not state.is_holding
        assert not state.is_powered_on
        assert state.current_temp_c == pytest.approx(21.19)

    def test_hold_mode(self):
        state = parse_state(HOLD_MODE)
        assert state.is_holding
        assert not state.is_heating
        assert state.warming  # wd flag set

    def test_menu_overlay_still_heating(self):
        state = parse_state(MENU_MODE)
        assert state.mode == "S_Heat+menu"
        assert state.is_heating
        assert state.is_in_menu


class TestDegradedResponses:
    def test_missing_mode_raises(self):
        with pytest.raises(KettleResponseError):
            parse_state(TRUNCATED_NO_MODE)

    def test_missing_temp_is_not_a_lift(self):
        state = parse_state(TRUNCATED_NO_TEMP)
        assert state.current_temp_c is None
        assert not state.temp_field_present
        # A response without the field must not read as "off the base".
        assert not state.is_docked

    def test_sentinel_temp_reads_as_lifted(self):
        state = parse_state(LIFTED_SENTINEL)
        assert state.current_temp_c is None
        assert state.temp_field_present
        assert not state.is_docked
        # Target stays usable even while the current temp is a sentinel.
        assert state.target_temp_c == 95.0

    def test_missing_target_is_none_not_zero(self):
        state = parse_state("mode=S_Off\ntempr=21.0 C\nunits=1\n")
        assert state.target_temp_c is None


class TestRegexIsolation:
    def test_target_not_swallowed_by_current(self):
        # temprT first in the response must not be consumed by the tempr
        # pattern (and vice versa).
        state = parse_state("mode=S_Off\ntemprT=95.0 C\ntempr=21.0 C\nunits=1\n")
        assert state.current_temp_c == 21.0
        assert state.target_temp_c == 95.0

    def test_suffix_not_stolen_from_following_word(self):
        # "Foo" after the value must not be read as a Fahrenheit suffix.
        state = parse_state("mode=S_Off\ntempr=185.0 Foo\nunits=0\n")
        assert state.current_temp_c == pytest.approx(85.0, abs=0.01)

    def test_flags_only_from_ketl_line(self):
        # "ho 99" outside the ketl= line must not be picked up as a flag.
        text = "mode=S_Off\necho 99\ntempr=21.0 C\nketl= ho 0 wd 1\n"
        state = parse_state(text)
        assert state.flags == {"ho": 0, "wd": 1}
        assert state.warming


class TestStateProblems:
    """state_problems() backs the config flow's strict setup validation:
    a response that connects but can't be understood must not produce a
    false-positive setup success."""

    def test_fully_parsed_state_has_no_problems(self):
        assert state_problems(parse_state(EKG_PLUS_HEATING)) == []
        assert state_problems(parse_state(EKG_PRO_HEATING_F)) == []

    def test_missing_temp_field_is_a_problem(self):
        problems = state_problems(parse_state(TRUNCATED_NO_TEMP))
        assert any("tempr" in p for p in problems)

    def test_sentinel_temp_is_a_problem(self):
        problems = state_problems(parse_state(LIFTED_SENTINEL))
        assert any("base" in p for p in problems)

    def test_missing_target_is_a_problem(self):
        problems = state_problems(
            parse_state("mode=S_Off\ntempr=21.0 C\nunits=1\n")
        )
        assert any("temprT" in p for p in problems)


class TestHelperParsers:
    def test_mac_colon_separated(self):
        assert parse_wifiprt_mac("sta mac: A4:CF:12:34:56:78\nip: 10.0.0.5") == (
            "A4:CF:12:34:56:78"
        )

    def test_mac_dash_separated(self):
        assert parse_wifiprt_mac("mac A4-CF-12-34-56-78") == "A4-CF-12-34-56-78"

    def test_mac_absent(self):
        assert parse_wifiprt_mac("no mac here") is None

    def test_fwinfo_version(self):
        text = (
            "running partition: ota_0\n"
            "app version: 1.1.76SSP CLI\n"
            "compile time: May  9 2024 10:00:00\n"
            "idf version: v4.4.4\n"
        )
        info = parse_fwinfo(text)
        assert info["version"] == "1.1.76SSP CLI"
        assert info["idf"] == "v4.4.4"

    def test_fwinfo_empty(self):
        assert parse_fwinfo("garbage") == {}

    def test_settings_with_and_without_prefix(self):
        text = "st: hold=15\nguide=1\nst: chime=5\n"
        settings = parse_settings(text)
        assert settings["hold"] == "15"
        assert settings["guide"] == "1"
        assert settings["chime"] == "5"
