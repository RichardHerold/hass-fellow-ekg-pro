"""Tests for the kettle client's command safety guard and control paths.

No network involved: the forbidden-command check runs before any HTTP call,
and the control-path tests stub the transport.
"""
# pylint: disable=redefined-outer-name, protected-access


import importlib
import sys
import types
from pathlib import Path

import pytest

# Import kettle.py under a synthetic package so its relative imports work
# without executing custom_components/fellow/__init__.py (which needs Home
# Assistant installed).
_PKG_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "fellow"
)
_pkg = types.ModuleType("fellow_pkg")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules.setdefault("fellow_pkg", _pkg)
kettle = importlib.import_module("fellow_pkg.kettle")


@pytest.fixture
def client():
    return kettle.StaggEKGClient(host="192.0.2.1")


@pytest.mark.parametrize("cmd", ["ss", "adcsamples", "reset", "  ss  "])
def test_forbidden_commands_rejected(client, cmd):
    with pytest.raises(ValueError):
        client._send_command(cmd)


def test_state_machine_commands_have_arguments():
    # The safe commands all carry an argument — a bare "ss" must never
    # appear in the vocabulary.
    for cmd in (kettle.CMD_HEAT, kettle.CMD_HOLD, kettle.CMD_OFF):
        assert cmd.startswith("ss ") and len(cmd.split()) == 2


def test_get_raw_rejects_write_commands(client):
    with pytest.raises(ValueError):
        client.get_raw("ss S_Heat")


def test_identify_sends_fixed_safe_chirp(monkeypatch):
    client = kettle.StaggEKGClient(host="192.0.2.1")
    sent = []
    monkeypatch.setattr(
        client, "_send_command", lambda cmd, **kw: sent.append(cmd) or "ok"
    )
    client.identify()
    assert sent == ["buz 1000 4000 200"]


def test_direct_target_command_format():
    cmd = kettle.CMD_SET_TARGET_DIRECT.format(temp_f=203.0)
    assert cmd == "setsettingd settempr 203.0"
    legacy = kettle.CMD_SET_TARGET_LEGACY.format(temp_f=203)
    assert legacy == "setsetting settempr 203"


class TestCommandFirstControl:
    """Control actions must not die on a failed state read.

    The kettle's HTTP server stalls past the read timeout while heating —
    exactly when the user hits 'turn off' — so a timed-out 'state' read
    must never block sending the actual command.
    """

    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        monkeypatch.setattr(kettle.time, "sleep", lambda _s: None)

    @pytest.fixture
    def busy_client(self, monkeypatch):
        """Client whose 'state' reads time out but whose commands succeed."""
        client = kettle.StaggEKGClient(host="192.0.2.1")
        client.sent = []

        def fake_send(cmd, retries=1, timeout=5.0):
            if cmd == kettle.CMD_STATE:
                raise kettle.KettleTimeoutError("busy heating")
            client.sent.append(cmd)
            return "ok"

        monkeypatch.setattr(client, "_send_command", fake_send)
        return client

    def test_stop_heating_sends_off_despite_unreadable_state(self, busy_client):
        assert busy_client.stop_heating() == "stopped"
        assert kettle.CMD_OFF in busy_client.sent

    def test_start_heating_sends_heat_despite_unreadable_state(self, busy_client):
        assert busy_client.start_heating() == "ok"
        assert busy_client.sent == [kettle.CMD_HEAT]

    def test_start_hold_sends_hold_despite_unreadable_state(self, busy_client):
        assert busy_client.start_hold() == "ok"
        assert busy_client.sent == [kettle.CMD_HOLD]

    def test_stop_heating_raises_when_kettle_fully_unreachable(self, monkeypatch):
        client = kettle.StaggEKGClient(host="192.0.2.1")

        def always_timeout(cmd, retries=1, timeout=5.0):
            raise kettle.KettleTimeoutError("unreachable")

        monkeypatch.setattr(client, "_send_command", always_timeout)
        with pytest.raises(kettle.KettleTransientError):
            client.stop_heating()

    def test_stop_heating_skips_send_when_verifiably_off(self, monkeypatch):
        client = kettle.StaggEKGClient(host="192.0.2.1")
        client.sent = []

        def fake_send(cmd, retries=1, timeout=5.0):
            if cmd == kettle.CMD_STATE:
                return "mode=S_Off\ntempr=21.0 C\ntemprT=95.0 C\nunits=1\n"
            client.sent.append(cmd)
            return "ok"

        monkeypatch.setattr(client, "_send_command", fake_send)
        assert client.stop_heating() == "stopped"
        assert client.sent == []
