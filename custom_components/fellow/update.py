"""Update platform: notify when a new integration version is released.

Checks the GitHub releases feed twice a day and exposes a standard Home
Assistant update entity — visible in Settings → Updates and usable as a
notification-automation trigger. It links to the release; installing the
update still happens through HACS (or a manual copy), since an integration
can't safely overwrite itself while running.

When HACS is installed this entity is not created at all: HACS tracks the
repository itself and shows an update entity with a working Install button,
so the announce-only card would only duplicate it (and read as broken when
tapped). Anyone running a manual copy alongside HACS can add this repo to
HACS as a custom repository to get the installable card instead.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.start import async_at_started
from homeassistant.loader import async_get_integration

from . import StaggEKGDataUpdateCoordinator
from .const import DOMAIN, GITHUB_REPO
from .updates import parse_latest_release

_LOGGER = logging.getLogger(__name__)

# Unauthenticated GitHub API is rate-limited per IP (60/hr, shared with
# everything else on the network) — twice a day is plenty for releases.
SCAN_INTERVAL = timedelta(hours=12)

RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


# This entity announces updates; it cannot install them (an integration
# can't safely overwrite its own files while running). Say so wherever
# the update dialog shows text, or the card reads as broken.
INSTALL_HINT = (
    "⬆️ Install via HACS (HACS → Fellow → Update), then restart Home "
    "Assistant — this card only announces releases and cannot install them."
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the integration-update entity — on non-HACS installs only.

    HACS may not have loaded yet while Home Assistant is still starting
    (config entries set up in parallel), so the HACS check is deferred
    until startup has finished; on a plain reload it runs immediately.
    """
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version

    @callback
    def _add_unless_hacs(_hass: HomeAssistant) -> None:
        if "hacs" in hass.config.components:
            # Drop the entity a pre-HACS-aware version registered, so it
            # doesn't linger as an orphan next to HACS's installable one.
            registry = er.async_get(hass)
            stale = registry.async_get_entity_id(
                "update", DOMAIN, f"{entry.entry_id}_integration_update"
            )
            if stale:
                registry.async_remove(stale)
            _LOGGER.debug(
                "HACS is installed; leaving release announcements to its "
                "installable update entity"
            )
            return
        async_add_entities(
            [StaggEKGIntegrationUpdate(coordinator, entry, version)],
            update_before_add=True,
        )

    entry.async_on_unload(async_at_started(hass, _add_unless_hacs))


class StaggEKGIntegrationUpdate(UpdateEntity):
    """Tracks the latest published release of this integration on GitHub."""

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES
    _attr_title = "Fellow Stagg EKG integration"

    def __init__(
        self,
        coordinator: StaggEKGDataUpdateCoordinator,
        entry: ConfigEntry,
        installed_version: str | None,
    ) -> None:
        """Initialize the update entity."""
        self._attr_unique_id = f"{entry.entry_id}_integration_update"
        self._attr_name = "Integration Update"
        self._attr_device_info = coordinator.device_info
        self._attr_installed_version = str(installed_version) if installed_version else None
        self._release_notes: str | None = None

    async def async_update(self) -> None:
        """Check GitHub for the latest published release.

        Failures (network, rate limit, no releases yet) keep the previous
        values — an update check must never make the kettle look broken.
        """
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                RELEASES_URL,
                headers={"Accept": "application/vnd.github+json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Release check returned HTTP %s; keeping previous state",
                        resp.status,
                    )
                    return
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Release check failed: %s", err)
            return

        parsed = parse_latest_release(data)
        if parsed is None:
            _LOGGER.debug("No usable published release found")
            return

        version, release_url, summary = parsed
        self._attr_latest_version = version
        self._attr_release_url = release_url or None
        # release_summary is capped at 255 chars by HA — the hint alone
        # fits and is the one thing the card must say; the dialog's full
        # release notes carry the hint plus the actual notes.
        self._attr_release_summary = INSTALL_HINT
        body = (data.get("body") or "").strip() or summary
        self._release_notes = f"{INSTALL_HINT}\n\n---\n\n{body}" if body else INSTALL_HINT

    async def async_release_notes(self) -> str | None:
        """Full release notes for the Settings → Updates dialog."""
        return self._release_notes
