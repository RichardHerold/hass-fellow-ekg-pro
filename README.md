# Fellow EKG Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License: Unlicense](https://img.shields.io/badge/License-Unlicense-blue.svg)](http://unlicense.org/)

A Home Assistant custom integration for Fellow Stagg EKG WiFi kettles (Stagg EKG+ and Stagg EKG Pro) with temperature control, automation support, and real-time monitoring — entirely over the local network, no cloud.

It talks to the kettle's built-in HTTP CLI interface (`http://<kettle-ip>/cli`). The command set and response parsing cover both the Stagg EKG+ (firmware 1.1.76SSP) and the Stagg EKG Pro, whose firmware formats responses differently and uses a different set-temperature command (`setsettingd settempr`, as documented by the [stagg-ekg-pro](https://github.com/montymhughes/stagg-ekg-pro) reverse-engineering effort). Response parsing is tolerant of both formats, and every state read is logged at debug level so format differences on other firmwares are easy to capture and fix.

## Features

- Turn the kettle on/off and start keep-warm (Hold) from Home Assistant
- Set the target temperature (40–100°C / 104–212°F) with read-back verification, falling back to dial emulation on firmwares without a working set-target command
- Monitor current water temperature, target, mode, and heating status
- Real device info (firmware version, MAC) read from the kettle
- Built-in diagnostics: download a bundle with the raw firmware responses from Settings → Devices & Services
- Local polling (default every 10 seconds, configurable 5–60)

## Entities

| Entity | Type | Purpose |
|--------|------|---------|
| Kettle | Water Heater | Main control: target temperature, off/heat/warm |
| Current Temperature | Sensor | Real-time water temperature |
| Target Temperature | Sensor | Target temperature setting |
| Mode | Sensor | Operating mode (Off, Heat, Hold, …) |
| Heating | Switch | Start/stop a heating cycle |
| Warming | Switch | Keep-warm (Hold mode) |
| Power | Binary Sensor | Power on/off status |
| Boil Threshold | Sensor (diagnostic, disabled by default) | Altitude-adjusted boil point reported by the kettle |
| Low Water Warning | Binary Sensor (diagnostic, disabled by default) | The firmware's `nw` status flag — meaning not yet verified on all models |
| Lifted | Binary Sensor (disabled by default) | Inferred from the temperature reading disappearing |
| Heater Element (Direct) | Switch (disabled by default) | **Advanced:** raw `heaton`/`heatoff` GPIO control, bypassing the firmware state machine |

The disabled-by-default entities can be enabled per-entity in Settings → Devices & Services → Fellow → entities.

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed
2. Add this repository as a custom repository:
   - Go to HACS → Integrations
   - Click the three dots in the top right
   - Select "Custom repositories"
   - Add this repository's URL, category: Integration
3. Install the integration and restart Home Assistant
4. Add it via Settings → Devices & Services → Add Integration → "Fellow"

### Manual Installation

1. Copy `custom_components/fellow` into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via Settings → Devices & Services

## Configuration

### Finding Your Kettle's IP Address

The kettle joins your WiFi via the Fellow app. Find its IP in your router's DHCP client list — look for "Stagg", "Fellow", or "espressif" (the ESP32 manufacturer). Give it a DHCP reservation so the address doesn't change.

### Setup

1. Settings → Devices & Services → Add Integration → "Fellow"
2. Choose **Enter IP address** (recommended) and type the kettle's IP, or **Scan network** to probe the local /24 for kettles
3. Pick your preferred temperature unit for Home Assistant

Setup does **not** change anything on the kettle itself.

### Options (Settings → Devices & Services → Fellow → Configure)

