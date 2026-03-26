"""Water heater platform for Stagg EKG integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import StaggEKGDataUpdateCoordinator
from .const import DOMAIN, CONF_TEMPERATURE_UNIT, UNIT_CELSIUS, UNIT_FAHRENHEIT

_LOGGER = logging.getLogger(__name__)

# Temperature bounds (Celsius)
MIN_TEMP_C = 40
MAX_TEMP_C = 100

# Temperature bounds (Fahrenheit)
MIN_TEMP_F = 104
MAX_TEMP_F = 212

# Operation modes
OPERATION_MODE_OFF = "off"
OPERATION_MODE_HEAT = "heat"
OPERATION_MODE_WARM = "warm"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Stagg EKG water heater."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([StaggEKGWaterHeater(coordinator, entry)])


class StaggEKGWaterHeater(CoordinatorEntity, WaterHeaterEntity):
    """Representation of a Stagg EKG kettle as a water heater."""

    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.ON_OFF
        | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_operation_list = [OPERATION_MODE_OFF, OPERATION_MODE_HEAT, OPERATION_MODE_WARM]

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the water heater."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_water_heater"
        self._attr_name = "Kettle"
        self._attr_has_entity_name = True

        # Set temperature unit based on configuration
        configured_unit = entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)
        if configured_unit == UNIT_FAHRENHEIT:
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
            self._attr_min_temp = MIN_TEMP_F
            self._attr_max_temp = MAX_TEMP_F
        else:
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_min_temp = MIN_TEMP_C
            self._attr_max_temp = MAX_TEMP_C

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Stagg EKG+",
            "manufacturer": "Fellow",
            "model": "Stagg EKG+",
            "sw_version": "1.1.76SSP",
        }

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.coordinator.data and "state" in self.coordinator.data:
            temp_c = self.coordinator.data["state"].current_temp_c
            if temp_c is None:
                return None
            # Convert to configured unit
            if self._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT:
                return round(temp_c * 9/5 + 32, 1)
            return temp_c
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.coordinator.data and "state" in self.coordinator.data:
            temp_c = self.coordinator.data["state"].set_temp_c
            # Convert to configured unit
            if self._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT:
                return round(temp_c * 9/5 + 32, 1)
            return temp_c
        return None

    @property
    def current_operation(self) -> str:
        """Return current operation (off, heat, warm)."""
        if not self.coordinator.data or "state" not in self.coordinator.data:
            return OPERATION_MODE_OFF

        state = self.coordinator.data["state"]

        if state.is_off:
            return OPERATION_MODE_OFF
        elif state.is_heating:
            return OPERATION_MODE_HEAT
        elif state.warming or state.is_holding:
            return OPERATION_MODE_WARM
        else:
            # S_Standby, S_HeatOff without warming = effectively off
            return OPERATION_MODE_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.data or "state" not in self.coordinator.data:
            return None
        return {
            "docked": self.coordinator.data["state"].is_docked,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature using batched dial rotation."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return

        # Convert to Celsius if needed
        if self._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT:
            temp_celsius = (temperature - 32) * 5/9
        else:
            temp_celsius = temperature

        # The kettle client handles batching, verification, and self-correction
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_temperature, temp_celsius
        )

        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        if operation_mode == OPERATION_MODE_OFF:
            await self.hass.async_add_executor_job(
                self.coordinator.client.stop_heating
            )
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_warming, False
            )
        elif operation_mode == OPERATION_MODE_HEAT:
            await self.hass.async_add_executor_job(
                self.coordinator.client.start_heating
            )
        elif operation_mode == OPERATION_MODE_WARM:
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_warming, True
            )

        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the kettle on and start heating."""
        await self.hass.async_add_executor_job(
            self.coordinator.client.start_heating
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the kettle off."""
        await self.hass.async_add_executor_job(
            self.coordinator.client.stop_heating
        )
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_warming, False
        )
        await self.coordinator.async_request_refresh()
