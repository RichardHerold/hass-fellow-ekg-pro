"""Button platform for Stagg EKG integration: one-tap heat presets.

A built-in Boil button, plus user-configured presets from the options flow
("Name: temperature" pairs). Pressing a button sets the target temperature
and starts heating — the single action people actually want on a dashboard.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from . import StaggEKGDataUpdateCoordinator
from .const import (
    CONF_PRESETS,
    CONF_TEMPERATURE_UNIT,
    DEFAULT_PRESETS,
    DOMAIN,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)
from .presets import parse_preset_list

_LOGGER = logging.getLogger(__name__)

BOIL_TEMP_C = 100.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up preset buttons."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    configured_unit = entry.options.get(
        CONF_TEMPERATURE_UNIT, entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)
    )
    presets_text = entry.options.get(CONF_PRESETS, DEFAULT_PRESETS)
    try:
        presets = parse_preset_list(
            presets_text, fahrenheit=configured_unit == UNIT_FAHRENHEIT
        )
    except ValueError as err:
        # The options flow validates on save; this guards legacy/hand-edited
        # entries. Bad presets shouldn't take down the integration.
        _LOGGER.warning("Ignoring invalid presets option (%s)", err)
        presets = []

    entities: list[ButtonEntity] = [
        StaggEKGPresetButton(coordinator, entry, "Boil", BOIL_TEMP_C)
    ]
    for name, temp_c in presets:
        entities.append(StaggEKGPresetButton(coordinator, entry, name, temp_c))
    entities.append(StaggEKGSyncClockButton(coordinator, entry))

    # Drop registry entries for presets that were removed or renamed, so
    # stale buttons don't linger as unavailable entities.
    registry = er.async_get(hass)
    valid_ids = {entity.unique_id for entity in entities}
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain == "button" and reg_entry.unique_id not in valid_ids:
            registry.async_remove(reg_entry.entity_id)

    async_add_entities(entities)


class StaggEKGPresetButton(CoordinatorEntity, ButtonEntity):
    """One-tap 'heat to <preset>' button."""

    _attr_icon = "mdi:kettle-steam"

    def __init__(
        self,
        coordinator: StaggEKGDataUpdateCoordinator,
        entry: ConfigEntry,
        name: str,
        temp_c: float,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._entry = entry
        self._temp_c = temp_c
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{entry.entry_id}_preset_{slugify(name)}"

        configured_unit = entry.options.get(
            CONF_TEMPERATURE_UNIT, entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)
        )
        if configured_unit == UNIT_FAHRENHEIT:
            shown = round(temp_c * 9 / 5 + 32)
            self._attr_name = f"{name} ({shown}°F)"
        else:
            shown = round(temp_c) if temp_c == int(temp_c) else temp_c
            self._attr_name = f"{name} ({shown}°C)"

    async def async_press(self) -> None:
        """Set the preset temperature and start heating."""
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_temperature, self._temp_c
        )
        await self.hass.async_add_executor_job(
            self.coordinator.client.start_heating
        )
        await self.coordinator.async_request_refresh()


class StaggEKGSyncClockButton(CoordinatorEntity, ButtonEntity):
    """Set the kettle's display clock to Home Assistant's local time."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-check-outline"

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{entry.entry_id}_sync_clock"
        self._attr_name = "Sync Clock"

    async def async_press(self) -> None:
        """Push HA's local time to the kettle's clock."""
        local = dt_util.now()
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_clock, local.hour, local.minute, local.second
        )
