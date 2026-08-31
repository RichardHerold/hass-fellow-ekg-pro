"""Binary sensor platform for Stagg EKG integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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

    # The Water Ready binary sensor was replaced by the Kettle State enum
    # sensor; drop its registry entry so it doesn't linger as an orphan.
    registry = er.async_get(hass)
    stale = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_water_ready"
    )
    if stale:
        registry.async_remove(stale)

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
        self._attr_device_info = coordinator.device_info

    @property
    def _state(self):
        if self.coordinator.data and "state" in self.coordinator.data:
            return self.coordinator.data["state"]
        return None


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
        state = self._state
        return state.is_powered_on if state else False

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        state = self._state
        if state is None:
            return {}
        return {
            "mode": state.mode,
            "screen": state.screen_name,
            "in_menu": state.is_in_menu,
        }


class StaggEKGLiftedBinarySensor(StaggEKGBinarySensorBase):
    """Binary sensor that fires when the kettle is taken off the base.

    Inferred from the temperature reading disappearing/going implausible;
    disabled by default until verified on your kettle model.
    """

    _attr_device_class = BinarySensorDeviceClass.MOVING
    _attr_entity_registry_enabled_default = False

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
    """Binary sensor for the firmware's 'nw' (no water) flag.

    The flag's meaning is inferred from the ketl= status line and hasn't
    been verified on all models, so this is a disabled-by-default
    diagnostic. The full flags dict is exposed as attributes so you can
    watch which flag actually flips when you lift or empty the kettle.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: StaggEKGDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_warning"
        self._attr_name = "Low Water Warning"
        self._attr_icon = "mdi:water-alert"

    @property
    def is_on(self) -> bool | None:
        """Return the firmware's no-water flag, or None when not reported."""
        state = self._state
        if state is None or "nw" not in state.flags:
            return None
        return bool(state.flags["nw"])

    @property
    def extra_state_attributes(self):
        """Expose all firmware status flags for ground-truthing."""
        state = self._state
        if state is None:
            return {}
        return {
            "flags": state.flags,
            "note": "The 'nw' flag is assumed to mean no-water; watch these "
            "flags while lifting/emptying the kettle to confirm.",
        }
