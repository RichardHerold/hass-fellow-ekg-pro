"""Parsing for GitHub release data used by the update entity.

Pure Python (no Home Assistant imports) so it's unit-testable standalone.
"""
from __future__ import annotations

from typing import Optional

# Home Assistant truncates release_summary at 255 characters.
SUMMARY_LIMIT = 255


def parse_latest_release(data: dict) -> Optional[tuple[str, str, str]]:
    """Extract (version, release_url, summary) from GitHub release JSON.

    Returns None for drafts, prereleases, or data without a usable tag.
    The version has any leading 'v' stripped so it compares cleanly with
    the manifest version.
    """
    if not isinstance(data, dict):
        return None
    if data.get("draft") or data.get("prerelease"):
        return None

    tag = data.get("tag_name")
    if not tag or not isinstance(tag, str):
        return None
    version = tag.lstrip("vV").strip()
    if not version:
        return None

    release_url = data.get("html_url") or ""
    body = data.get("body") or ""
    summary = body.strip()
    if len(summary) > SUMMARY_LIMIT:
        summary = summary[: SUMMARY_LIMIT - 1] + "…"

    return version, release_url, summary
