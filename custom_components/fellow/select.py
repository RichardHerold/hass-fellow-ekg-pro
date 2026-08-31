"""Select platform for Stagg EKG integration: kettle display unit.

Flips the °C/°F shown on the kettle's own screen — a first-class entity
(the Ember Mug integration's pattern) instead of a buried options toggle.
This changes only the kettle's display; the unit Home Assistant uses for
this integration's entities stays whatever was configured at setup.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import StaggEKGDataUpdateCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Stagg EKG selects."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([StaggEKGDisplayUnitSelect(coordinator, entry)])


class StaggEKGDisplayUnitSelect(CoordinatorEntity, SelectEntity):
    """The temperature unit shown on the kettle's own display."""

    _attr_options = ["celsius", "fahrenheit"]
    _attr_translation_key = "display_unit"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:thermometer"

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{entry.entry_id}_display_unit"

    @property
    def current_option(self) -> str | None:
        """Return the unit the kettle reports (units=1 Celsius, 0 Fahrenheit)."""
        if not (self.coordinator.data and "state" in self.coordinator.data):
            return None
        units = self.coordinator.data["state"].units
        if units is None:
            return None
        return "celsius" if units == 1 else "fahrenheit"

    async def async_select_option(self, option: str) -> None:
        """Switch the kettle's display unit."""
        if option == "celsius":
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_units_celsius
            )
        else:
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_units_fahrenheit
            )
        await self.coordinator.async_request_refresh()
