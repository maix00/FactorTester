"""Minimal device-key allow-list for the private Manager and its peers.

The registry stores no MAC address, IMEI, browser fingerprint, raw User-Agent,
or location. For access auditing it retains only a coarse client label, the
source IP observed during enrollment, and the most recently observed IP. The
private key remains in browser storage or the native Keychain.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from server.manager.domain.device_clients import normalise_client_metadata


DEVICE_REGISTRY_SCHEMA_VERSION = 2
PUBLIC_DEVICE_LIMIT = 3
DEVICE_AUTHORIZATION_SCHEMA_VERSION = 1
DEVICE_AUTHORIZATION_TTL_SECONDS = 10 * 60
DEVICE_AUTHORIZATION_LANGUAGES = {"system", "zh-Hans", "en"}
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class DeviceRegistryError(ValueError):
    """A device record or registry snapshot is invalid."""


class PublicDeviceLimitError(DeviceRegistryError):
    """The account has reached its public-server device allowance."""

    def __init__(self, *, username: str, count: int, limit: int = PUBLIC_DEVICE_LIMIT) -> None:
        self.username = str(username)
        self.count = int(count)
        self.limit = int(limit)
        super().__init__("public device limit reached")


class DeviceAuthorizationError(DeviceRegistryError):
    """A one-time public-device authorization is invalid or expired."""


def authorization_token_hash(token: object) -> str:
    """Return the only representation of an authorization token we persist."""
    value = str(token or "").strip()
    if len(value) < 32 or len(value) > 256 or not _B64URL_RE.fullmatch(value):
        raise DeviceAuthorizationError("device authorization is invalid")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _b64url_decode(value: object, *, field: str) -> bytes:
    encoded = str(value or "").strip()
    if not encoded or not _B64URL_RE.fullmatch(encoded):
        raise DeviceRegistryError(f"{field} is not valid base64url")
    try:
        return base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4),
        )
    except (ValueError, TypeError) as exc:
        raise DeviceRegistryError(f"{field} is not valid base64url") from exc


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def normalise_device_id(value: object) -> str:
    result = str(value or "").strip()
    if not _DEVICE_ID_RE.fullmatch(result):
        raise DeviceRegistryError("device_id must be an opaque 16-128 character value")
    return result


def normalise_public_key(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise DeviceRegistryError("public_key must be a WebCrypto JWK object")
    if value.get("kty") != "EC" or value.get("crv") != "P-256":
        raise DeviceRegistryError("public_key must use the P-256 EC curve")
    x = _b64url_decode(value.get("x"), field="public_key.x")
    y = _b64url_decode(value.get("y"), field="public_key.y")
    if len(x) != 32 or len(y) != 32:
        raise DeviceRegistryError("public_key coordinates must be 32 bytes")
    # Do not persist arbitrary JWK members supplied by a browser.
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_encode(x),
        "y": _b64url_encode(y),
    }


def _normalise_record(
    value: object,
    *,
    source_server_id: str,
    now: float | None = None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DeviceRegistryError("device record must be an object")
    source = str(source_server_id or "").strip()
    if not source:
        raise DeviceRegistryError("source_server_id is required")
    username = str(value.get("username") or "").strip()
    if not username or len(username) > 256:
        raise DeviceRegistryError("username is required")
    device_id = normalise_device_id(value.get("device_id"))
    public_key = normalise_public_key(value.get("public_key"))
    current = time.time() if now is None else float(now)
    try:
        created_at = float(value.get("created_at") or current)
        updated_at = float(value.get("updated_at") or created_at)
    except (TypeError, ValueError) as exc:
        raise DeviceRegistryError("device timestamps must be numeric") from exc
    metadata = normalise_client_metadata(value)
    return {
        "device_id": device_id,
        "public_key": public_key,
        "username": username,
        "device_name": str(value.get("device_name") or "").strip()[:128],
        "enabled": bool(value.get("enabled", True)),
        "public_access": bool(value.get("public_access", False)),
        "created_at": created_at,
        "updated_at": updated_at,
        "source_server_id": source,
        **metadata,
    }


def _public_record(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in value.items()
        if key != "public_key"
    } | {
        "public_key_fingerprint": hashlib.sha256(
            json.dumps(
                value["public_key"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16],
    }


def _verify_public_key_signature(
    public_key: dict[str, str],
    *,
    challenge: bytes,
    signature: object,
) -> None:
    """Verify a WebCrypto P-256/SHA-256 signature without retaining key data."""
    signature_bytes = _b64url_decode(signature, field="signature")
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import (
            encode_dss_signature,
        )

        # WebCrypto returns IEEE P1363 r||s; cryptography accepts DER DSS.
        if len(signature_bytes) != 64:
            raise PermissionError("device signature is invalid")
        x = int.from_bytes(
            _b64url_decode(public_key["x"], field="public_key.x"), "big",
        )
        y = int.from_bytes(
            _b64url_decode(public_key["y"], field="public_key.y"), "big",
        )
        public = ec.EllipticCurvePublicNumbers(
            x, y, ec.SECP256R1(),
        ).public_key()
        der_signature = encode_dss_signature(
            int.from_bytes(signature_bytes[:32], "big"),
            int.from_bytes(signature_bytes[32:], "big"),
        )
        public.verify(der_signature, bytes(challenge), ec.ECDSA(hashes.SHA256()))
    except PermissionError:
        raise
    except Exception as exc:
        raise PermissionError("device signature is invalid") from exc


class DeviceRegistry:
    """Device allow-list with PostgreSQL as the deployed authority.

    The JSON file is retained only for a checkout that has no control database
    configured.  A Manager connected to PostgreSQL never authenticates from a
    stale local file, which makes a revoke effective on every server.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        server_id: str,
        control_store: object | None = None,
        public_server: bool = False,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.server_id = str(server_id or "").strip()
        if not self.server_id:
            raise DeviceRegistryError("server_id is required")
        self.control_store = control_store
        self.public_server = bool(public_server)
        self._lock = threading.RLock()
        self._generation = 0
        self._local: dict[str, dict[str, object]] = {}
        self._sources: dict[str, dict[str, object]] = {}
        if self.control_store is None:
            self._load()

    @property
    def backend(self) -> str:
        return "postgresql" if self.control_store is not None else "json"

    def backend_status(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "authoritative": self.control_store is not None,
            "server_id": self.server_id,
            "public_server": self.public_server,
            "public_device_limit": PUBLIC_DEVICE_LIMIT,
        }

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in {
                1,
                DEVICE_REGISTRY_SCHEMA_VERSION,
            }
        ):
            return
        try:
            self._generation = max(0, int(payload.get("generation") or 0))
        except (TypeError, ValueError):
            self._generation = 0
        local = payload.get("devices") or {}
        if isinstance(local, dict):
            for device_id, value in local.items():
                try:
                    record = _normalise_record(
                        {**value, "device_id": device_id},
                        source_server_id=self.server_id,
                    )
                except (TypeError, DeviceRegistryError):
                    continue
                self._local[record["device_id"]] = record
        sources = payload.get("sources") or {}
        if not isinstance(sources, dict):
            return
        for source_id, value in sources.items():
            if not isinstance(value, dict) or str(source_id) == self.server_id:
                continue
            try:
                generation = max(0, int(value.get("generation") or 0))
            except (TypeError, ValueError):
                continue
            records: dict[str, dict[str, object]] = {}
            for item in value.get("devices") or []:
                try:
                    record = _normalise_record(
                        item, source_server_id=str(source_id),
                    )
                except (TypeError, DeviceRegistryError):
                    continue
                records[record["device_id"]] = record
            self._sources[str(source_id)] = {
                "generation": generation,
                "devices": records,
            }

    def _save(self) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        payload = {
            "schema_version": DEVICE_REGISTRY_SCHEMA_VERSION,
            "server_id": self.server_id,
            "generation": self._generation,
            "devices": self._local,
            "sources": {
                source: {
                    "generation": value["generation"],
                    "devices": list(value["devices"].values()),
                }
                for source, value in self._sources.items()
            },
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def _all_locked(self) -> list[dict[str, object]]:
        result = list(self._local.values())
        for value in self._sources.values():
            result.extend(value["devices"].values())
        return [dict(item) for item in result]

    def enroll(
        self,
        *,
        username: str,
        device_id: str,
        public_key: object,
        device_name: str = "",
        client_type: str = "unknown",
        client_name: str = "",
        enrollment_ip: str = "",
    ) -> dict[str, object]:
        now = time.time()
        candidate = _normalise_record(
            {
                "device_id": device_id,
                "public_key": public_key,
                "username": username,
                "device_name": device_name,
                "client_type": client_type,
                "client_name": client_name,
                "enrollment_ip": enrollment_ip,
                "last_seen_ip": enrollment_ip,
                "enabled": True,
                "public_access": self.public_server,
                "created_at": now,
                "updated_at": now,
            },
            source_server_id=self.server_id,
            now=now,
        )
        if self.control_store is not None:
            try:
                record = self.control_store.enroll_device(
                    device_id=str(candidate["device_id"]),
                    public_key=dict(candidate["public_key"]),
                    username=str(candidate["username"]),
                    device_name=str(candidate["device_name"]),
                    source_server_id=self.server_id,
                    public_access=bool(candidate["public_access"]),
                    client_type=str(candidate["client_type"]),
                    client_name=str(candidate["client_name"]),
                    enrollment_ip=str(candidate["enrollment_ip"]),
                )
            except ValueError as exc:
                if str(exc) != "public device limit reached":
                    raise
                raise PublicDeviceLimitError(
                    username=str(candidate["username"]),
                    count=self.public_device_count(
                        username=str(candidate["username"]),
                    ),
                ) from exc
            return _public_record(record)
        with self._lock:
            if any(
                item.get("device_id") == candidate["device_id"]
                for item in self._all_locked()
            ):
                raise DeviceRegistryError("device_id is already registered")
            if bool(candidate["public_access"]):
                count = sum(
                    1
                    for item in self._all_locked()
                    if item.get("username") == candidate["username"]
                    and bool(item.get("enabled"))
                    and bool(item.get("public_access"))
                )
                if count >= PUBLIC_DEVICE_LIMIT:
                    raise PublicDeviceLimitError(
                        username=str(candidate["username"]),
                        count=count,
                    )
            self._local[candidate["device_id"]] = candidate
            self._generation += 1
            self._save()
            return _public_record(candidate)

    def public_device_count(self, *, username: str = "") -> int:
        owner = str(username or "").strip()
        if self.control_store is not None:
            return int(self.control_store.public_device_count(username=owner))
        with self._lock:
            return sum(
                1
                for item in self._all_locked()
                if (not owner or item.get("username") == owner)
                and bool(item.get("enabled"))
                and bool(item.get("public_access"))
            )

    def public_user_count(self) -> int:
        if self.control_store is not None:
            return int(self.control_store.public_device_user_count())
        with self._lock:
            return len({
                str(item.get("username") or "")
                for item in self._all_locked()
                if bool(item.get("enabled")) and bool(item.get("public_access"))
            } - {""})

    def revoke(self, device_id: str) -> dict[str, object]:
        identifier = normalise_device_id(device_id)
        if self.control_store is not None:
            record = self.control_store.revoke_device(identifier)
            if record is None:
                raise DeviceRegistryError("device was not found")
            return _public_record(record)
        with self._lock:
            record = self._local.get(identifier)
            if record is None:
                raise DeviceRegistryError("device was not found on this server")
            record = {**record, "enabled": False, "updated_at": time.time()}
            self._local[identifier] = record
            self._generation += 1
            self._save()
            return _public_record(record)

    def list(self, *, username: str = "", include_disabled: bool = True) -> list[dict[str, object]]:
        owner = str(username or "").strip()
        if self.control_store is not None:
            records = self.control_store.list_devices(
                username=owner,
                include_disabled=include_disabled,
            )
            return sorted(
                (_public_record(record) for record in records),
                key=lambda item: (
                    str(item.get("username") or ""),
                    str(item.get("device_name") or ""),
                    str(item.get("device_id") or ""),
                ),
            )
        with self._lock:
            values = [
                item for item in self._all_locked()
                if (not owner or item.get("username") == owner)
                and (include_disabled or bool(item.get("enabled")))
            ]
        return sorted(
            (_public_record(item) for item in values),
            key=lambda item: (
                str(item.get("username") or ""),
                str(item.get("device_name") or ""),
                str(item.get("device_id") or ""),
            ),
        )

    def snapshot(self) -> dict[str, object]:
        if self.control_store is not None:
            records = self.control_store.list_devices(include_disabled=True)
            return {
                "source_server_id": self.server_id,
                "generation": 0,
                "devices": records,
            }
        with self._lock:
            return {
                "source_server_id": self.server_id,
                "generation": self._generation,
                "devices": [dict(item) for item in self._local.values()],
            }

    def apply_snapshot(
        self,
        *,
        source_server_id: str,
        generation: int,
        devices: object,
    ) -> bool:
        if self.control_store is not None:
            # PostgreSQL is shared by all Managers; accepting HTTP snapshots
            # here would create a second, weaker source of truth.
            raise DeviceRegistryError(
                "device snapshots are disabled when PostgreSQL is authoritative"
            )
        source = str(source_server_id or "").strip()
        if not source or source == self.server_id:
            raise DeviceRegistryError("snapshot source is invalid")
        try:
            revision = max(0, int(generation))
        except (TypeError, ValueError) as exc:
            raise DeviceRegistryError("snapshot generation is invalid") from exc
        if not isinstance(devices, list) or len(devices) > 2000:
            raise DeviceRegistryError("snapshot devices must be a list of at most 2000 records")
        records: dict[str, dict[str, object]] = {}
        for item in devices:
            record = _normalise_record(item, source_server_id=source)
            records[record["device_id"]] = record
        with self._lock:
            previous = self._sources.get(source)
            if previous is not None and revision < int(previous["generation"]):
                return False
            self._sources[source] = {
                "generation": revision,
                "devices": records,
            }
            self._save()
        return True

    def verify(
        self,
        *,
        device_id: str,
        public_key: object,
        challenge: bytes,
        signature: object,
        last_seen_ip: str = "",
    ) -> dict[str, object]:
        identifier = normalise_device_id(device_id)
        key = normalise_public_key(public_key)
        if self.control_store is not None:
            record = self.control_store.device(identifier)
            if (
                record is None
                or not bool(record.get("enabled"))
                or record.get("public_key") != key
            ):
                raise PermissionError("device is not approved")
            _verify_public_key_signature(
                key, challenge=bytes(challenge), signature=signature,
            )
            self.control_store.touch_device(
                identifier,
                last_seen_ip=last_seen_ip,
            )
            observed = normalise_client_metadata({
                "last_seen_ip": last_seen_ip,
            })["last_seen_ip"]
            return {
                **dict(record),
                "last_seen_ip": observed or str(record.get("last_seen_ip") or ""),
            }
        with self._lock:
            matches = [
                item for item in self._all_locked()
                if item.get("device_id") == identifier
                and item.get("enabled")
                and item.get("public_key") == key
            ]
        if len(matches) != 1:
            raise PermissionError("device is not approved")
        _verify_public_key_signature(
            key, challenge=bytes(challenge), signature=signature,
        )
        record = matches[0]
        observed = normalise_client_metadata({
            "last_seen_ip": last_seen_ip,
        })["last_seen_ip"]
        if observed:
            with self._lock:
                local = self._local.get(identifier)
                if local is not None:
                    record = {
                        **local,
                        "last_seen_ip": observed,
                        "updated_at": time.time(),
                    }
                    self._local[identifier] = record
                    self._generation += 1
                    self._save()
        return dict(record)


class DeviceAuthorizationStore:
    """Issue short-lived, single-use grants for a public-origin enrollment.

    The raw token is returned only to the already authenticated internal
    Manager that creates the grant. PostgreSQL/local JSON store only a hash,
    so a leaked database snapshot cannot be used to redeem a grant.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        server_id: str,
        control_store: object | None = None,
        ttl_seconds: float = DEVICE_AUTHORIZATION_TTL_SECONDS,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.server_id = str(server_id or "").strip()
        if not self.server_id:
            raise DeviceAuthorizationError("server_id is required")
        self.control_store = control_store
        self.ttl_seconds = max(60.0, min(3600.0, float(ttl_seconds)))
        self._lock = threading.RLock()
        self._values: dict[str, dict[str, object]] = {}
        if self.control_store is None:
            self._load()

    @property
    def backend(self) -> str:
        return "postgresql" if self.control_store is not None else "json"

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("schema_version") != DEVICE_AUTHORIZATION_SCHEMA_VERSION:
            return
        values = payload.get("authorizations") or {}
        if not isinstance(values, dict):
            return
        now = time.time()
        for token_hash, value in values.items():
            if not isinstance(value, dict):
                continue
            try:
                expires_at = float(value.get("expires_at") or 0)
            except (TypeError, ValueError):
                continue
            if expires_at <= now:
                continue
            self._values[str(token_hash)] = dict(value)

    def _save(self) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        payload = {
            "schema_version": DEVICE_AUTHORIZATION_SCHEMA_VERSION,
            "authorizations": self._values,
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def issue(
        self,
        *,
        username: str,
        target_server_id: str,
        target_endpoint: str,
        device_name: str = "",
        preferred_language: str = "zh-Hans",
    ) -> dict[str, object]:
        owner = str(username or "").strip()
        target = str(target_server_id or "").strip()
        endpoint = str(target_endpoint or "").strip().rstrip("/")
        language = str(preferred_language or "").strip()
        if not owner or len(owner) > 256 or not target or len(target) > 128 or not endpoint:
            raise DeviceAuthorizationError("device authorization fields are invalid")
        if language not in DEVICE_AUTHORIZATION_LANGUAGES:
            raise DeviceAuthorizationError("device authorization language is invalid")
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + self.ttl_seconds
        token_hash = authorization_token_hash(token)
        if self.control_store is not None:
            self.control_store.create_device_authorization(
                token_hash=token_hash,
                username=owner,
                target_server_id=target,
                target_endpoint=endpoint,
                device_name=str(device_name or "").strip()[:128],
                preferred_language=language,
                expires_at=expires_at,
                source_server_id=self.server_id,
            )
        else:
            with self._lock:
                current = time.time()
                self._values = {
                    key: value for key, value in self._values.items()
                    if float(value.get("expires_at") or 0) > current
                    and not value.get("used_at")
                }
                self._values[token_hash] = {
                    "username": owner,
                    "target_server_id": target,
                    "target_endpoint": endpoint,
                    "device_name": str(device_name or "").strip()[:128],
                    "preferred_language": language,
                    "expires_at": expires_at,
                    "source_server_id": self.server_id,
                }
                self._save()
        return {
            "token": token,
            "username": owner,
            "target_server_id": target,
            "target_endpoint": endpoint,
            "device_name": str(device_name or "").strip()[:128],
            "preferred_language": language,
            "expires_at": expires_at,
            "expires_in": int(self.ttl_seconds),
            "backend": self.backend,
        }

    def preview(self, token: object, *, target_server_id: str) -> dict[str, object]:
        """Read a live grant without consuming its one-time redemption."""
        token_hash = authorization_token_hash(token)
        target = str(target_server_id or "").strip()
        if not target:
            raise DeviceAuthorizationError("device authorization target is invalid")
        if self.control_store is not None:
            record = self.control_store.preview_device_authorization(
                token_hash=token_hash,
                target_server_id=target,
            )
            if record is None:
                raise DeviceAuthorizationError(
                    "device authorization is invalid or expired"
                )
            return dict(record)
        with self._lock:
            value = self._values.get(token_hash)
            if (
                value is None
                or value.get("used_at")
                or float(value.get("expires_at") or 0) <= time.time()
                or str(value.get("target_server_id") or "") != target
            ):
                raise DeviceAuthorizationError(
                    "device authorization is invalid or expired"
                )
            return dict(value)

    def consume(self, token: object, *, target_server_id: str) -> dict[str, object]:
        token_hash = authorization_token_hash(token)
        target = str(target_server_id or "").strip()
        if not target:
            raise DeviceAuthorizationError("device authorization target is invalid")
        if self.control_store is not None:
            record = self.control_store.consume_device_authorization(
                token_hash=token_hash,
                target_server_id=target,
            )
            if record is None:
                raise DeviceAuthorizationError("device authorization is invalid or expired")
            return dict(record)
        with self._lock:
            value = self._values.get(token_hash)
            now = time.time()
            if (
                value is None
                or value.get("used_at")
                or float(value.get("expires_at") or 0) <= now
                or str(value.get("target_server_id") or "") != target
            ):
                raise DeviceAuthorizationError("device authorization is invalid or expired")
            result = dict(value)
            result["used_at"] = now
            self._values[token_hash] = result
            self._save()
            return result


class DeviceChallengeStore:
    """Short-lived, one-use challenges kept in Manager memory."""

    def __init__(self, *, ttl_seconds: float = 120.0) -> None:
        self.ttl_seconds = max(30.0, min(600.0, float(ttl_seconds)))
        self._lock = threading.RLock()
        self._values: dict[str, tuple[bytes, float]] = {}

    def issue(self) -> tuple[str, bytes]:
        identifier = secrets.token_urlsafe(24)
        challenge = secrets.token_bytes(32)
        with self._lock:
            now = time.time()
            self._values = {
                key: value for key, value in self._values.items()
                if value[1] > now
            }
            self._values[identifier] = (challenge, now + self.ttl_seconds)
        return identifier, challenge

    def consume(self, identifier: object) -> bytes:
        key = str(identifier or "").strip()
        with self._lock:
            value = self._values.pop(key, None)
        if value is None or value[1] <= time.time():
            raise PermissionError("device challenge is expired")
        return value[0]
