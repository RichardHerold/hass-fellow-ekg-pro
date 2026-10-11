"""Tests for GitHub release parsing used by the update entity."""

import importlib
import sys
import types
from pathlib import Path

_PKG_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "fellow"
)
_pkg = types.ModuleType("fellow_pkg")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules.setdefault("fellow_pkg", _pkg)
updates = importlib.import_module("fellow_pkg.updates")

parse_latest_release = updates.parse_latest_release


def test_v_prefix_stripped():
    result = parse_latest_release(
        {"tag_name": "v1.5.0", "html_url": "https://x/r/v1.5.0", "body": "notes"}
    )
    assert result == ("1.5.0", "https://x/r/v1.5.0", "notes")


def test_bare_tag_accepted():
    version, _, _ = parse_latest_release({"tag_name": "1.5.0"})
    assert version == "1.5.0"


def test_prerelease_rejected():
    assert parse_latest_release({"tag_name": "v2.0.0b1", "prerelease": True}) is None


def test_draft_rejected():
    assert parse_latest_release({"tag_name": "v2.0.0", "draft": True}) is None


def test_missing_tag_rejected():
    assert parse_latest_release({}) is None
    assert parse_latest_release({"tag_name": None}) is None
    assert parse_latest_release({"tag_name": "v"}) is None


def test_missing_body_gives_empty_summary():
    _, _, summary = parse_latest_release({"tag_name": "v1.0.0", "body": None})
    assert summary == ""


def test_long_body_truncated():
    _, _, summary = parse_latest_release(
        {"tag_name": "v1.0.0", "body": "x" * 500}
    )
    assert len(summary) == updates.SUMMARY_LIMIT
    assert summary.endswith("…")


def test_non_dict_rejected():
    assert parse_latest_release(None) is None
    assert parse_latest_release([1, 2]) is None
