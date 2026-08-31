"""Sensor platform for Stagg EKG integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
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
    """Set up Stagg EKG sensors."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        StaggEKGCurrentTempSensor(coordinator, entry),
        StaggEKGTargetTempSensor(coordinator, entry),
        StaggEKGModeSensor(coordinator, entry),
        StaggEKGTimeToReadySensor(coordinator, entry),
        StaggEKGBoilThresholdSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class StaggEKGSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Stagg EKG sensors."""

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_device_info = coordinator.device_info

    @property
    def _state(self):
        if self.coordinator.data and "state" in self.coordinator.data:
            return self.coordinator.data["state"]
        return None


class StaggEKGCurrentTempSensor(StaggEKGSensorBase):
    """Current temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_current_temp"
        self._attr_name = "Current Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        state = self._state
        return state.current_temp_c if state else None


class StaggEKGTargetTempSensor(StaggEKGSensorBase):
    """Target temperature sensor (a setpoint, so no measurement state class)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_target_temp"
        self._attr_name = "Target Temperature"

    @property
    def native_value(self) -> float | None:
        """Return the target temperature, or None when the kettle doesn't report one."""
        state = self._state
        return state.target_temp_c if state else None


class StaggEKGModeSensor(StaggEKGSensorBase):
    """Kettle mode sensor."""

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_name = "Mode"

    @property
    def icon(self) -> str:
        """Steam the kettle icon while it's actively heating."""
        state = self._state
        if state and state.is_heating:
            return "mdi:kettle-steam"
        return "mdi:kettle"

    @property
    def native_value(self) -> str | None:
        """Return the kettle mode."""
        state = self._state
        if state is None:
            return None
        mode = state.mode
        # Clean up mode name
        if mode.startswith("S_"):
            mode = mode[2:]
        return mode


class StaggEKGTimeToReadySensor(StaggEKGSensorBase):
    """Projected minutes until the water reaches target while heating.

    Computed from the heating rate over the last ~90 seconds of polls.
    Unknown while the kettle is off, holding, or too early in a cycle to
    have a stable rate.
    """

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:timer-sand"

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_time_to_ready"
        self._attr_name = "Time to Ready"

    @property
    def native_value(self) -> float | None:
        """Return the estimated minutes until target."""
        minutes = self.coordinator.minutes_to_ready
        return round(minutes, 1) if minutes is not None else None


class StaggEKGBoilThresholdSensor(StaggEKGSensorBase):
    """Boil threshold reported by the kettle (altitude-adjusted). Diagnostic."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_boil_threshold"
        self._attr_name = "Boil Threshold"

    @property
    def native_value(self) -> float | None:
        """Return the boil threshold temperature."""
        state = self._state
        return state.boil_temp_c if state else None
