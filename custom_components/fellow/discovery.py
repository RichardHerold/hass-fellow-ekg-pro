"""LAN discovery for Fellow Stagg EKG kettles.

Scans a caller-chosen IPv4 network for HTTP services that answer the
kettle's `state` CLI command. The network to scan is supplied by the user
in the config flow (prefilled with Home Assistant's own detected subnets),
because the kettle frequently lives on a different subnet or IoT VLAN than
Home Assistant — a scan of HA's own /24 can never find it there.

Home Assistant and aiohttp are imported lazily inside the functions that
need them so the pure helpers in this module stay unit-testable without a
Home Assistant installation.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from ipaddress import IPv4Network, ip_address, ip_network
from typing import TYPE_CHECKING, Optional

from .parser import parse_state

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 3.0
PROBE_CONCURRENCY = 30

# Largest network we're willing to sweep: /22 = 1022 hosts. Prevents an
# accidental "10.0.0.0/8" from launching a 16-million-host scan.
MIN_PREFIX_LEN = 22


def parse_scan_network(value: str) -> IPv4Network:
    """Parse the user's scan-network input.

    Accepts a CIDR ("192.168.20.0/24", host bits tolerated) or a bare IP
    ("192.168.20.55", treated as its /24). Raises ValueError for anything
    unusable: garbage, IPv6, loopback/link-local/multicast networks, or a
    network larger than /22.
    """
    value = value.strip()
    if not value:
        raise ValueError("empty network")

    if "/" in value:
        network = ip_network(value, strict=False)
    else:
        # Bare IP: scan the /24 it lives in.
        address = ip_address(value)
        network = ip_network(f"{address}/24", strict=False)

    if network.version != 4:
        raise ValueError(f"not an IPv4 network: {value}")
    if network.prefixlen < MIN_PREFIX_LEN:
        raise ValueError(
            f"network too large to scan ({network}); use /{MIN_PREFIX_LEN} or smaller"
        )
    if (
        network.is_loopback
        or network.is_link_local
        or network.is_multicast
        or network.is_reserved
    ):
        raise ValueError(f"not a scannable network: {network}")
    return network


def looks_like_kettle(text: str) -> bool:
    """Whether an HTTP response body looks like a kettle's `state` output.

    Uses the same parser the integration runs on, and requires a
    temperature field, so discovery only offers kettles that setup
    validation would accept.
    """
    if "mode=" not in text:
        return False
    try:
        state = parse_state(text)
    except Exception:
        return False
    return state.temp_field_present


async def default_scan_networks(hass: "HomeAssistant") -> list[str]:
    """HA's own IPv4 subnets, as CIDR strings, for prefilling the scan form.

    Uses the Home Assistant network helper (real adapter enumeration —
    works on HAOS/containers where guessing via a UDP socket picks the
    wrong interface), falling back to the UDP-socket trick if the helper
    yields nothing.
    """
    networks: list[str] = []
    try:
        from homeassistant.components import network as ha_network

        adapters = await ha_network.async_get_adapters(hass)
        for adapter in adapters:
            if not adapter.get("enabled"):
                continue
            for ipv4 in adapter.get("ipv4", []):
                try:
                    net = ip_network(
                        f"{ipv4['address']}/{ipv4['network_prefix']}", strict=False
                    )
                except (KeyError, ValueError):
                    continue
                if net.is_loopback or net.is_link_local:
                    continue
                # Clamp very wide adapter networks to something scannable.
                if net.prefixlen < MIN_PREFIX_LEN:
                    net = ip_network(
                        f"{ipv4['address']}/{MIN_PREFIX_LEN}", strict=False
                    )
                cidr = str(net)
                if cidr not in networks:
                    networks.append(cidr)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Network helper unavailable: %s", err)

    if not networks:
        local_ip = await hass.async_add_executor_job(_get_local_ip)
        if local_ip:
            networks.append(str(ip_network(f"{local_ip}/24", strict=False)))

    _LOGGER.debug("Default scan networks: %s", networks)
    return networks


async def discover_kettles(
    hass: "HomeAssistant", network: IPv4Network
) -> list[str]:
    """Return IPs on `network` that answer like Stagg EKG kettles."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    candidates = [str(ip) for ip in network.hosts()]
    _LOGGER.debug("Discovery: scanning %d hosts in %s", len(candidates), network)

    session = async_get_clientsession(hass)
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)
    results = await asyncio.gather(
        *(_probe(session, semaphore, ip) for ip in candidates)
    )
    found = [ip for ip in results if ip is not None]
    if found:
        _LOGGER.info("Discovery: found %d kettle(s) in %s: %s", len(found), network, found)
    else:
        _LOGGER.info("Discovery: no kettles answered in %s", network)
    return found


async def _probe(
    session: "aiohttp.ClientSession",
    semaphore: asyncio.Semaphore,
    ip: str,
) -> Optional[str]:
    """Return ip if it answers like a Stagg EKG kettle, else None."""
    import aiohttp

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

    return ip if looks_like_kettle(text) else None


def _get_local_ip() -> Optional[str]:
    """Return this host's primary outbound IPv4 address.

    Opens a UDP socket toward a public address to let the kernel pick the
    interface it would route through, then reads the bound address. No
    packets are actually sent. Fallback only — the HA network helper is
    the primary source of scan networks.
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
