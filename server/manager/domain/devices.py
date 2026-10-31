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


DEVICE_REGISTRY_SCHEMA_VERSION = 3
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class DeviceRegistryError(ValueError):
    """A device record or registry snapshot is invalid."""


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


def device_public_key_digest(value: object) -> str:
    """Full canonical digest for binding an authorization to one device key."""
    return hashlib.sha256(json.dumps(
        normalise_public_key(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


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
    if "enabled" in value and type(value["enabled"]) is not bool:
        raise DeviceRegistryError("device enabled state must be boolean")
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
        "public_key_fingerprint": device_public_key_digest(value["public_key"])[:16],
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
        # Retain legacy fields only for migration inventory. They are never
        # returned as an authorization decision or exposed in device listings.
        self._legacy_local: dict[str, dict[str, object]] = {}
        self._legacy_sources: dict[str, dict[str, dict[str, object]]] = {}
        self._legacy_source_metadata: dict[str, dict[str, object]] = {}
        self._legacy_root: dict[str, object] = {}
        self._repair_count = 0
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
            "device_policy": "public_allowlist_only",
            # PostgreSQL requires a separate inventory; this in-process JSON
            # loader cannot say whether its records need migration repair.
            "migration_repair_required": self._repair_count > 0 if self.control_store is None else None,
            "migration_repair_count": self._repair_count if self.control_store is None else None,
        }

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError, json.JSONDecodeError):
            self._repair_count += 1
            return
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in {
                1,
                2,
                DEVICE_REGISTRY_SCHEMA_VERSION,
            }
        ):
            self._repair_count += 1
            return
        if payload.get("server_id") != self.server_id:
            # A moved or unbound snapshot is not evidence that its devices
            # belong to this Manager. Retain it for an explicit migration.
            self._repair_count += 1
            return
        self._legacy_root = {key: value for key, value in payload.items()
                             if key not in {"schema_version", "server_id", "generation", "devices", "sources"}}
        try:
            self._generation = max(0, int(payload.get("generation") or 0))
        except (TypeError, ValueError):
            self._generation = 0
            self._repair_count += 1
        local = payload.get("devices", {})
        if isinstance(local, dict):
            for device_id, value in local.items():
                try:
                    record = _normalise_record(
                        {**value, "device_id": device_id},
                        source_server_id=self.server_id,
                    )
                except (TypeError, DeviceRegistryError):
                    self._repair_count += 1
                    continue
                self._local[record["device_id"]] = record
                self._legacy_local[record["device_id"]] = {
                    key: item for key, item in value.items() if key not in record
                }
        else:
            self._repair_count += 1
        sources = payload.get("sources", {})
        if not isinstance(sources, dict):
            self._repair_count += 1
            return
        for source_id, value in sources.items():
            if not isinstance(value, dict) or str(source_id) == self.server_id:
                self._repair_count += 1
                continue
            try:
                generation = max(0, int(value.get("generation") or 0))
            except (TypeError, ValueError):
                self._repair_count += 1
                continue
            records: dict[str, dict[str, object]] = {}
            raw_devices = value.get("devices", [])
            if not isinstance(raw_devices, list):
                self._repair_count += 1
                continue
            legacy: dict[str, dict[str, object]] = {}
            for item in raw_devices:
                try:
                    record = _normalise_record(
                        item, source_server_id=str(source_id),
                    )
                except (TypeError, DeviceRegistryError):
                    self._repair_count += 1
                    continue
                if record["device_id"] in records:
                    self._repair_count += 1
                    continue
                records[record["device_id"]] = record
                legacy[record["device_id"]] = {key: item for key, item in item.items() if key not in record}
            self._legacy_sources[str(source_id)] = legacy
            self._legacy_source_metadata[str(source_id)] = {
                key: item for key, item in value.items() if key not in {"generation", "devices"}
            }
            self._sources[str(source_id)] = {
                "generation": generation,
                "devices": records,
            }
        seen: set[str] = set()
        for item in self._all_locked():
            identifier = str(item["device_id"])
            if identifier in seen:
                self._repair_count += 1
            seen.add(identifier)

    def _require_writable(self) -> None:
        if self._repair_count:
            raise DeviceRegistryError("device directory contains records requiring migration repair")

    def _save(self) -> None:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        payload = {
            **self._legacy_root,
            "schema_version": DEVICE_REGISTRY_SCHEMA_VERSION,
            "server_id": self.server_id,
            "generation": self._generation,
            "devices": {identifier: {**self._legacy_local.get(identifier, {}), **record}
                        for identifier, record in self._local.items()},
            "sources": {
                source: {
                    **self._legacy_source_metadata.get(source, {}),
                    "generation": value["generation"],
                    "devices": [{**self._legacy_sources.get(source, {}).get(identifier, {}), **record}
                                for identifier, record in value["devices"].items()],
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
                "created_at": now,
                "updated_at": now,
            },
            source_server_id=self.server_id,
            now=now,
        )
        if self.control_store is not None:
            record = self.control_store.enroll_device(
                device_id=str(candidate["device_id"]),
                public_key=dict(candidate["public_key"]),
                username=str(candidate["username"]),
                device_name=str(candidate["device_name"]),
                source_server_id=self.server_id,
                client_type=str(candidate["client_type"]),
                client_name=str(candidate["client_name"]),
                enrollment_ip=str(candidate["enrollment_ip"]),
            )
            return _public_record(record)
        with self._lock:
            self._require_writable()
            if any(
                item.get("device_id") == candidate["device_id"]
                for item in self._all_locked()
            ):
                raise DeviceRegistryError("device_id is already registered")
            self._local[candidate["device_id"]] = candidate
            self._generation += 1
            self._save()
            return _public_record(candidate)

    def retry_enrollment(self, *, username: str, device_id: str, public_key: object) -> dict[str, object]:
        """Explicitly re-enable a disabled device only with its original key."""
        identifier = normalise_device_id(device_id)
        owner = str(username or "").strip()
        key = normalise_public_key(public_key)
        if self.control_store is not None:
            record = self.control_store.reenable_device(device_id=identifier, username=owner,
                                                        public_key=key, source_server_id=self.server_id)
            if record is None:
                raise DeviceRegistryError("device cannot be re-enrolled with this identity or key")
            return _public_record(record)
        with self._lock:
            self._require_writable()
            record = self._local.get(identifier)
            if (record is None or record.get("enabled") or record.get("username") != owner
                    or record.get("public_key") != key):
                raise DeviceRegistryError("device cannot be re-enrolled with this identity or key")
            record = {**record, "enabled": True, "updated_at": time.time()}
            self._local[identifier] = record
            self._generation += 1
            self._save()
            return _public_record(record)

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
            )

    def public_user_count(self) -> int:
        if self.control_store is not None:
            return int(self.control_store.public_device_user_count())
        with self._lock:
            return len({
                str(item.get("username") or "")
                for item in self._all_locked()
                if bool(item.get("enabled"))
            } - {""})

    def public_device_total_count(self, *, username: str = "") -> int:
        """Count all enabled public allowlist devices."""
        owner = str(username or "").strip()
        if self.control_store is not None:
            reader = getattr(self.control_store, "public_device_total_count", None)
            if callable(reader):
                return int(reader(username=owner))
        with self._lock:
            return sum(
                1
                for item in self._all_locked()
                if (not owner or item.get("username") == owner)
                and bool(item.get("enabled"))
            )

    def revoke(self, device_id: str) -> dict[str, object]:
        identifier = normalise_device_id(device_id)
        if self.control_store is not None:
            record = self.control_store.revoke_device(identifier)
            if record is None:
                raise DeviceRegistryError("device was not found")
            return _public_record(record)
        with self._lock:
            self._require_writable()
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
        incoming_legacy: dict[str, dict[str, object]] = {}
        for item in devices:
            record = _normalise_record(item, source_server_id=source)
            if record["device_id"] in records:
                raise DeviceRegistryError("snapshot contains duplicate device IDs")
            records[record["device_id"]] = record
            incoming_legacy[record["device_id"]] = {
                key: item[key] for key in ("public_access", "quota_exempt") if key in item
            }
        with self._lock:
            self._require_writable()
            previous = self._sources.get(source)
            if previous is not None and revision < int(previous["generation"]):
                return False
            other_ids = set(self._local)
            for other_source, value in self._sources.items():
                if other_source != source:
                    other_ids.update(value["devices"])
            if other_ids.intersection(records):
                raise DeviceRegistryError("snapshot conflicts with another device source")
            # Never erase pre-cutover fields by accepting a later mirror that
            # omitted or replaced the corresponding device identity.
            for identifier, fields in self._legacy_sources.get(source, {}).items():
                if fields and (identifier not in records or identifier not in previous["devices"]
                        or any(records[identifier][key] != previous["devices"][identifier][key]
                               for key in ("username", "public_key"))):
                    raise DeviceRegistryError("legacy device fields require migration before snapshot replacement")
                for key, value in fields.items():
                    if key in incoming_legacy[identifier] and incoming_legacy[identifier][key] != value:
                        raise DeviceRegistryError("legacy device fields require migration before snapshot replacement")
                    incoming_legacy[identifier][key] = value
            self._legacy_sources[source] = incoming_legacy
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
            if record is None or not bool(record.get("enabled")) or record.get("public_key") != key:
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
                if local is not None and not self._repair_count:
                    record = {
                        **local,
                        "last_seen_ip": observed,
                        "updated_at": time.time(),
                    }
                    self._local[identifier] = record
                    self._generation += 1
                    self._save()
        return dict(record)

    def key_binding(self, *, username: str, device_id: str) -> dict[str, object] | None:
        """Resolve one device key; its authorization is decided by Keycloak."""
        identifier = normalise_device_id(device_id)
        owner = str(username or "").strip()
        if not owner:
            return None
        if self.control_store is not None:
            row = self.control_store.device(identifier)
            return dict(row) if row and row.get("username") == owner else None
        with self._lock:
            matches = [row for row in self._all_locked()
                       if row.get("device_id") == identifier and row.get("username") == owner]
        return dict(matches[0]) if len(matches) == 1 else None


