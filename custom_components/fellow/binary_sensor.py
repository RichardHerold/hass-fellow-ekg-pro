"""Binary sensor platform for Stagg EKG integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
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
    """Set up Stagg EKG binary sensors."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        StaggEKGPowerBinarySensor(coordinator, entry),
        StaggEKGWaterBinarySensor(coordinator, entry),
        StaggEKGLiftedBinarySensor(coordinator, entry),
    ]

    async_add_entities(entities)


class StaggEKGBinarySensorBase(CoordinatorEntity, BinarySensorEntity):
    """Base class for Stagg EKG binary sensors."""

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_has_entity_name = True

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


class StaggEKGPowerBinarySensor(StaggEKGBinarySensorBase):
    """Binary sensor for kettle power state."""

    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_name = "Power"

    @property
    def is_on(self) -> bool:
        """Return true if kettle is powered on."""
        if self.coordinator.data and "state" in self.coordinator.data:
            return self.coordinator.data["state"].is_powered_on
        return False

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        if self.coordinator.data and "state" in self.coordinator.data:
            state = self.coordinator.data["state"]
            return {
                "mode": state.mode,
                "screen": state.screen_name,
                "in_menu": state.is_in_menu,
            }
        return {}


class StaggEKGLiftedBinarySensor(StaggEKGBinarySensorBase):
    """Binary sensor that fires when the kettle is taken off the base."""

    _attr_device_class = BinarySensorDeviceClass.MOVING

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_lifted"
        self._attr_name = "Lifted"
        self._attr_icon = "mdi:kettle-pour-over"

    @property
    def is_on(self) -> bool:
        """Return true if the kettle was recently lifted from the base."""
        return self.coordinator.recently_lifted


class StaggEKGWaterBinarySensor(StaggEKGBinarySensorBase):
    """Binary sensor for water detection."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_warning"
        self._attr_name = "Low Water Warning"
        self._attr_icon = "mdi:water-alert"

    @property
    def is_on(self) -> bool:
        """Return true if kettle may have low/no water."""
        if self.coordinator.data and "state" in self.coordinator.data:
            return self.coordinator.data["state"].may_have_no_water
        return False

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        if self.coordinator.data and "state" in self.coordinator.data:
            state = self.coordinator.data["state"]
            return {
                "current_temperature": state.current_temp_c,
                "note": "Temperature below 30°C may indicate no water",
            }
        return {}
