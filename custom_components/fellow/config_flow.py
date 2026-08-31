"""Config flow for Stagg EKG integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac

from .const import (
    CONF_POLL_INTERVAL,
    CONF_SYNC_UNITS,
    CONF_TEMP_SET_METHOD,
    CONF_TEMPERATURE_UNIT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SYNC_UNITS,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    TEMP_METHOD_DIAL,
    TEMP_METHOD_DIRECT,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)
from .discovery import discover_kettles
from .kettle import StaggEKGClient

_LOGGER = logging.getLogger(__name__)

STEP_MANUAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_TEMPERATURE_UNIT, default=UNIT_CELSIUS): vol.In(
            [UNIT_CELSIUS, UNIT_FAHRENHEIT]
        ),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Returns a title and, when the kettle reports one, its MAC address for
    use as the config entry's unique ID.
    """
    client = StaggEKGClient(host=data[CONF_HOST])

    try:
        # Try to get state to verify connectivity
        await hass.async_add_executor_job(client.get_state)
    except Exception as err:
        _LOGGER.error("Cannot connect to kettle: %s", err)
        raise CannotConnect

    # Best-effort MAC for a stable unique ID (survives IP changes).
    mac = await hass.async_add_executor_job(client.get_mac)

    return {"title": f"Fellow Stagg EKG ({data[CONF_HOST]})", "mac": mac}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stagg EKG."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._discovered: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose manual entry or a network scan.

        Manual entry comes first: most people know their kettle's IP, and
        the scan probes every host on the local /24.
        """
        return self.async_show_menu(step_id="user", menu_options=["manual", "pick"])

    async def _async_validate_and_create(
        self, data: dict[str, Any], errors: dict[str, str]
    ) -> FlowResult | None:
        """Shared validate + unique-ID + create-entry path.

        Returns a FlowResult on success/abort, or None (with `errors`
        populated) when the caller should re-show its form.
        """
        try:
            info = await validate_input(self.hass, data)
        except CannotConnect:
            errors["base"] = "cannot_connect"
            return None
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
            return None

        # Prefer the MAC as unique ID (stable across IP changes); fall back
        # to the host so duplicates are still caught for kettles whose
        # firmware doesn't answer wifiprt.
        if info["mac"]:
            unique_id = format_mac(info["mac"])
        else:
            unique_id = f"host_{data[CONF_HOST]}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: data[CONF_HOST]})

        return self.async_create_entry(title=info["title"], data=data)

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Scan the network and let the user choose a discovered kettle."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_TEMPERATURE_UNIT: user_input[CONF_TEMPERATURE_UNIT],
            }
            result = await self._async_validate_and_create(data, errors)
            if result is not None:
                return result
        else:
            # Only scan when the user explicitly chose this path — the scan
            # probes every host on the local /24.
            self._discovered = await discover_kettles(self.hass)
            if not self._discovered:
                return await self.async_step_manual()

        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self._discovered[0]): vol.In(
                        {ip: ip for ip in self._discovered}
                    ),
                    vol.Required(
                        CONF_TEMPERATURE_UNIT, default=UNIT_CELSIUS
                    ): vol.In([UNIT_CELSIUS, UNIT_FAHRENHEIT]),
                }
            ),
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manual host entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_validate_and_create(user_input, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="manual", data_schema=STEP_MANUAL_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Stagg EKG."""

    def _current(self, key: str, default: Any) -> Any:
        """Read an option with entry-data fallback for legacy entries."""
        return self.config_entry.options.get(
            key, self.config_entry.data.get(key, default)
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            new_unit = user_input[CONF_TEMPERATURE_UNIT]
            current_unit = self._current(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)

            # Only touch the physical kettle's display when the user opted
            # into unit syncing and actually changed the unit.
            if user_input.get(CONF_SYNC_UNITS) and new_unit != current_unit:
                client = StaggEKGClient(host=self.config_entry.data[CONF_HOST])
                try:
                    if new_unit == UNIT_CELSIUS:
                        await self.hass.async_add_executor_job(client.set_units_celsius)
                    else:
                        await self.hass.async_add_executor_job(client.set_units_fahrenheit)
                except Exception as err:
                    _LOGGER.error("Failed to update kettle units: %s", err)

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TEMPERATURE_UNIT,
                        default=self._current(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS),
                    ): vol.In([UNIT_CELSIUS, UNIT_FAHRENHEIT]),
                    vol.Required(
                        CONF_TEMP_SET_METHOD,
                        default=self._current(CONF_TEMP_SET_METHOD, TEMP_METHOD_DIRECT),
                    ): vol.In([TEMP_METHOD_DIRECT, TEMP_METHOD_DIAL]),
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self._current(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                    vol.Required(
                        CONF_SYNC_UNITS,
                        default=self._current(CONF_SYNC_UNITS, DEFAULT_SYNC_UNITS),
                    ): bool,
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
