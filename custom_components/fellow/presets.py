"""Parsing for user-configured temperature presets.

Pure Python (no Home Assistant imports) so it's unit-testable standalone.
Presets are configured in the options flow as a comma- or newline-separated
list of ``Name: temperature`` pairs, with temperatures in the unit the user
configured for the integration, e.g.::

    Pour-over: 96, Green tea: 79
"""
from __future__ import annotations

import re

# Preset temperatures must stay inside the kettle's settable range.
MIN_PRESET_C = 40.0
MAX_PRESET_C = 100.0

_PAIR_RE = re.compile(r"^\s*(?P<name>[^:]+?)\s*:\s*(?P<temp>\d+(?:\.\d+)?)\s*$")


def parse_preset_list(text: str, fahrenheit: bool) -> list[tuple[str, float]]:
    """Parse the presets option into (name, celsius) tuples.

    ``fahrenheit`` says which unit the configured numbers are in. Raises
    ValueError on a malformed pair, a duplicate name, or an out-of-range
    temperature, naming the offending entry.
    """
    presets: list[tuple[str, float]] = []
    seen: set[str] = set()
    for chunk in re.split(r"[,\n;]", text or ""):
        if not chunk.strip():
            continue
        match = _PAIR_RE.match(chunk)
        if not match:
            raise ValueError(f"not a 'Name: temperature' pair: {chunk.strip()!r}")
        name = match.group("name")
        value = float(match.group("temp"))
        temp_c = (value - 32.0) * 5.0 / 9.0 if fahrenheit else value
        if not MIN_PRESET_C <= temp_c <= MAX_PRESET_C:
            raise ValueError(
                f"preset {name!r} is outside the kettle's 40-100°C "
                f"(104-212°F) range"
            )
        key = name.casefold()
        if key in seen:
            raise ValueError(f"duplicate preset name: {name!r}")
        seen.add(key)
        presets.append((name, round(temp_c, 1)))
    return presets
