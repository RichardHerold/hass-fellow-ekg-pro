"""The Fellow Stagg EKG+ integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .kettle import StaggEKGClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.WATER_HEATER, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stagg EKG from a config entry."""
    from .const import CONF_TEMPERATURE_UNIT, UNIT_CELSIUS

    host = entry.data["host"]

    # Create API client
    client = StaggEKGClient(host=host)

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

    return True


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

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            state = await self.hass.async_add_executor_job(self.client.get_state)
            settings = await self.hass.async_add_executor_job(self.client.get_settings)

            return {
                "state": state,
                "settings": settings,
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