- **Temperature unit** — the unit Home Assistant uses
- **Temperature-setting method** — *Direct* (firmware set-target commands with verification; recommended) or *Dial emulation* (slower; for firmwares where the set commands don't work)
- **Poll interval** — 5–60 seconds, default 10
- **Sync unit to the kettle's display** — off by default; when on, changing the unit here also switches the kettle's own display

## Usage

```yaml
# Heat water to 95°C
service: water_heater.set_temperature
target:
  entity_id: water_heater.fellow_kettle
data:
  temperature: 95
```

**Morning Coffee**
```yaml
automation:
  - alias: "Morning Coffee"
    trigger:
      platform: time
      at: "07:00:00"
    action:
      - service: water_heater.set_temperature
        target:
          entity_id: water_heater.fellow_kettle
        data:
          temperature: 95
      - service: water_heater.turn_on
        target:
          entity_id: water_heater.fellow_kettle
```

**Dashboard Card**
```yaml
type: thermostat
entity: water_heater.fellow_kettle
name: Coffee Kettle
```

## Troubleshooting

### First step: capture what your kettle actually says

Different firmwares format the CLI responses differently. From any machine on the kettle's network:

```bash
python3 examples/probe_kettle.py <KETTLE_IP>
```

This sends only read-only commands, prints the raw responses, and shows how the integration's parser interprets them (PASS/FAIL per field). Paste the output into a GitHub issue if something fails. Equivalent raw captures:

```bash
curl 'http://<KETTLE_IP>/cli?cmd=state'
curl 'http://<KETTLE_IP>/cli?cmd=prtsettings'
curl 'http://<KETTLE_IP>/cli?cmd=fwinfo'
```

> **Never** send `cmd=ss` with no argument (reboots the kettle) or `cmd=adcsamples` (crashes it).

### Debug logging

```yaml
logger:
  logs:
    custom_components.fellow: debug
```

Every poll then logs the raw `state` response (`Raw state response from …`).

### Diagnostics download

Settings → Devices & Services → Fellow → device page → **Download diagnostics** produces a bundle with the last parsed state and the raw firmware responses. Review it before sharing — it can include network details.

### Kettle Not Responding

1. Verify the kettle is powered and on WiFi (check the Fellow app)
2. Check the IP address hasn't changed
3. Ensure Home Assistant can reach the kettle's network (VLANs/subnet isolation block it; the network scan only covers Home Assistant's own /24)
4. Try `curl 'http://<KETTLE_IP>/cli?cmd=state'` from another machine

### Setting temperature doesn't stick

The integration tries `setsettingd settempr` (EKG Pro), then the legacy `setsetting settempr` (EKG+), then dial emulation, verifying each by read-back. If it always ends up dialing, switch the *Temperature-setting method* option to *Dial emulation* to skip the probes. Check debug logs to see which path was used.

## Standalone Python API

[`examples/stagg_ekg_api.py`](examples/stagg_ekg_api.py) is a standalone client for use outside Home Assistant, and [`examples/probe_kettle.py`](examples/probe_kettle.py) is the read-only diagnostic capture tool. See [examples/README.md](examples/README.md).

## Technical Details

- **Protocol:** HTTP GET to `/cli?cmd=<command>` on port 80, plain-text responses (an undocumented firmware debug interface — it can change with firmware updates)
- **Platform:** ESP32 (Espressif)
- **Range:** 40–100°C (104–212°F)
- **Polling:** every 10 seconds by default (5–60 configurable)

See [KETTLE_SPECS.md](KETTLE_SPECS.md) for the command reference, including the EKG Pro differences and the list of commands that must never be sent.

## Contributing

Contributions are welcome! Run the parser tests with `pip install pytest && pytest tests/` — no Home Assistant installation needed. If your kettle's responses parse incorrectly, include `probe_kettle.py` output in your issue.

## License

This is free and unencumbered software released into the public domain. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built for [Fellow](https://fellowproducts.com/) Stagg EKG WiFi kettles
- EKG Pro command set cross-checked against the [stagg-ekg-pro](https://github.com/montymhughes/stagg-ekg-pro) reverse-engineering project
- **Created with AI assistance** — originally developed with Claude Code and reworked for the EKG Pro

## Disclaimer

This is an unofficial integration not affiliated with Fellow Products. It drives an undocumented debug interface; use at your own risk.
