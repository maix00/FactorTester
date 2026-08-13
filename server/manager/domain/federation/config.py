"""Owner-only federation settings and peer endpoint validation."""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import threading
from pathlib import Path
from urllib.parse import urlparse

from server.manager.config import PEER_CONTROL_PORT

FEDERATION_CONFIG_SCHEMA_VERSION = 1

def _port_selection(value: object) -> list[int]:
    """Normalise the local ports explicitly advertised to a peer Manager."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("ports must be a list")
    result: list[int] = []
    for item in value:
        try:
            port = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("ports must contain integers") from exc
        if not 1 <= port <= 65535:
            raise ValueError("ports must be integers from 1 to 65535")
        if port not in result:
            result.append(port)
    return sorted(result)


def _url(value: object, *, field: str, required: bool = False) -> str:
    result = str(value or "").strip().rstrip("/")
    if not result:
        if required:
            raise ValueError(f"{field} is required")
        return ""
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an http or https URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} must not include credentials")
    return result


def _peer_registration_url(value: object) -> str:
    result = _url(value, field="register_url")
    if not result:
        return ""
    parsed = urlparse(result)
    try:
        port = parsed.port
        address = ipaddress.ip_address(parsed.hostname or "")
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "register_url must use a private WireGuard IP on port 17998"
        ) from exc
    if (
        parsed.scheme != "http"
        or port != PEER_CONTROL_PORT
        or not address.is_private
        or address.is_loopback
        or address.is_unspecified
        or address.is_multicast
        or parsed.path != "/api/federation/register"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "register_url must use a private WireGuard IP on port 17998"
        )
    return result


_FEDERATION_CONFIG_DEFAULTS: dict[str, object] = {
    "schema_version": FEDERATION_CONFIG_SCHEMA_VERSION,
    "enabled": False,
    "register_url": "",
    "public_endpoint": "",
    "registration_token": "",
    "ports": [],
    "interval": 10.0,
}


def _normalise_federation_config(
    payload: dict[str, object] | None = None,
    *,
    base: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        **_FEDERATION_CONFIG_DEFAULTS,
        **(base or {}),
        **(payload or {}),
    }
    try:
        interval = float(value.get("interval") or 10.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("interval must be a number") from exc
    return {
        "schema_version": FEDERATION_CONFIG_SCHEMA_VERSION,
        "enabled": bool(value.get("enabled", False)),
        "register_url": _peer_registration_url(value.get("register_url")),
        "public_endpoint": _url(
            value.get("public_endpoint"), field="public_endpoint",
        ),
        "registration_token": str(value.get("registration_token") or "").strip(),
        "ports": _port_selection(value.get("ports")),
        "interval": max(3.0, min(300.0, interval)),
    }


class FederationConfigStore:
    """Owner-only persistent settings for a feature Manager attachment.

    The registration token is deliberately kept in this file instead of the
    browser or a checked-in deployment file.  ``public()`` never returns it;
    the Web settings page only receives a boolean indicating whether one is
    configured.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> dict[str, object]:
        with self._lock:
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                return _normalise_federation_config()
            if not isinstance(value, dict):
                return _normalise_federation_config()
            try:
                return _normalise_federation_config(value)
            except ValueError:
                return _normalise_federation_config()

    def merged(self, payload: dict[str, object]) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("federation config must be an object")
        allowed = {
            "enabled", "register_url", "public_endpoint",
            "registration_token", "ports", "interval",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown federation config fields: {', '.join(unknown)}")
        return _normalise_federation_config(payload, base=self.load())

    def save(self, value: dict[str, object]) -> dict[str, object]:
        normalised = _normalise_federation_config(value)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        with self._lock:
            temporary.write_text(
                json.dumps(normalised, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        return normalised

    @staticmethod
    def public(value: dict[str, object]) -> dict[str, object]:
        normalised = _normalise_federation_config(value)
        return {
            key: item
            for key, item in normalised.items()
            if key != "registration_token"
        } | {
            "registration_token_configured": bool(
                str(normalised.get("registration_token") or "")
            ),
        }

