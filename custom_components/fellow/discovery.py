"""LAN discovery for Stagg EKG+ kettles.

Scans the HA host's local /24 for HTTP services that respond to the
kettle's `state` CLI command. We probe `/cli?cmd=state` and require the
response to contain both `mode=` and `tempr=` so we don't false-positive
on unrelated devices that happen to have port 80 open.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from ipaddress import IPv4Network
from typing import Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 1.5
PROBE_CONCURRENCY = 30


async def discover_kettles(hass: HomeAssistant) -> list[str]:
    """Return a list of IPs on the local /24 that look like Stagg EKG+ kettles."""
    local_ip = await hass.async_add_executor_job(_get_local_ip)
    if local_ip is None:
        _LOGGER.debug("Discovery: could not determine local IP, skipping scan")
        return []

    network = IPv4Network(f"{local_ip}/24", strict=False)
    candidates = [str(ip) for ip in network.hosts() if str(ip) != local_ip]
    _LOGGER.debug("Discovery: scanning %d hosts in %s", len(candidates), network)

    session = async_get_clientsession(hass)
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)
    results = await asyncio.gather(
        *(_probe(session, semaphore, ip) for ip in candidates)
    )
    found = [ip for ip in results if ip is not None]
    _LOGGER.debug("Discovery: found %d kettle(s): %s", len(found), found)
    return found


async def _probe(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    ip: str,
) -> Optional[str]:
    """Return ip if it answers like a Stagg EKG+, else None."""
    async with semaphore:
        try:
            async with session.get(
                f"http://{ip}/cli",
                params={"cmd": "state"},
                timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return None

    if "mode=" in text and "tempr=" in text:
        return ip
    return None


def _get_local_ip() -> Optional[str]:
    """Return this host's primary outbound IPv4 address.

    Opens a UDP socket toward a public address to let the kernel pick the
    interface it would route through, then reads the bound address. No
    packets are actually sent.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return None
