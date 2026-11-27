"""Helpers for normalizing persisted registration browser profiles."""

from __future__ import annotations

import json
import re
from typing import Any


def normalize_registration_browser_profile(
    fingerprint_json: str | dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Return a stable display name and Chrome version from a fingerprint."""
    if not fingerprint_json:
        return None, None

    try:
        fingerprint = (
            json.loads(fingerprint_json)
            if isinstance(fingerprint_json, str)
            else fingerprint_json
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, None

    if not isinstance(fingerprint, dict):
        return None, None

    profile = fingerprint.get("profile_name") or fingerprint.get("archetype_name")
    version = fingerprint.get("chrome_version")
    user_agent = str(fingerprint.get("user_agent") or "")
    impersonate = str(fingerprint.get("impersonate") or "")

    if not version:
        match = re.search(r"Chrome/(\d+(?:\.\d+){0,3})", user_agent)
        if match:
            version = match.group(1)
        else:
            match = re.search(r"chrome(\d+)", impersonate, re.IGNORECASE)
            if match:
                version = f"{match.group(1)}.0.0.0"

    if not profile and version:
        major = str(version).split(".", 1)[0]
        if "Macintosh" in user_agent or "macos" in impersonate.lower():
            platform = "macOS"
        elif "Windows" in user_agent:
            platform = "Windows"
        elif "Linux" in user_agent:
            platform = "Linux"
        else:
            platform = "Unknown"
        profile = f"Chrome-{major}-{platform}"

    return str(profile) if profile else None, str(version) if version else None
