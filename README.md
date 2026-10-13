# Fellow EKG Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![License: Unlicense](https://img.shields.io/badge/License-Unlicense-blue.svg)](http://unlicense.org/)

A Home Assistant custom integration for Fellow Stagg EKG WiFi kettles (Stagg EKG+ and Stagg EKG Pro) with temperature control, automation support, and real-time monitoring — entirely over the local network, no cloud.

It talks to the kettle's built-in HTTP CLI interface (`http://<kettle-ip>/cli`). The command set and response parsing cover both the Stagg EKG+ (firmware 1.1.76SSP) and the Stagg EKG Pro, whose firmware formats responses differently and uses a different set-temperature command (`setsettingd settempr`, as documented by the [stagg-ekg-pro](https://github.com/montymhughes/stagg-ekg-pro) reverse-engineering effort). Response parsing is tolerant of both formats, and every state read is logged at debug level so format differences on other firmwares are easy to capture and fix.

> **Firmware 1.2.24 and later break local control.** In October 2026 Fellow began updating kettles automatically to firmware 1.2.24 and 1.2.26, which stop returning output from the command interface this integration uses. Most kettles still hold their previous firmware and can be switched back: see [Kettle firmware update stopped local control](#kettle-firmware-update-stopped-local-control). The integration detects this and raises a Repairs card with the steps for your kettle.

## Features

- Turn the kettle on/off and start keep-warm (Hold) from Home Assistant
- Set the target temperature (40–100°C / 104–212°F) with read-back verification, falling back to dial emulation on firmwares without a working set-target command
- Monitor current water temperature, target, mode, and heating status
- Real device info (firmware version, MAC) read from the kettle
- Built-in diagnostics: download a bundle with the raw firmware responses from Settings → Devices & Services
- Adaptive local polling — every 3 seconds while heating/keeping warm, every 10 seconds when idle (both configurable)

## Entities

| Entity | Type | Purpose |
|--------|------|---------|
| Kettle | Water Heater | Main control: target temperature, off/heat/warm; supports the `fellow.heat_to` action |
| Boil / your presets | Buttons | One tap: set target and start heating (presets configurable in options) |
| Kettle State | Sensor (enum) | Lifecycle at a glance: Off / Heating / At temperature / Keeping warm (raw firmware mode as attribute) |
| Time to Ready | Sensor | Estimated minutes until target while heating (from the live heating rate) |
| Hold Duration | Number (config) | How long keep-warm stays on before auto-off (1–120 min) |
| Chime Volume | Number (config) | Kettle chime level, 0 = silent — automatable for quiet hours |
| Sync Clock | Button (config) | Set the kettle's display clock to HA's local time (or enable daily auto-sync in options) |
| Integration Update | Update | "Update available" when a new version is released on GitHub, with release notes (manual installs only — with HACS installed, HACS's own installable update entity takes its place) |
| Current Temperature | Sensor | Real-time water temperature |
| Target Temperature | Sensor | Target temperature setting |
| Mode | Sensor | Operating mode (Off, Heat, Hold, …) |
| Set Target | Number (slider) | Set the target temperature **without** starting heating (the sensor above reports; this controls) |
| Kettle Display Unit | Select (config) | Flip the °C/°F shown on the kettle's own screen |
| Identify | Button (diagnostic, disabled by default) | Beep the buzzer to confirm which kettle this is |
| Heating | Switch | Start/stop a heating cycle (heats to target, then off) |
| Warming | Switch | Keep-warm (Hold mode: heats to target and stays there) |
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
2. Choose **Enter IP address** (recommended) and type the kettle's IP, or **Scan network** — the scan asks which network to look on (prefilled with Home Assistant's own subnet), so a kettle on a different subnet or IoT VLAN can be found by entering its network (e.g. `192.168.20.0/24`). Cross-VLAN scanning requires your firewall to allow HTTP (port 80) from Home Assistant to that subnet.
3. Pick your preferred temperature unit for Home Assistant, and optionally a device name — left blank, the kettle's detected model name is used (it becomes the entity-ID prefix). To rename later, use the pencil icon on the device page; Home Assistant offers to update entity IDs too.

Setup does **not** change anything on the kettle itself.

Setup only succeeds when the kettle both **answers and is understood**: validation requires usable current and target temperatures, not just a reply. If the kettle responds but its format can't be parsed, setup stops with an "incomplete response" error and the raw response is written to the Home Assistant log — no silent false-positive setups. After a successful setup, the log contains a confirmation line: `Fellow kettle at <ip> is up: mode=… current=… target=… firmware=…`.

### Options (Settings → Devices & Services → Fellow → Configure)

- **Temperature unit** — the unit Home Assistant uses for this kettle's entities, presets and actions. The kettle's own screen is set separately, with the **Kettle Display Unit** control on the device page.
- **Temperature-setting method** — *Direct* (firmware set-target commands with verification; recommended) or *Dial emulation* (slower; for firmwares where the set commands don't work)
- **Poll intervals** — idle (default 10s) and active-while-heating (default 3s), both configurable

## Usage

**Heat to a temperature in one action** — `fellow.heat_to` sets the target and starts heating:

```yaml
service: fellow.heat_to
target:
  entity_id: water_heater.fellow_kettle
data:
  temperature: 95
```

**One-tap presets** — a Boil button is built in, and you can add your own in the integration's options (`Pour-over: 96, Green tea: 79`); each becomes a button entity for dashboards and voice.

**Morning Coffee**
```yaml
automation:
  - alias: "Morning Coffee"
    trigger:
      platform: time
      at: "07:00:00"
    action:
      - service: fellow.heat_to
        target:
          entity_id: water_heater.fellow_kettle
        data:
          temperature: 95
```

**Notify when the water is ready** — trigger on the Kettle State sensor reaching `at_temperature`:
```yaml
automation:
  - alias: "Water ready"
    trigger:
      - platform: state
        entity_id: sensor.fellow_kettle_state
        to: "at_temperature"
    action:
      - service: notify.mobile_app
        data:
          title: "☕ Kettle"
          message: "Water is at temperature"
```

**Update notifications** — on manual installs the integration ships an update entity that checks this repo's GitHub releases twice a day; new versions appear in Settings → Updates with release notes. When HACS is installed, this entity isn't created — HACS tracks the repo itself and shows the one update card that can actually install (trigger on HACS's `update.*` entity for this repo instead). For a phone ping on a manual install:
```yaml
automation:
  - alias: "Kettle integration update available"
    trigger:
      - platform: state
        entity_id: update.fellow_kettle_integration_update
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: "New Fellow kettle integration version available"
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

On Windows, type `curl.exe` rather than `curl` in PowerShell (there, `curl` is PowerShell's own web command), or open the addresses in a browser.

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
3. Ensure Home Assistant can reach the kettle's network — if the kettle is on another subnet or IoT VLAN, the firewall must allow HTTP (port 80) from Home Assistant to it; point the network scan at the kettle's subnet, not Home Assistant's
4. Try `curl 'http://<KETTLE_IP>/cli?cmd=state'` from another machine

### Entities unavailable: ping works but curl hangs → power-cycle the kettle

The known failure signature of the kettle's firmware:

```bash
ping <KETTLE_IP>                            # answers
curl -m 5 'http://<KETTLE_IP>/cli?cmd=state'  # hangs / connect timeout
```

means the kettle is on WiFi but its ESP32 web server has wedged and stopped accepting TCP connections — observed especially after long or back-to-back heating sessions. **Unplug the kettle's base for ~10 seconds and plug it back in**; entities recover automatically within ~30 seconds (the integration never stops retrying). This is a kettle-firmware limitation, not fixable from Home Assistant. If instead the kettle answers but every command comes back empty, see the next section.

The integration helps in two ways: while the kettle is unreachable it automatically slows its polling (up to 60s between attempts) so a struggling firmware isn't pinned down by connect attempts, and after ~5 minutes it raises an issue in **Settings → Repairs** describing exactly this fix. The Repair clears itself when the kettle answers again.

### Kettle firmware update stopped local control

**Symptoms:** the entities are unavailable. The kettle answers, but `http://<KETTLE_IP>/cli?cmd=state` shows only an empty "CLI Command" form, for every command, and unplugging the kettle doesn't help. The integration raises a **Settings → Repairs** card naming the firmware.

**Cause:** in October 2026 Fellow began updating kettles automatically to firmware 1.2.24, then 1.2.26. Both stop returning output from the local command interface: commands may still run, but nothing comes back, so nothing can be read. Firmware 1.2.26 has also been observed dropping WiFi while heating or keeping warm.

**Check:** open the kettle's version page, `http://<KETTLE_IP>/`. It shows the running firmware and what each firmware slot holds, for example:

```
Current version: 1.2.26 CLI
Boot partition: ota_1
Running partition: ota_1
partition 'factory' at 0x10000 size 0x200000 encr 0 state ?? fw version 1.1.14SSB
partition 'ota_0' at 0x210000 size 0x200000 encr 0 state valid fw version 1.1.76SSP
partition 'ota_1' at 0x410000 size 0x200000 encr 0 state valid fw version 1.2.26
```

**Fix: switch back to the previous firmware.** The kettle keeps its previous firmware in the slot it isn't running from (`ota_0` above). If that slot holds an older version, such as `1.1.76SSP`, and isn't marked `invalid`:

1. **Block the kettle's internet access first**, keeping local access. Otherwise the old firmware's update check, about every 30 minutes, reinstalls the update.
   - **UniFi Network 9 and later:** Settings → Policy Engine (or Security → Firewall) → **Create Policy**. Set the action to **Block**, the source zone to your kettle network's zone (usually Internal), the source to **Device** → the kettle, and the destination zone to **External**.
   - **Older UniFi:** Settings → Security → **Traffic Rules**: Block · Internet · the kettle. Or use an *Internet Out* firewall rule that drops the kettle's IP.
   - **Other routers:** block the kettle's IP from reaching the internet. Blocking the update server `qhderznbzup.firmware.fellowproducts.com` in DNS also works if the kettle uses your DNS server.

   While you're there, give the kettle a fixed IP address.
2. Open `http://<KETTLE_IP>/cli?cmd=setpart+ota_0` in a browser, using your spare slot's name. You'll see only the empty form.
3. Reload `http://<KETTLE_IP>/` and check that it shows `Boot partition: ota_0`. If it still shows the old slot, the firmware isn't running commands: stop here.
4. Open `http://<KETTLE_IP>/cli?cmd=reset`. The page won't load while the kettle restarts; that's expected.
5. After about 30 seconds, the version page should show the older firmware as running, and `cmd=state` returns readings again. Reload the integration, then turn on **Keep the kettle's clock synced** in its options, since the kettle can no longer get the time from the internet.

Keep the internet block on permanently. A later update would also overwrite the spare slot, and with it the way back. **Never send `eraseotherpart`**: it erases the spare slot.

On 1.2.x firmware, the kettle's own *Auto update* menu toggle only passes your preference on to Fellow's update server, which makes the final call, so don't rely on it in place of the router block.

**If the spare slot holds no older firmware** (for example, both slots hold 1.2.x), there's no simple way back. [stagg-ekg-plus-ha](https://github.com/bramboe/stagg-ekg-plus-ha) supports firmware 1.2.26 over Bluetooth, which needs a Bluetooth adapter or an ESPHome Bluetooth proxy within range of the kettle.

The diagnosis and switch-back procedure come from [stagg-ekg-plus-ha issue #5](https://github.com/bramboe/stagg-ekg-plus-ha/issues/5).

### Setting temperature doesn't stick

The integration tries `setsettingd settempr` (EKG Pro), then the legacy `setsetting settempr` (EKG+), then dial emulation, verifying each by read-back. If it always ends up dialing, switch the *Temperature-setting method* option to *Dial emulation* to skip the probes. Check debug logs to see which path was used.

## Standalone Python API

[`examples/stagg_ekg_api.py`](examples/stagg_ekg_api.py) is a standalone client for use outside Home Assistant, and [`examples/probe_kettle.py`](examples/probe_kettle.py) is the read-only diagnostic capture tool. See [examples/README.md](examples/README.md).

## Technical Details

- **Protocol:** HTTP GET to `/cli?cmd=<command>` on port 80, plain-text responses (an undocumented firmware debug interface — it can change with firmware updates). The firmware version and slot table come from the version page at `/`, which still answers when the command interface is muted.
- **Platform:** ESP32 (Espressif)
- **Range:** 40–100°C (104–212°F)
- **Polling:** adaptive — every 3 seconds while heating/keeping warm, every 10 seconds when idle (both configurable in options)

See [KETTLE_SPECS.md](KETTLE_SPECS.md) for the command reference, including the EKG Pro differences and the list of commands that must never be sent.

## Contributing

Contributions are welcome! Run the parser tests with `pip install pytest && pytest tests/` — no Home Assistant installation needed. If your kettle's responses parse incorrectly, include `probe_kettle.py` output in your issue.

## License

This is free and unencumbered software released into the public domain. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built for [Fellow](https://fellowproducts.com/) Stagg EKG WiFi kettles
- Began as a fork of [rderewianko/fellow-ekg](https://github.com/rderewianko/fellow-ekg), then substantially rewritten for the EKG Pro
- Took alot of design inspiration from [sopelj](https://github.com/sopelj/hass-ember-mug-component)
- EKG Pro command set cross-checked against the [stagg-ekg-pro](https://github.com/montymhughes/stagg-ekg-pro) reverse-engineering project
- Firmware 1.2.x diagnosis, the switch-back procedure, and the Identify beep pattern come from [stagg-ekg-plus-ha](https://github.com/bramboe/stagg-ekg-plus-ha)
- **Created with AI assistance** — developed with Claude Code

## Disclaimer

This is an unofficial integration not affiliated with Fellow Products. It drives an undocumented debug interface; use at your own risk.
