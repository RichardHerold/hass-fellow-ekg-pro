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
OPERATION_MODE_STANDBY = "standby"


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
    _attr_operation_list = [OPERATION_MODE_OFF, OPERATION_MODE_HEAT, OPERATION_MODE_STANDBY]

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
        """Return current operation (off, heat, standby)."""
        if not self.coordinator.data or "state" not in self.coordinator.data:
            return OPERATION_MODE_OFF

        state = self.coordinator.data["state"]
        mode = state.mode

        if mode == "S_Off":
            return OPERATION_MODE_OFF
        elif state.heating:
            return OPERATION_MODE_HEAT
        else:
            return OPERATION_MODE_STANDBY

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return

        # Convert to Celsius if needed
        if self._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT:
            temp_celsius = (temperature - 32) * 5/9
        else:
            temp_celsius = temperature

        # Calculate steps needed to reach target temperature
        current_state = self.coordinator.data["state"]
        current_target = current_state.set_temp_c
        temp_diff = temp_celsius - current_target

        # Each dial step changes temperature by 0.5°C (value changes by 1 in "2C" format)
        # Verified: 90 steps = 45°C change (from 40°C to 85°C)
        steps = int(round(temp_diff * 2))

        if steps > 0:
            await self.hass.async_add_executor_job(
                self.coordinator.client.rotate_dial_right, abs(steps)
            )
        elif steps < 0:
            await self.hass.async_add_executor_job(
                self.coordinator.client.rotate_dial_left, abs(steps)
            )

        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        if operation_mode == OPERATION_MODE_OFF:
            # Turn off and power down
            await self.hass.async_add_executor_job(self.coordinator.client.stop_heating)
        elif operation_mode == OPERATION_MODE_HEAT:
            # Start heating (wakes screen and starts heating)
            await self.hass.async_add_executor_job(self.coordinator.client.start_heating)
        elif operation_mode == OPERATION_MODE_STANDBY:
            # Power on screen but don't heat
            await self.hass.async_add_executor_job(self.coordinator.client.power_on)

        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the kettle on and start heating."""
        # Check if water might be low
        if self.coordinator.data and "state" in self.coordinator.data:
            state = self.coordinator.data["state"]
            if state.may_have_no_water:
                _LOGGER.warning("Kettle temperature very low (%s°C) - may not have water!", state.current_temp_c)

        await self.hass.async_add_executor_job(self.coordinator.client.start_heating)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the kettle off."""
        await self.hass.async_add_executor_job(self.coordinator.client.stop_heating)
        await self.coordinator.async_request_refresh()
