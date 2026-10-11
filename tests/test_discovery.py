"""Tests for the pure helpers in discovery.py (no HA, no network)."""
# pylint: disable=missing-class-docstring


import importlib
import sys
import types
from ipaddress import IPv4Network
from pathlib import Path

import pytest

# Import under a synthetic package so relative imports resolve without
# executing custom_components/fellow/__init__.py (which needs Home
# Assistant). HA/aiohttp imports in discovery.py are lazy for this reason.
_PKG_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "fellow"
)
_pkg = types.ModuleType("fellow_pkg")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules.setdefault("fellow_pkg", _pkg)
discovery = importlib.import_module("fellow_pkg.discovery")

parse_scan_network = discovery.parse_scan_network
looks_like_kettle = discovery.looks_like_kettle


class TestParseScanNetwork:
    def test_cidr(self):
        assert parse_scan_network("192.168.20.0/24") == IPv4Network("192.168.20.0/24")

    def test_cidr_with_host_bits(self):
        assert parse_scan_network("192.168.20.55/24") == IPv4Network("192.168.20.0/24")

    def test_bare_ip_becomes_slash_24(self):
        assert parse_scan_network("192.168.20.55") == IPv4Network("192.168.20.0/24")

    def test_whitespace_tolerated(self):
        assert parse_scan_network("  10.1.1.0/24 ") == IPv4Network("10.1.1.0/24")

    def test_slash_22_allowed(self):
        assert parse_scan_network("10.1.0.0/22") == IPv4Network("10.1.0.0/22")

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "garbage",
            "10.0.0.0/8",  # too large to scan
            "192.168.1.0/16",  # too large to scan
            "fe80::1/64",  # IPv6
            "127.0.0.1",  # loopback
            "169.254.1.1",  # link-local
            "224.0.0.0/24",  # multicast
        ],
    )
    def test_rejected(self, value):
        with pytest.raises(ValueError):
            parse_scan_network(value)


class TestLooksLikeKettle:
    def test_kettle_state_accepted(self):
        assert looks_like_kettle("mode=S_Off\ntempr=21.0 C\ntemprT=95.0 C\nunits=1\n")

    def test_pro_shape_accepted(self):
        assert looks_like_kettle("mode=S_Heat\ntempr=185.0\ntemprT=203.0\nunits=0\n")

    def test_random_webserver_rejected(self):
        assert not looks_like_kettle("<html><body>router admin</body></html>")

    def test_mode_without_temperature_rejected(self):
        # Some other device echoing "mode=" must not be offered as a kettle.
        assert not looks_like_kettle("mode=bridge\nuptime=42\n")
