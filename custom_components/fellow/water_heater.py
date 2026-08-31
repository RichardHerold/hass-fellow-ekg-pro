"""Water heater platform for Stagg EKG integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
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
    SERVICE_HEAT_TO,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)

_LOGGER = logging.getLogger(__name__)

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

    # fellow.heat_to: set the target and start heating in one action —
    # the call automations and dashboards actually want.
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_HEAT_TO,
        {vol.Required(ATTR_TEMPERATURE): vol.Coerce(float)},
        "async_heat_to",
    )


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
        self._attr_device_info = coordinator.device_info

        # Set temperature unit based on configuration (options take
        # precedence so changes apply on reload without re-adding).
        configured_unit = entry.options.get(
            CONF_TEMPERATURE_UNIT, entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)
        )
        if configured_unit == UNIT_FAHRENHEIT:
            self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
            self._attr_min_temp = MIN_TEMP_F
            self._attr_max_temp = MAX_TEMP_F
        else:
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_min_temp = MIN_TEMP_C
            self._attr_max_temp = MAX_TEMP_C

    @property
    def _state(self):
        if self.coordinator.data and "state" in self.coordinator.data:
            return self.coordinator.data["state"]
        return None

    def _to_display_unit(self, temp_c: float | None) -> float | None:
        if temp_c is None:
            return None
        if self._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return round(temp_c * 9 / 5 + 32, 1)
        return temp_c

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        state = self._state
        return self._to_display_unit(state.current_temp_c) if state else None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        state = self._state
        return self._to_display_unit(state.target_temp_c) if state else None

    @property
    def current_operation(self) -> str:
        """Return current operation (off, heat, warm)."""
        state = self._state
        if state is None:
            return OPERATION_MODE_OFF

        if state.is_off:
            return OPERATION_MODE_OFF
        if state.is_heating:
            return OPERATION_MODE_HEAT
        if state.is_holding:
            # Mode-based only: the wd flag means wind-down, not keep-warm.
            return OPERATION_MODE_WARM
        # S_Standby, S_HeatOff without holding = effectively off
        return OPERATION_MODE_OFF

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        state = self._state
        if state is None:
            return None
        return {
            "docked": state.is_docked,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get("temperature")
        if temperature is None:
            return

        # Convert to Celsius if needed
        if self._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT:
            temp_celsius = (temperature - 32) * 5 / 9
        else:
            temp_celsius = temperature

        # The kettle client handles verification and fallbacks
        await self.hass.async_add_executor_job(
            self.coordinator.client.set_temperature, temp_celsius
        )

        await self.coordinator.async_request_refresh()

    async def async_heat_to(self, temperature: float) -> None:
        """Set the target temperature and start heating, in one action.

        The temperature is interpreted in this entity's display unit,
        matching set_temperature semantics.
        """
        if self._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT:
            temp_celsius = (temperature - 32) * 5 / 9
        else:
            temp_celsius = temperature

        await self.hass.async_add_executor_job(
            self.coordinator.client.set_temperature, temp_celsius
        )
        await self.hass.async_add_executor_job(
            self.coordinator.client.start_heating
        )
        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set operation mode."""
        if operation_mode == OPERATION_MODE_OFF:
            await self.hass.async_add_executor_job(
                self.coordinator.client.stop_heating
            )
        elif operation_mode == OPERATION_MODE_HEAT:
            await self.hass.async_add_executor_job(
                self.coordinator.client.start_heating
            )
        elif operation_mode == OPERATION_MODE_WARM:
            await self.hass.async_add_executor_job(
                self.coordinator.client.start_hold
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
        await self.coordinator.async_request_refresh()
