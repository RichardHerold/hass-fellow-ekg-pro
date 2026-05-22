"""The Fellow Stagg EKG+ integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .kettle import KettleTransientError, StaggEKGClient

# After this many consecutive transient failures, give up holding the
# last known state and let HA mark the device unavailable. At a 5s poll
# interval that's roughly half a minute of staleness — long enough to
# absorb the "kettle just turned off" window, short enough that a truly
# offline kettle doesn't show stale data forever.
MAX_CONSECUTIVE_TRANSIENT_FAILURES = 6

# Lift-detection: once we observe the kettle leaving the base, treat it
# as "lifted" for at least this long, even if a brief docked reading
# appears (the kettle can flap as it's set back down).
LIFT_COOLDOWN_SECONDS = 90

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.WATER_HEATER, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stagg EKG from a config entry."""
    from .const import (
        CONF_TEMP_SET_METHOD,
        CONF_TEMPERATURE_UNIT,
        TEMP_METHOD_DIRECT,
        UNIT_CELSIUS,
    )

    host = entry.data["host"]
    # Options take precedence over the original entry data so changes from
    # the options flow apply without re-adding the integration.
    temp_method = entry.options.get(
        CONF_TEMP_SET_METHOD,
        entry.data.get(CONF_TEMP_SET_METHOD, TEMP_METHOD_DIRECT),
    )

    # Create API client
    client = StaggEKGClient(host=host, temp_method=temp_method)

    # Sync kettle units with configured preference
    configured_unit = entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)
    try:
        if configured_unit == UNIT_CELSIUS:
            await hass.async_add_executor_job(client.set_units_celsius)
        else:
            await hass.async_add_executor_job(client.set_units_fahrenheit)
    except Exception as err:
        _LOGGER.warning("Failed to sync kettle temperature units: %s", err)

    # Create update coordinator
    coordinator = StaggEKGDataUpdateCoordinator(hass, client)

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

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

    def __init__(self, hass: HomeAssistant, client: StaggEKGClient) -> None:
        """Initialize."""
        self.client = client
        self._consecutive_transient_failures = 0
        self._was_docked: bool | None = None
        self._lifted_at = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=5),
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

        # Track docked → undocked transition for lift detection. We only
        # care about the falling edge; the cooldown window in
        # `recently_lifted` handles re-dock flapping.
        if self._was_docked and not state.is_docked:
            self._lifted_at = dt_util.utcnow()
        self._was_docked = state.is_docked

        return {"state": state}
