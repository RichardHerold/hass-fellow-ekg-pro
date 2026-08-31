"""Switch platform for Stagg EKG integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up Stagg EKG switches."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        StaggEKGHeatingSwitch(coordinator, entry),
        StaggEKGWarmingSwitch(coordinator, entry),
        StaggEKGHeaterElementSwitch(coordinator, entry),
    ]

    async_add_entities(entities)


class StaggEKGSwitchBase(CoordinatorEntity, SwitchEntity):
    """Base class for Stagg EKG switches."""

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info

    @property
    def _state(self):
        if self.coordinator.data and "state" in self.coordinator.data:
            return self.coordinator.data["state"]
        return None


class StaggEKGHeatingSwitch(StaggEKGSwitchBase):
    """Switch to control heating."""

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_heating"
        self._attr_name = "Heating"
        self._attr_icon = "mdi:fire"

    @property
    def is_on(self) -> bool:
        """Return true if heating is on."""
        state = self._state
        return state.is_heating if state else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn heating on."""
        await self.hass.async_add_executor_job(self.coordinator.client.start_heating)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn heating off."""
        await self.hass.async_add_executor_job(self.coordinator.client.stop_heating)
        await self.coordinator.async_request_refresh()


class StaggEKGWarmingSwitch(StaggEKGSwitchBase):
    """Switch to control keep-warm (Hold mode)."""

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_warming"
        self._attr_name = "Warming"
        self._attr_icon = "mdi:fire-circle"

    @property
    def is_on(self) -> bool:
        """Return true if warming is on."""
        state = self._state
        if state is None:
            return False
        return state.warming or state.is_holding

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn warming on (enter Hold mode)."""
        await self.hass.async_add_executor_job(self.coordinator.client.start_hold)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn warming off (back to Off mode)."""
        await self.hass.async_add_executor_job(self.coordinator.client.stop_heating)
        await self.coordinator.async_request_refresh()


class StaggEKGHeaterElementSwitch(StaggEKGSwitchBase):
    """ADVANCED: direct heater-element GPIO control (heaton/heatoff).

    Bypasses the firmware state machine and its safety logic — the display
    won't reflect it and normal auto-shutoff may not apply. Disabled by
    default; enable it only if you know you want raw element control.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_heater_element"
        self._attr_name = "Heater Element (Direct)"
        self._attr_icon = "mdi:heating-coil"

    @property
    def is_on(self) -> bool:
        """Return true if the heater-output flag is set."""
        state = self._state
        if state is None:
            return False
        return bool(state.flags.get("ho", 0))

    @property
    def extra_state_attributes(self):
        """Warn in the UI about what this switch actually does."""
        return {
            "warning": "Drives the heater element directly, bypassing the "
            "firmware state machine. Prefer the Heating switch."
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the heater element GPIO on."""
        await self.hass.async_add_executor_job(self.coordinator.client.heat_on)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the heater element GPIO off."""
        await self.hass.async_add_executor_job(self.coordinator.client.heat_off)
        await self.coordinator.async_request_refresh()
