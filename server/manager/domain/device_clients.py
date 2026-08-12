"""Minimal client and network audit metadata for approved devices.

The Module deliberately does not retain a raw User-Agent, browser fingerprint,
MAC address, IMEI, or location. It reduces request metadata to a coarse client
kind/name and validates the source IP observed by the Manager.
"""

from __future__ import annotations

import ipaddress
import re


_CLIENT_HINT_RE = re.compile(r"^[a-z0-9._-]{1,32}$")
_CLIENT_PATTERNS = (
    (re.compile(r"(?:Edg|EdgiOS|EdgA)/([0-9.]+)"), "Microsoft Edge"),
    (re.compile(r"(?:Chrome|CriOS)/([0-9.]+)"), "Google Chrome"),
    (re.compile(r"(?:Firefox|FxiOS)/([0-9.]+)"), "Mozilla Firefox"),
    (re.compile(r"Version/([0-9.]+).*Safari/"), "Apple Safari"),
)


def observed_ip(value: object) -> str:
    """Return one canonical IPv4/IPv6 address or an empty value."""
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ""


def describe_client(
    *,
    user_agent: object,
    client_hint: object = "",
) -> dict[str, str]:
    """Reduce request headers to non-fingerprinting client audit metadata."""
    agent = str(user_agent or "").strip()[:512]
    hint = str(client_hint or "").strip().lower()
    if not _CLIENT_HINT_RE.fullmatch(hint):
        hint = ""

    native = re.search(r"FactorTester-Swift/([0-9.]+)", agent)
    if hint == "swift" or native:
        version = native.group(1) if native else ""
        return {
            "client_type": "swift",
            "client_name": f"FactorTester Swift {version}".strip(),
        }

    for pattern, label in _CLIENT_PATTERNS:
        match = pattern.search(agent)
        if match:
            return {
                "client_type": "browser",
                "client_name": f"{label} {match.group(1)}"[:128],
            }

    if "Safari/" in agent:
        return {"client_type": "browser", "client_name": "Apple Safari"}
    if "Mozilla/" in agent:
        return {"client_type": "browser", "client_name": "Web Browser"}
    if hint:
        return {"client_type": hint, "client_name": hint}
    return {"client_type": "unknown", "client_name": "Unknown Client"}


def normalise_client_metadata(value: object) -> dict[str, str]:
    """Validate persisted client metadata from PostgreSQL/JSON adapters."""
    source = value if isinstance(value, dict) else {}
    client_type = str(source.get("client_type") or "unknown").strip().lower()
    if not _CLIENT_HINT_RE.fullmatch(client_type):
        client_type = "unknown"
    return {
        "client_type": client_type,
        "client_name": str(source.get("client_name") or "").strip()[:128],
        "enrollment_ip": observed_ip(source.get("enrollment_ip")),
        "last_seen_ip": observed_ip(source.get("last_seen_ip")),
    }
