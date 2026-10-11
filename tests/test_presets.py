"""Tests for preset parsing, lifecycle state, water-ready, model names."""
# pylint: disable=missing-class-docstring


import importlib
import sys
import types
from pathlib import Path

import pytest

_PKG_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "fellow"
)
_pkg = types.ModuleType("fellow_pkg")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules.setdefault("fellow_pkg", _pkg)
presets = importlib.import_module("fellow_pkg.presets")
parser = importlib.import_module("fellow_pkg.parser")

parse_preset_list = presets.parse_preset_list
prettify_model_name = parser.prettify_model_name
is_water_ready = parser.is_water_ready
kettle_display_state = parser.kettle_display_state
parse_state = parser.parse_state


class TestParsePresetList:
    def test_celsius_pairs(self):
        assert parse_preset_list("Pour-over: 96, Green tea: 79", fahrenheit=False) == [
            ("Pour-over", 96.0),
            ("Green tea", 79.0),
        ]

    def test_fahrenheit_converted_to_celsius(self):
        result = parse_preset_list("Pour-over: 205", fahrenheit=True)
        assert result[0][0] == "Pour-over"
        assert result[0][1] == pytest.approx(96.1, abs=0.1)

    def test_newline_and_semicolon_separators(self):
        assert parse_preset_list("A: 90\nB: 80; C: 70", fahrenheit=False) == [
            ("A", 90.0),
            ("B", 80.0),
            ("C", 70.0),
        ]

    def test_empty_and_blank(self):
        assert parse_preset_list("", fahrenheit=False) == []
        assert parse_preset_list("  ,  \n ", fahrenheit=False) == []

    @pytest.mark.parametrize(
        "text",
        [
            "just a name",  # no temperature
            "Tea: hot",  # non-numeric
            "Tea: 30",  # below 40C
            "Tea: 101",  # above 100C
            "Tea: 90, tea: 80",  # duplicate name (case-insensitive)
        ],
    )
    def test_rejected(self, text):
        with pytest.raises(ValueError):
            parse_preset_list(text, fahrenheit=False)

    def test_fahrenheit_range_check(self):
        # 100F = 37.8C — below the kettle's minimum.
        with pytest.raises(ValueError):
            parse_preset_list("Warm: 100", fahrenheit=True)


class TestIsWaterReady:
    def test_ready_while_heating_at_target(self):
        state = parse_state("mode=S_Heat\ntempr=94.5 C\ntemprT=95.0 C\nunits=1\n")
        assert is_water_ready(state)

    def test_ready_while_holding(self):
        state = parse_state("mode=S_Hold\ntempr=95.0 C\ntemprT=95.0 C\nunits=1\n")
        assert is_water_ready(state)

    def test_not_ready_mid_heat(self):
        state = parse_state("mode=S_Heat\ntempr=60.0 C\ntemprT=95.0 C\nunits=1\n")
        assert not is_water_ready(state)

    def test_off_kettle_with_hot_water_is_not_ready(self):
        state = parse_state("mode=S_Off\ntempr=95.0 C\ntemprT=95.0 C\nunits=1\n")
        assert not is_water_ready(state)

    def test_unknown_temps_are_not_ready(self):
        state = parse_state("mode=S_Heat\nunits=1\n")
        assert not is_water_ready(state)


class TestPrettifyModelName:
    def test_underscores_and_ekg_uppercased(self):
        assert prettify_model_name("stagg_ekg_pro") == "Stagg EKG Pro"

    def test_dashes_and_mixed_case(self):
        assert prettify_model_name("STAGG-EKG") == "Stagg EKG"

    def test_spaces_kept(self):
        assert prettify_model_name("corvo kettle") == "Corvo Kettle"

    def test_blank_and_none(self):
        assert prettify_model_name(None) is None
        assert prettify_model_name("") is None
        assert prettify_model_name("  _- ") is None

    def test_overlong_trimmed(self):
        result = prettify_model_name("x" * 100)
        assert result is not None and len(result) <= 40


class TestKettleDisplayState:
    """The Ember-style lifecycle value shown by the Kettle State sensor."""

    def test_heating_below_target(self):
        state = parse_state("mode=S_Heat\ntempr=60.0 C\ntemprT=95.0 C\nunits=1\n")
        assert kettle_display_state(state) == "heating"

    def test_heating_at_target_is_at_temperature(self):
        state = parse_state("mode=S_Heat\ntempr=94.5 C\ntemprT=95.0 C\nunits=1\n")
        assert kettle_display_state(state) == "at_temperature"

    def test_hold_at_target_is_at_temperature(self):
        state = parse_state("mode=S_Hold\ntempr=95.0 C\ntemprT=95.0 C\nunits=1\n")
        assert kettle_display_state(state) == "at_temperature"

    def test_hold_below_target_is_keeping_warm(self):
        state = parse_state("mode=S_Hold\ntempr=88.0 C\ntemprT=95.0 C\nunits=1\n")
        assert kettle_display_state(state) == "keeping_warm"

    def test_off(self):
        state = parse_state("mode=S_Off\ntempr=95.0 C\ntemprT=95.0 C\nunits=1\n")
        assert kettle_display_state(state) == "off"

    def test_unknown_mode_reads_off(self):
        state = parse_state("mode=S_Standby\ntempr=21.0 C\ntemprT=95.0 C\nunits=1\n")
        assert kettle_display_state(state) == "off"

    def test_missing_temps_while_heating_stays_heating(self):
        state = parse_state("mode=S_Heat\nunits=1\n")
        assert kettle_display_state(state) == "heating"

    def test_all_values_in_options(self):
        assert set(parser.KETTLE_STATE_OPTIONS) == {
            "off", "heating", "at_temperature", "keeping_warm",
        }
