"""The Fellow Stagg EKG+ / EKG Pro integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_POLL_INTERVAL,
    CONF_TEMP_SET_METHOD,
    DEFAULT_ACTIVE_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    TEMP_METHOD_DIRECT,
)
from .kettle import KettleTransientError, StaggEKGClient
from .parser import is_water_ready

# After this many consecutive transient failures, give up holding the
# last known state and let HA mark the device unavailable. At the default
# 10s poll interval that's roughly a minute of staleness — long enough to
# absorb the "kettle just turned off" window, short enough that a truly
# offline kettle doesn't show stale data forever.
MAX_CONSECUTIVE_TRANSIENT_FAILURES = 6

# Lift-detection: once we observe the kettle leaving the base, treat it
# as "lifted" for at least this long, even if a brief docked reading
# appears (the kettle can flap as it's set back down).
LIFT_COOLDOWN_SECONDS = 90

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stagg EKG from a config entry."""
    host = entry.data["host"]
    # Options take precedence over the original entry data so changes from
    # the options flow apply without re-adding the integration.
    temp_method = entry.options.get(
        CONF_TEMP_SET_METHOD,
        entry.data.get(CONF_TEMP_SET_METHOD, TEMP_METHOD_DIRECT),
    )
    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    active_poll_interval = entry.options.get(
        CONF_ACTIVE_POLL_INTERVAL, DEFAULT_ACTIVE_POLL_INTERVAL
    )

    client = StaggEKGClient(host=host, temp_method=temp_method)

    # Best-effort device metadata; must never block or fail setup.
    fw_info = await hass.async_add_executor_job(client.get_firmware_info)
    mac = await hass.async_add_executor_job(client.get_mac)

    coordinator = StaggEKGDataUpdateCoordinator(
        hass, client, poll_interval, active_poll_interval
    )
    coordinator.device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        connections={(dr.CONNECTION_NETWORK_MAC, format_mac(mac))} if mac else set(),
        name=entry.title or "Fellow Stagg EKG",
        manufacturer="Fellow",
        model=fw_info.get("project") or "Stagg EKG (WiFi)",
        sw_version=fw_info.get("version"),
        configuration_url=f"http://{host}",
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Positive confirmation in the log that the kettle was reached AND
    # understood — the counterpart of the config flow's strict validation.
    if coordinator.data and "state" in coordinator.data:
        state = coordinator.data["state"]
        _LOGGER.info(
            "Fellow kettle at %s is up: mode=%s current=%s°C target=%s°C "
            "firmware=%s mac=%s",
            host,
            state.mode,
            state.current_temp_c,
            state.target_temp_c,
            fw_info.get("version", "unknown"),
            mac or "unknown",
        )

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload when options change so settings like temp_set_method take
    # effect without an HA restart.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when the user changes options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class StaggEKGDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Stagg EKG data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: StaggEKGClient,
        poll_interval: int,
        active_poll_interval: int,
    ) -> None:
        """Initialize."""
        self.client = client
        self.device_info: DeviceInfo | None = None
        self.water_ready: bool = False
        self._idle_interval = timedelta(seconds=poll_interval)
        self._active_interval = timedelta(seconds=active_poll_interval)
        self._consecutive_transient_failures = 0
        self._was_docked: bool | None = None
        self._lifted_at = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._idle_interval,
        )

    @property
    def recently_lifted(self) -> bool:
        """Whether the kettle was lifted off the base in the recent past.

        Edge-triggered on docked → undocked, with a cooldown window so a
        single flapping reading after re-docking doesn't immediately clear
        the signal.
        """
        if self._lifted_at is None:
            return False
        return (
            dt_util.utcnow() - self._lifted_at
        ).total_seconds() < LIFT_COOLDOWN_SECONDS

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            state = await self.hass.async_add_executor_job(self.client.get_state)
        except KettleTransientError as err:
            # The kettle stops answering HTTP (or returns truncated data)
            # for a few seconds when it transitions to Off. Hold the last
            # known state for a while instead of surfacing an error every
            # time that happens — but give up after enough consecutive
            # failures so HA can mark the device unavailable if it really
            # is offline.
            self._consecutive_transient_failures += 1
            if (
                self.data is not None
                and self._consecutive_transient_failures
                <= MAX_CONSECUTIVE_TRANSIENT_FAILURES
            ):
                _LOGGER.debug(
                    "Kettle transient failure %d/%d, keeping last state: %s",
                    self._consecutive_transient_failures,
                    MAX_CONSECUTIVE_TRANSIENT_FAILURES,
                    err,
                )
                return self.data
            raise UpdateFailed(f"Kettle unresponsive: {err}")
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

        self._consecutive_transient_failures = 0

        # Track docked → undocked transition for lift detection. Only a
        # response that actually carried a temperature field counts — a
        # truncated response without one is a parse anomaly, not a lift.
        if state.temp_field_present:
            if self._was_docked and not state.is_docked:
                self._lifted_at = dt_util.utcnow()
            self._was_docked = state.is_docked

        self.water_ready = is_water_ready(state)

        # Adaptive polling: track a live heat/hold cycle closely so the
        # climbing temperature and Water Ready stay fresh, then relax to
        # the idle interval when the kettle is off. The coordinator never
        # overlaps refreshes, so a stalling kettle just stretches a cycle
        # rather than piling up requests.
        wanted = (
            self._active_interval
            if (state.is_heating or state.is_holding)
            else self._idle_interval
        )
        if self.update_interval != wanted:
            _LOGGER.debug(
                "Switching poll interval to %ss (%s)",
                wanted.total_seconds(),
                "active" if wanted == self._active_interval else "idle",
            )
            self.update_interval = wanted

        return {"state": state}
