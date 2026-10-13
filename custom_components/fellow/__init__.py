"""The Fellow Stagg EKG+ / EKG Pro integration."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo, format_mac
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_POLL_INTERVAL,
    CONF_SYNC_CLOCK,
    CONF_TEMP_SET_METHOD,
    DEFAULT_ACTIVE_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SYNC_CLOCK,
    DOMAIN,
    TEMP_METHOD_DIRECT,
)
from .eta import HeatingRateEstimator
from .kettle import KettleCliMutedError, KettleTransientError, StaggEKGClient
from .parser import is_water_ready

# After this many consecutive transient failures, give up holding the
# last known state and let HA mark the device unavailable. At the default
# 10s poll interval that's roughly a minute of staleness — long enough to
# absorb the "kettle just turned off" window, short enough that a truly
# offline kettle doesn't show stale data forever.
MAX_CONSECUTIVE_TRANSIENT_FAILURES = 6

# Lift-detection: once we observe the kettle leaving the base, treat it
# as "lifted" for at least this long, even if a brief docked reading
# appears (the kettle can flap as it's set back down).
LIFT_COOLDOWN_SECONDS = 90

# While the kettle is unreachable, stretch the poll interval instead of
# hammering it: the EKG's ESP32 HTTP server is known to wedge (device
# answers ping, port 80 times out), and stacking connect attempts against
# a struggling firmware can keep it pinned down. The first couple of
# failures get no backoff (they're usually the benign off-transition
# blip); after that the interval doubles per failure up to the cap.
FAILURE_BACKOFF_GRACE = 2
FAILURE_BACKOFF_CAP = timedelta(seconds=60)

# After this long continuously unreachable, raise a Repairs issue that
# names the known failure signature and the fix (power-cycle).
UNREACHABLE_REPAIR_AFTER = timedelta(minutes=5)
TROUBLESHOOTING_URL = (
    "https://github.com/RichardHerold/hass-fellow-ekg-pro#troubleshooting"
)

# Firmware 1.2.24+ answers every command with just the command form. A few
# such replies in a row prompt a look at the kettle's version page, which
# decides whether to raise the firmware Repairs card — a single odd reply
# never does.
MUTED_REPLIES_BEFORE_FIRMWARE_CHECK = 3
FIRMWARE_HELP_URL = (
    "https://github.com/RichardHerold/hass-fellow-ekg-pro"
    "#kettle-firmware-update-stopped-local-control"
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stagg EKG from a config entry."""
    host = entry.data["host"]
    # Options take precedence over the original entry data so changes from
    # the options flow apply without re-adding the integration.
    temp_method = entry.options.get(
        CONF_TEMP_SET_METHOD,
        entry.data.get(CONF_TEMP_SET_METHOD, TEMP_METHOD_DIRECT),
    )
    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    active_poll_interval = entry.options.get(
        CONF_ACTIVE_POLL_INTERVAL, DEFAULT_ACTIVE_POLL_INTERVAL
    )

    client = StaggEKGClient(host=host, temp_method=temp_method)

    # Best-effort device metadata; must never block or fail setup.
    fw_info = await hass.async_add_executor_job(client.get_firmware_info)
    firmware = await hass.async_add_executor_job(client.get_firmware_status)
    mac = await hass.async_add_executor_job(client.get_mac)

    coordinator = StaggEKGDataUpdateCoordinator(
        hass, client, entry.entry_id, poll_interval, active_poll_interval
    )
    coordinator.device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        connections={(dr.CONNECTION_NETWORK_MAC, format_mac(mac))} if mac else set(),
        name=entry.title or "Fellow Kettle",
        manufacturer="Fellow",
        model=fw_info.get("project") or "Stagg EKG (WiFi)",
        sw_version=fw_info.get("version")
        or (firmware.current_version if firmware else None),
        configuration_url=f"http://{host}",
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        # On firmware that mutes the CLI, setup retries forever, each time
        # with a fresh coordinator that would never see enough failed polls
        # to raise the Repairs card — so raise it from here.
        if isinstance(coordinator.last_failure, KettleCliMutedError):
            await coordinator.async_report_muted_firmware()
        raise

    # Positive confirmation in the log that the kettle was reached AND
    # understood — the counterpart of the config flow's strict validation.
    if coordinator.data and "state" in coordinator.data:
        state = coordinator.data["state"]
        _LOGGER.info(
            "Fellow kettle at %s is up: mode=%s current=%s°C target=%s°C "
            "firmware=%s mac=%s",
            host,
            state.mode,
            state.current_temp_c,
            state.target_temp_c,
            fw_info.get("version", "unknown"),
            mac or "unknown",
        )

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Optionally keep the kettle's display clock synced to HA time
    # (daily and on setup) — the kettle's clock drifts and forgets DST.
    if entry.options.get(CONF_SYNC_CLOCK, DEFAULT_SYNC_CLOCK):

        async def _async_sync_clock(_now=None) -> None:
            local = dt_util.now()
            try:
                await hass.async_add_executor_job(
                    client.set_clock, local.hour, local.minute, local.second
                )
                _LOGGER.debug("Synced kettle clock to %s", local.strftime("%H:%M:%S"))
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.warning("Failed to sync kettle clock: %s", err)

        await _async_sync_clock()
        entry.async_on_unload(
            async_track_time_interval(hass, _async_sync_clock, timedelta(hours=24))
        )

    # Reload when options change so settings like temp_set_method take
    # effect without an HA restart.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when the user changes options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class StaggEKGDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Stagg EKG data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: StaggEKGClient,
        entry_id: str,
        poll_interval: int,
        active_poll_interval: int,
    ) -> None:
        """Initialize."""
        self.client = client
        self.entry_id = entry_id
        self.device_info: DeviceInfo | None = None
        self.water_ready: bool = False
        self.minutes_to_ready: float | None = None
        self._eta = HeatingRateEstimator()
        self._idle_interval = timedelta(seconds=poll_interval)
        self._active_interval = timedelta(seconds=active_poll_interval)
        self._consecutive_transient_failures = 0
        self._failure_streak = 0
        self._unreachable_since = None
        self._repair_created = False
        self.last_failure: Exception | None = None
        self._muted_replies = 0
        self._firmware_checked = False
        self._firmware_reported = False
        # A firmware card from an earlier setup attempt may still be open
        # (setup retries build a fresh coordinator); the first success
        # clears it.
        self._firmware_issue_may_exist = True
        self._was_docked: bool | None = None
        self._lifted_at = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._idle_interval,
        )

    @property
    def recently_lifted(self) -> bool:
        """Whether the kettle was lifted off the base in the recent past.

        Edge-triggered on docked → undocked, with a cooldown window so a
        single flapping reading after re-docking doesn't immediately clear
        the signal.
        """
        if self._lifted_at is None:
            return False
        return (
            dt_util.utcnow() - self._lifted_at
        ).total_seconds() < LIFT_COOLDOWN_SECONDS

    def _note_failure(self, err: Exception) -> None:
        """Track an unreachable kettle: back off polling, raise a Repair.

        Called on every failed poll. Backoff gives a half-wedged firmware
        room to recover instead of pinning it down with connect attempts;
        the Repairs issue turns a silent 'unavailable' into a guided fix
        for the known ESP32 web-server wedge (ping answers, port 80 dead
        → power-cycle the kettle).
        """
        self.last_failure = err
        self._failure_streak += 1
        now = dt_util.utcnow()
        if self._unreachable_since is None:
            self._unreachable_since = now

        factor = 2 ** min(max(self._failure_streak - FAILURE_BACKOFF_GRACE, 0), 3)
        backoff = min(FAILURE_BACKOFF_CAP, self._idle_interval * factor)
        # update_interval is set by the DataUpdateCoordinator base class;
        # pylint can't see that and flags the read.
        # pylint: disable-next=access-member-before-definition
        current = self.update_interval
        if current != backoff:
            _LOGGER.debug(
                "Kettle unreachable (failure %d); polling every %ss until it answers",
                self._failure_streak,
                backoff.total_seconds(),
            )
            self.update_interval = backoff

        if (
            not self._repair_created
            and not self._firmware_reported
            and now - self._unreachable_since >= UNREACHABLE_REPAIR_AFTER
        ):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"kettle_unreachable_{self.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="kettle_unreachable",
                translation_placeholders={"host": self.client.host},
                learn_more_url=TROUBLESHOOTING_URL,
            )
            self._repair_created = True

    def _note_success(self) -> None:
        """Clear the failure streak and any open Repairs issue."""
        self._failure_streak = 0
        self._unreachable_since = None
        self.last_failure = None
        self._muted_replies = 0
        self._firmware_checked = False
        self._firmware_reported = False
        if self._repair_created:
            ir.async_delete_issue(
                self.hass, DOMAIN, f"kettle_unreachable_{self.entry_id}"
            )
            self._repair_created = False
        if self._firmware_issue_may_exist:
            ir.async_delete_issue(self.hass, DOMAIN, self._firmware_issue_id)
            self._firmware_issue_may_exist = False

    @property
    def _firmware_issue_id(self) -> str:
        return f"firmware_cli_muted_{self.entry_id}"

    async def async_report_muted_firmware(self) -> None:
        """Raise the firmware Repairs card if the version page confirms it.

        Called once muted replies persist. The version page decides: only
        firmware known to mute the CLI gets the card — with switch-back
        steps naming the right slot when older firmware is still on the
        kettle. Anything else is left to the generic unreachable card.
        """
        self._firmware_checked = True
        firmware = await self.hass.async_add_executor_job(
            self.client.get_firmware_status
        )
        if firmware is None or not firmware.cli_muted:
            _LOGGER.debug(
                "Kettle replies carry no output, but its version page doesn't "
                "show CLI-muting firmware (%s)",
                firmware.current_version if firmware else "page unavailable",
            )
            return

        spare = firmware.rollback_slot()
        placeholders = {"host": self.client.host, "version": firmware.current_version}
        if spare is not None:
            translation_key = "firmware_cli_muted"
            placeholders["spare_slot"] = spare.name
            placeholders["spare_version"] = spare.version
        else:
            translation_key = "firmware_cli_muted_no_rollback"

        already_open = (
            ir.async_get(self.hass).async_get_issue(DOMAIN, self._firmware_issue_id)
            is not None
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._firmware_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=translation_key,
            translation_placeholders=placeholders,
            learn_more_url=FIRMWARE_HELP_URL,
        )
        self._firmware_reported = True
        self._firmware_issue_may_exist = True
        if self._repair_created:
            ir.async_delete_issue(
                self.hass, DOMAIN, f"kettle_unreachable_{self.entry_id}"
            )
            self._repair_created = False

        if not already_open:
            _LOGGER.warning(
                "Kettle at %s is running firmware %s, which no longer returns "
                "output from its local command interface, so Home Assistant "
                "can't read or control it. %s See Settings → Repairs.",
                self.client.host,
                firmware.current_version,
                f"Its spare slot {spare.name} still holds {spare.version}."
                if spare
                else "No older firmware was found in its spare slot.",
            )

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            state = await self.hass.async_add_executor_job(self.client.get_state)
        except KettleTransientError as err:
            # The kettle stops answering HTTP (or returns truncated data)
            # for a few seconds when it transitions to Off. Hold the last
            # known state for a while instead of surfacing an error every
            # time that happens — but give up after enough consecutive
            # failures so HA can mark the device unavailable if it really
            # is offline.
            self._note_failure(err)
            if isinstance(err, KettleCliMutedError):
                self._muted_replies += 1
                if (
                    self._muted_replies >= MUTED_REPLIES_BEFORE_FIRMWARE_CHECK
                    and not self._firmware_checked
                ):
                    await self.async_report_muted_firmware()
            else:
                self._muted_replies = 0
            self._consecutive_transient_failures += 1
            if (
                self.data is not None
                and self._consecutive_transient_failures
                <= MAX_CONSECUTIVE_TRANSIENT_FAILURES
            ):
                _LOGGER.debug(
                    "Kettle transient failure %d/%d, keeping last state: %s",
                    self._consecutive_transient_failures,
                    MAX_CONSECUTIVE_TRANSIENT_FAILURES,
                    err,
                )
                return self.data
            raise UpdateFailed(f"Kettle unresponsive: {err}") from err
        except Exception as err:
            self._note_failure(err)
            self._muted_replies = 0
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        self._consecutive_transient_failures = 0
        self._note_success()

        # Track docked → undocked transition for lift detection. Only a
        # response that actually carried a temperature field counts — a
        # truncated response without one is a parse anomaly, not a lift.
        if state.temp_field_present:
            if self._was_docked and not state.is_docked:
                self._lifted_at = dt_util.utcnow()
            self._was_docked = state.is_docked

        self.water_ready = is_water_ready(state)

        # Time-to-ready estimate: feed the heating-rate estimator while a
        # heat cycle runs; anything else invalidates the curve.
        if state.is_heating and state.current_temp_c is not None:
            self._eta.add_sample(time.monotonic(), state.current_temp_c)
            self.minutes_to_ready = self._eta.minutes_to(state.target_temp_c)
        else:
            self._eta.reset()
            self.minutes_to_ready = None

        # Adaptive polling: track a live heat/hold cycle closely so the
        # climbing temperature and Water Ready stay fresh, then relax to
        # the idle interval when the kettle is off. The coordinator never
        # overlaps refreshes, so a stalling kettle just stretches a cycle
        # rather than piling up requests.
        wanted = (
            self._active_interval
            if (state.is_heating or state.is_holding)
            else self._idle_interval
        )
        # update_interval is set by the DataUpdateCoordinator base class;
        # pylint can't see that and flags the read.
        if self.update_interval != wanted:  # pylint: disable=access-member-before-definition
            _LOGGER.debug(
                "Switching poll interval to %ss (%s)",
                wanted.total_seconds(),
                "active" if wanted == self._active_interval else "idle",
            )
            self.update_interval = wanted

        return {"state": state}