class DeviceChallengeStore:
    """Short-lived, one-use challenges kept in Manager memory."""

    def __init__(self, *, ttl_seconds: float = 120.0) -> None:
        self.ttl_seconds = max(30.0, min(600.0, float(ttl_seconds)))
        self._lock = threading.RLock()
        self._values: dict[str, tuple[bytes, float]] = {}
        self._device_login_tickets: dict[
            str, tuple[str, str, str, float, str]
        ] = {}

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

    def issue_device_login_ticket(
        self, *, username: str, device_id: str, origin: str, public_key: object,
    ) -> str:
        """Bind a verified device proof to one subsequent Keycloak OIDC flow."""
        principal = str(username or "").strip()
        identifier = normalise_device_id(device_id)
        trusted_origin = str(origin or "").strip().rstrip("/")
        if not principal or not trusted_origin.startswith(("https://", "http://")):
            raise DeviceRegistryError("device login identity or origin is invalid")
        ticket = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._device_login_tickets = {
                key: value for key, value in self._device_login_tickets.items()
                if value[3] > now
            }
            while len(self._device_login_tickets) >= 1024:
                self._device_login_tickets.pop(next(iter(self._device_login_tickets)))
            self._device_login_tickets[ticket] = (
                principal, identifier, trusted_origin, now + self.ttl_seconds,
                device_public_key_digest(public_key),
            )
        return ticket

    def consume_device_login_ticket(
        self, ticket: object, *, origin: str,
    ) -> tuple[str, str, str]:
        """Consume one device-to-OIDC binding; reject replay or origin changes."""
        key = str(ticket or "").strip()
        with self._lock:
            value = self._device_login_tickets.pop(key, None)
        if (
            value is None
            or value[3] <= time.time()
            or not secrets.compare_digest(value[2], str(origin or "").strip().rstrip("/"))
        ):
            raise PermissionError("device login ticket is invalid or expired")
        return value[0], value[1], value[4]
