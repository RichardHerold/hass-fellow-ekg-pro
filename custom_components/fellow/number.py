"""Number platform for Stagg EKG integration: kettle settings.

Hold duration (keep-warm auto-off) and chime volume. Initial values are
read once from prtsettings at setup — the kettle isn't re-polled for
settings on every cycle — so a change made on the kettle's own menu shows
up here after a reload.
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import StaggEKGDataUpdateCoordinator
from .const import (
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
    MAX_TEMP_C,
    MAX_TEMP_F,
    MIN_TEMP_C,
    MIN_TEMP_F,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Stagg EKG setting numbers."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Best-effort initial values; entities show unknown until first set
    # if the kettle doesn't answer or uses different setting keys.
    settings: dict = {}
    try:
        settings = await hass.async_add_executor_job(coordinator.client.get_settings)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Could not read initial settings: %s", err)

    def initial(key: str) -> float | None:
        try:
            return float(settings[key])
        except (KeyError, ValueError, TypeError):
            return None

    async_add_entities(
        [
            StaggEKGTargetTempNumber(coordinator, entry),
            StaggEKGHoldMinutesNumber(coordinator, entry, initial("hold")),
            StaggEKGChimeNumber(coordinator, entry, initial("chime")),
        ]
    )


class StaggEKGTargetTempNumber(CoordinatorEntity, NumberEntity):
    """Target-temperature slider: sets the active target WITHOUT starting
    heating — the counterpart to heat_to and the preset buttons, which
    always start a cycle. The Target Temperature sensor reports what the
    kettle says; this number is the control."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = "slider"
    _attr_icon = "mdi:thermometer-lines"

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{entry.entry_id}_set_target"
        self._attr_name = "Set Target"

        configured_unit = entry.options.get(
            CONF_TEMPERATURE_UNIT, entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)
        )
        self._fahrenheit = configured_unit == UNIT_FAHRENHEIT
        if self._fahrenheit:
            self._attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
            self._attr_native_min_value = MIN_TEMP_F
            self._attr_native_max_value = MAX_TEMP_F
            self._attr_native_step = 1
        else:
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_native_min_value = MIN_TEMP_C
            self._attr_native_max_value = MAX_TEMP_C
            self._attr_native_step = 0.5

    @property
    def native_value(self) -> float | None:
        """Return the kettle's current target in the configured unit."""
        if not (self.coordinator.data and "state" in self.coordinator.data):
            return None
        temp_c = self.coordinator.data["state"].target_temp_c
        if temp_c is None:
            return None
        return round(temp_c * 9 / 5 + 32, 1) if self._fahrenheit else temp_c

    async def async_set_native_value(self, value: float) -> None:
        """Set the active target temperature (does not start heating)."""
        temp_c = (value - 32) * 5 / 9 if self._fahrenheit else value
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_temperature, temp_c
        )
        await self.coordinator.async_request_refresh()


class StaggEKGNumberBase(CoordinatorEntity, NumberEntity):
    """Base class for kettle setting numbers."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = "box"

    def __init__(
        self,
        coordinator: StaggEKGDataUpdateCoordinator,
        entry: ConfigEntry,
        initial_value: float | None,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info
        self._attr_native_value = initial_value

    @property
    def available(self) -> bool:
        # Settings aren't in the poll data; stay available as long as the
        # coordinator is healthy.
        return self.coordinator.last_update_success


class StaggEKGHoldMinutesNumber(StaggEKGNumberBase):
    """Keep-warm hold duration: how long Hold stays on before auto-off."""

    _attr_native_min_value = 1
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-cog-outline"

    def __init__(
        self,
        coordinator: StaggEKGDataUpdateCoordinator,
        entry: ConfigEntry,
        initial_value: float | None,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, entry, initial_value)
        self._attr_unique_id = f"{entry.entry_id}_hold_minutes"
        self._attr_name = "Hold Duration"

    async def async_set_native_value(self, value: float) -> None:
        """Set the hold duration on the kettle."""
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_hold_minutes, int(value)
        )
        self._attr_native_value = int(value)
        self.async_write_ha_state()


class StaggEKGChimeNumber(StaggEKGNumberBase):
    """Chime volume (0 = silent)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(
        self,
        coordinator: StaggEKGDataUpdateCoordinator,
        entry: ConfigEntry,
        initial_value: float | None,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, entry, initial_value)
        self._attr_unique_id = f"{entry.entry_id}_chime"
        self._attr_name = "Chime Volume"

    async def async_set_native_value(self, value: float) -> None:
        """Set the chime volume on the kettle."""
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_chime, int(value)
        )
        self._attr_native_value = int(value)
        self.async_write_ha_state()
