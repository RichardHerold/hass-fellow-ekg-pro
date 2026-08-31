"""Update platform: notify when a new integration version is released.

Checks the GitHub releases feed twice a day and exposes a standard Home
Assistant update entity — visible in Settings → Updates and usable as a
notification-automation trigger. It links to the release; installing the
update still happens through HACS (or a manual copy), since an integration
can't safely overwrite itself while running.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.loader import async_get_integration

from . import StaggEKGDataUpdateCoordinator
from .const import DOMAIN, GITHUB_REPO
from .updates import parse_latest_release

_LOGGER = logging.getLogger(__name__)

# Unauthenticated GitHub API is rate-limited per IP (60/hr, shared with
# everything else on the network) — twice a day is plenty for releases.
SCAN_INTERVAL = timedelta(hours=12)

RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the integration-update entity."""
    coordinator: StaggEKGDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    integration = await async_get_integration(hass, DOMAIN)

    async_add_entities(
        [StaggEKGIntegrationUpdate(coordinator, entry, integration.version)],
        update_before_add=True,
    )


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
        self._attr_release_summary = summary or None
        self._release_notes = (data.get("body") or "").strip() or None

    async def async_release_notes(self) -> str | None:
        """Full release notes for the Settings → Updates dialog."""
        return self._release_notes
