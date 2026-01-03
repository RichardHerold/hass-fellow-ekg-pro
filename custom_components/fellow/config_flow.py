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
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_TEMPERATURE_UNIT, UNIT_CELSIUS, UNIT_FAHRENHEIT
from .kettle import StaggEKGClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="10.1.1.177"): str,
        vol.Required(CONF_TEMPERATURE_UNIT, default=UNIT_CELSIUS): vol.In(
            [UNIT_CELSIUS, UNIT_FAHRENHEIT]
        ),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    client = StaggEKGClient(host=data[CONF_HOST])

    try:
        # Try to get state to verify connectivity
        state = await hass.async_add_executor_job(client.get_state)
    except Exception as err:
        _LOGGER.error("Cannot connect to kettle: %s", err)
        raise CannotConnect

    # Return info that you want to store in the config entry.
    return {"title": f"Stagg EKG+ ({data[CONF_HOST]})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stagg EKG."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Stagg EKG."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Update kettle units if changed
            new_unit = user_input[CONF_TEMPERATURE_UNIT]
            current_unit = self.config_entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)

            if new_unit != current_unit:
                # Update the kettle's unit setting
                client = StaggEKGClient(host=self.config_entry.data[CONF_HOST])
                try:
                    if new_unit == UNIT_CELSIUS:
                        await self.hass.async_add_executor_job(client.set_units_celsius)
                    else:
                        await self.hass.async_add_executor_job(client.set_units_fahrenheit)
                except Exception as err:
                    _LOGGER.error("Failed to update kettle units: %s", err)

            # Update config entry with new data
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **user_input}
            )
            return self.async_create_entry(title="", data={})

        current_unit = self.config_entry.data.get(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TEMPERATURE_UNIT,
                        default=current_unit
                    ): vol.In([UNIT_CELSIUS, UNIT_FAHRENHEIT]),
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
