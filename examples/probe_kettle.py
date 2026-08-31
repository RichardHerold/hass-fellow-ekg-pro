#!/usr/bin/env python3
"""Capture ground-truth output from a Fellow Stagg EKG+ / EKG Pro kettle.

Run this from any machine on the same network as the kettle:

    python3 examples/probe_kettle.py <KETTLE_IP>

It sends only READ-ONLY commands (state, prtsettings, fwinfo, wifiprt),
prints each raw response verbatim between BEGIN/END markers, and then shows
how the Home Assistant integration's parser interprets the state response —
with a PASS/FAIL line per field. Paste the whole output into a GitHub issue
(or back to whoever is debugging the integration with you): it pins down
your firmware's exact response format.

Optional write test (changes your kettle's target temperature):

    python3 examples/probe_kettle.py <KETTLE_IP> --set-temp 200

Requires only the Python standard library. The parser check needs the repo
checkout next to this script; without it, raw output is still printed.

NOTE: wifiprt output can include your WiFi SSID and MAC — review before
posting publicly.
"""

import argparse
import importlib.util
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

READ_ONLY_COMMANDS = ("state", "prtsettings", "fwinfo", "wifiprt")

# Never send these: a bare "ss" reboots the kettle, "adcsamples" crashes
# the firmware, "reset" reboots the device.
FORBIDDEN_COMMANDS = ("ss", "adcsamples", "reset")


def send_command(host: str, cmd: str, timeout: float = 10.0) -> str:
    if cmd.strip() in FORBIDDEN_COMMANDS:
        raise SystemExit(f"Refusing to send {cmd!r}: it reboots or crashes the kettle")
    url = f"http://{host}/cli?{urllib.parse.urlencode({'cmd': cmd})}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def load_parser():
    """Load the integration's parser module directly by path, if present."""
    parser_path = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "fellow"
        / "parser.py"
    )
    if not parser_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("fellow_parser", parser_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fellow_parser"] = module
    spec.loader.exec_module(module)
    return module


def check(label: str, ok: bool, detail: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")


def main() -> None:
    argp = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argp.add_argument("host", help="Kettle IP address")
    argp.add_argument(
        "--set-temp",
        type=float,
        metavar="F",
        help="OPTIONAL WRITE TEST: send 'setsettingd settempr <F>' "
        "(Fahrenheit) and read back. This CHANGES your kettle's target.",
    )
    args = argp.parse_args()

    raw = {}
    for cmd in READ_ONLY_COMMANDS:
        print(f"--- BEGIN {cmd} ---")
        try:
            raw[cmd] = send_command(args.host, cmd)
            print(raw[cmd])
        except Exception as err:
            raw[cmd] = None
            print(f"<request failed: {err}>")
        print(f"--- END {cmd} ---\n")

    fellow_parser = load_parser()
    if fellow_parser is None:
        print("parser.py not found next to this script — raw output only.")
    elif raw.get("state"):
        print("=== Parser interpretation of 'state' ===")
        try:
            state = fellow_parser.parse_state(raw["state"])
        except Exception as err:
            check("mode", False, f"parse_state raised: {err}")
        else:
            check("mode", bool(state.mode), f"{state.mode!r}")
            check(
                "current temperature",
                state.current_temp_c is not None,
                f"{state.current_temp_c} °C (field present: {state.temp_field_present})",
            )
            check(
                "target temperature",
                state.target_temp_c is not None,
                f"{state.target_temp_c} °C",
            )
            check("units field", state.units is not None, f"units={state.units}")
            check("status flags", bool(state.flags), f"{state.flags}")
            print(
                f"  derived: is_heating={state.is_heating} is_off={state.is_off} "
                f"is_holding={state.is_holding} is_docked={state.is_docked}"
            )
        if raw.get("fwinfo"):
            print(f"  fwinfo parsed: {fellow_parser.parse_fwinfo(raw['fwinfo'])}")
        if raw.get("wifiprt"):
            print(f"  MAC parsed: {fellow_parser.parse_wifiprt_mac(raw['wifiprt'])}")

    if args.set_temp is not None:
        print(f"\n=== Write test: setsettingd settempr {args.set_temp:.1f} ===")
        print(send_command(args.host, f"setsettingd settempr {args.set_temp:.1f}"))
        time.sleep(0.5)
        print("--- state after write ---")
        after = send_command(args.host, "state")
        print(after)
        if fellow_parser is not None:
            state = fellow_parser.parse_state(after)
            target_f = (
                state.target_temp_c * 9 / 5 + 32
                if state.target_temp_c is not None
                else None
            )
            check(
                "target changed to request",
                target_f is not None and abs(target_f - args.set_temp) <= 1.0,
                f"target now {target_f} °F (requested {args.set_temp} °F)",
            )


if __name__ == "__main__":
    main()
