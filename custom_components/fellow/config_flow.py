"""Config flow for Stagg EKG integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac

from .const import (
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_POLL_INTERVAL,
    CONF_PRESETS,
    CONF_SYNC_CLOCK,
    CONF_SYNC_UNITS,
    CONF_TEMP_SET_METHOD,
    CONF_TEMPERATURE_UNIT,
    DEFAULT_ACTIVE_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PRESETS,
    DEFAULT_SYNC_CLOCK,
    DEFAULT_SYNC_UNITS,
    DOMAIN,
    MAX_ACTIVE_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    MIN_ACTIVE_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    TEMP_METHOD_DIAL,
    TEMP_METHOD_DIRECT,
    UNIT_CELSIUS,
    UNIT_FAHRENHEIT,
)
from .discovery import default_scan_networks, discover_kettles, parse_scan_network
from .kettle import StaggEKGClient
from .parser import prettify_model_name, state_problems
from .presets import parse_preset_list

CONF_NETWORK = "network"

_LOGGER = logging.getLogger(__name__)

STEP_MANUAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_TEMPERATURE_UNIT, default=UNIT_CELSIUS): vol.In(
            [UNIT_CELSIUS, UNIT_FAHRENHEIT]
        ),
        vol.Optional(CONF_NAME): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect AND understand the kettle.

    Connecting is not enough: a kettle can answer with a response format the
    parser doesn't understand, which would set up an integration whose
    temperature entities are all broken (a false-positive success). So the
    parsed state must actually contain usable temperatures before setup is
    allowed to complete.

    Returns a title and, when the kettle reports one, its MAC address for
    use as the config entry's unique ID.
    """
    client = StaggEKGClient(host=data[CONF_HOST])

    try:
        state = await hass.async_add_executor_job(client.get_state)
    except Exception as err:
        _LOGGER.error("Cannot connect to kettle: %s", err)
        raise CannotConnect from err

    problems = state_problems(state)
    if problems:
        # Warning level so it lands in the log without debug logging on;
        # the raw response is exactly what an issue report needs.
        _LOGGER.warning(
            "Kettle at %s answered but the response is not fully understood "
            "(%s). Parsed: mode=%s current=%s target=%s units=%s. Raw response: %r "
            "— please run examples/probe_kettle.py and report this output.",
            data[CONF_HOST],
            "; ".join(problems),
            state.mode,
            state.current_temp_c,
            state.target_temp_c,
            state.units,
            state.raw,
        )
        raise IncompleteResponse

    # Best-effort MAC for a stable unique ID (survives IP changes), and
    # firmware info so the default device name can be the actual model.
    mac = await hass.async_add_executor_job(client.get_mac)
    fw_info = await hass.async_add_executor_job(client.get_firmware_info)
    suggested_name = prettify_model_name(fw_info.get("project")) or "Fellow Kettle"

    return {"mac": mac, "suggested_name": suggested_name}


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
        except IncompleteResponse:
            errors["base"] = "incomplete_response"
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

        # The entry title becomes the device name and the entity-ID prefix:
        # the user's typed name wins, else the kettle's detected model.
        typed_name = (data.pop(CONF_NAME, "") or "").strip()
        title = typed_name or info["suggested_name"]

        return self.async_create_entry(title=title, data=data)

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask which network to scan, then run the scan.

        The kettle often lives on a different subnet or IoT VLAN than Home
        Assistant, where a scan of HA's own network can never find it — so
        the user chooses the network, prefilled with HA's detected subnets.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                network = parse_scan_network(user_input[CONF_NETWORK])
            except ValueError:
                errors["base"] = "invalid_network"
            else:
                self._discovered = await discover_kettles(self.hass, network)
                if self._discovered:
                    return await self.async_step_pick_device()
                errors["base"] = "no_kettles_found"

        default_network = ""
        if user_input is not None:
            default_network = user_input[CONF_NETWORK]
        else:
            defaults = await default_scan_networks(self.hass)
            if defaults:
                default_network = defaults[0]

        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {vol.Required(CONF_NETWORK, default=default_network): str}
            ),
            errors=errors,
        )

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user choose one of the kettles the scan found."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_TEMPERATURE_UNIT: user_input[CONF_TEMPERATURE_UNIT],
                CONF_NAME: user_input.get(CONF_NAME, ""),
            }
            result = await self._async_validate_and_create(data, errors)
            if result is not None:
                return result

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self._discovered[0]): vol.In(
                        {ip: ip for ip in self._discovered}
                    ),
                    vol.Required(
                        CONF_TEMPERATURE_UNIT, default=UNIT_CELSIUS
                    ): vol.In([UNIT_CELSIUS, UNIT_FAHRENHEIT]),
                    vol.Optional(CONF_NAME): str,
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
        errors: dict[str, str] = {}
        if user_input is not None:
            new_unit = user_input[CONF_TEMPERATURE_UNIT]
            current_unit = self._current(CONF_TEMPERATURE_UNIT, UNIT_CELSIUS)

            try:
                parse_preset_list(
                    user_input.get(CONF_PRESETS, ""),
                    fahrenheit=new_unit == UNIT_FAHRENHEIT,
                )
            except ValueError:
                errors["base"] = "invalid_presets"

            if not errors:
                # Only touch the physical kettle's display when the user
                # opted into unit syncing and actually changed the unit.
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
                        CONF_ACTIVE_POLL_INTERVAL,
                        default=self._current(
                            CONF_ACTIVE_POLL_INTERVAL, DEFAULT_ACTIVE_POLL_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_ACTIVE_POLL_INTERVAL, max=MAX_ACTIVE_POLL_INTERVAL
                        ),
                    ),
                    vol.Required(
                        CONF_SYNC_UNITS,
                        default=self._current(CONF_SYNC_UNITS, DEFAULT_SYNC_UNITS),
                    ): bool,
                    vol.Optional(
                        CONF_PRESETS,
                        default=self._current(CONF_PRESETS, DEFAULT_PRESETS),
                    ): str,
                    vol.Required(
                        CONF_SYNC_CLOCK,
                        default=self._current(CONF_SYNC_CLOCK, DEFAULT_SYNC_CLOCK),
                    ): bool,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class IncompleteResponse(HomeAssistantError):
    """The kettle answered, but the response couldn't be fully parsed."""
