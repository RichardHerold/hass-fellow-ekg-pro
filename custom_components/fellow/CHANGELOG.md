# Changelog

All notable changes to this project will be documented in this file.

## Origins

This project began as a fork of
[rderewianko/fellow-ekg](https://github.com/rderewianko/fellow-ekg), an
AI-generated Home Assistant integration developed against a Stagg EKG+ on
firmware 1.1.76SSP. It was substantially rewritten for the Stagg EKG Pro —
new response parser, new command layer, new config flow, reworked entities,
tests, and diagnostics — with the EKG Pro command set cross-checked against
the independent
[stagg-ekg-pro](https://github.com/montymhughes/stagg-ekg-pro)
reverse-engineering project. Thanks to both. The pre-rework history is
preserved in this repository's git log.

## [1.1.0] - 2026-08-31

### Changed
- **The network scan now asks which network to scan.** Previously it
  guessed Home Assistant's own /24 (via a UDP-socket trick that picks the
  wrong interface on container installs) and could never find a kettle on
  a different subnet or IoT VLAN. The scan form is prefilled with Home
  Assistant's real detected subnets (via the HA network helper) and
  accepts any network up to /22 — enter the kettle's subnet (e.g.
  `192.168.20.0/24`, or just an IP on it) to scan across VLANs, provided
  the firewall allows HTTP from Home Assistant to that network.
- A scan that finds nothing now says so explicitly instead of silently
  dropping to manual entry.
- Probe timeout raised from 1.5s to 3s — the kettle's HTTP server can
  stall for seconds, causing missed detections.
- Scan hits are validated with the integration's own response parser
  (including a temperature field), so only kettles that setup validation
  would accept are offered.

## [1.0.0] - 2026-08-31

First release.

### Kettle support
- Works with the Stagg EKG Pro as well as the Stagg EKG+: response parsing
  tolerates both firmware output shapes (unit-suffixed Celsius on the EKG+,
  bare Fahrenheit-based values on the Pro), resolving units from an explicit
  C/F suffix, the `units=` field, or magnitude.
- Temperature setting uses the Pro-verified `setsettingd settempr` command
  (sets the *active* target), falling back to the legacy EKG+
  `setsetting settempr` and finally to dial emulation — each step verified
  by read-back.
- Keep-warm uses Hold mode (`ss S_Hold`); heating control uses the
  firmware state machine (`ss S_Heat` / `ss S_Off`).

### Setup that can't lie
- Setup succeeds only when the kettle both answers **and** is understood:
  validation requires usable current and target temperatures. A kettle that
  replies in an unrecognized format stops setup with a dedicated
  "incomplete response" error and logs the raw response at warning level.
- Successful setup logs a confirmation line
  (`Fellow kettle at <ip> is up: mode=… current=… target=… firmware=… mac=…`).
- Config entries have a stable unique ID (kettle MAC via `wifiprt`, host as
  fallback): no duplicate entries, and an IP change updates the existing
  entry.
- Manual IP entry is the first-class setup path; the /24 network scan runs
  only when explicitly chosen.
- Setup never modifies the kettle; syncing the display unit is an opt-in
  option.

### Entities
- Water heater (target temperature, off/heat/warm), current/target
  temperature sensors, mode sensor, heating and warming switches, power
  binary sensor.
- Device info (model, firmware version, MAC) is read from the kettle.
- Disabled-by-default extras: Boil Threshold sensor (`temprB`), Low Water
  Warning (the firmware's `nw` flag, with all status flags exposed for
  verification), Lifted (inferred), and an advanced "Heater Element
  (Direct)" switch exposing raw `heaton`/`heatoff` GPIO control.
- Polling every 10 seconds by default, configurable 5–60 in options.

### Safety
- The client refuses to send commands known to reboot or crash the kettle:
  bare `ss`, `adcsamples`, `reset`.

### Diagnostics
- Every poll logs the raw firmware response at debug level.
- Diagnostics platform: one-click download of the last parsed state plus
  raw `state`/`prtsettings`/`fwinfo`/`wifiprt` responses.
- `examples/probe_kettle.py`: stdlib-only, read-only capture tool with
  per-field parser PASS/FAIL, for pinning down firmware format differences.

### Development
- Parser and command-guard unit tests run with plain `pytest tests/` — no
  Home Assistant installation required.
