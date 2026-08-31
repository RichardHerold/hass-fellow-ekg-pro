"""Diagnostics support for the Fellow Stagg EKG integration.

Settings → Devices & Services → Fellow → Download diagnostics produces a
bundle with the last parsed state, the raw firmware responses, and the
entry configuration — everything needed to debug a model/firmware whose
CLI output differs from what the parser expects.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import StaggEKGDataUpdateCoordinator
from .const import DOMAIN
from .kettle import CMD_FWINFO, CMD_PRTSETTINGS, CMD_STATE, CMD_WIFIPRT

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    last_state: dict[str, Any] | None = None
    if coordinator.data and "state" in coordinator.data:
        last_state = asdict(coordinator.data["state"])

    raw_responses: dict[str, str] = {}
    for cmd in (CMD_STATE, CMD_PRTSETTINGS, CMD_FWINFO, CMD_WIFIPRT):
        try:
            raw_responses[cmd] = await hass.async_add_executor_job(
                coordinator.client.get_raw, cmd
            )
        except Exception as err:  # pylint: disable=broad-except
            raw_responses[cmd] = f"<error: {err}>"

    return {
        "note": "raw_responses come straight from the kettle firmware and "
        "may include network details (IP, SSID, MAC); review before sharing.",
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "unique_id": entry.unique_id,
        },
        "last_parsed_state": last_state,
        "raw_responses": raw_responses,
    }
