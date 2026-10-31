"""Keycloak authorization for one registered Manager device key.

Device metadata and challenge verification stay with the Manager. This module
only manages the Keycloak ``use`` grant; callers must first verify the user
session and device signature, and must never register on a mere access check.
"""
from __future__ import annotations

import json

from server.identity.keycloak_authorization import (
    delete_keycloak_resource,
    ensure_keycloak_resource,
    keycloak_authorized_objects,
)
from server.identity.user_session import oidc_settings
from server.manager.domain.devices import device_public_key_digest, normalise_device_id


def device_resource_ref(*, server_id: str, identity_id: str, device_id: str, public_key: object) -> str:
    """Use stable user, Manager and full key identities, never a display name."""
    server = str(server_id or "").strip()
    identity = str(identity_id or "").strip()
    if not server or len(server) > 256 or not identity or len(identity) > 512:
        raise ValueError("Manager and stable user identities are required")
    return json.dumps([server, identity, normalise_device_id(device_id), device_public_key_digest(public_key)],
                      ensure_ascii=False, separators=(",", ":"))


def _verified_binding(session: object) -> tuple[str, str]:
    if not isinstance(session, dict):
        raise PermissionError("verified Keycloak session is required")
    subject = str(session.get("keycloak_subject") or "").strip()
    identity = str(session.get("tr_identity_id") or "").strip()
    issuer = str(session.get("keycloak_issuer") or "").strip().rstrip("/")
    if not subject or not identity or issuer != oidc_settings()["issuer"].rstrip("/"):
        raise PermissionError("device owner has no verified local Keycloak identity")
    return subject, identity


def register_device(*, session: dict, server_id: str, device_id: str, public_key: object) -> str:
    """Create the owner's grant only during explicit enrollment or migration."""
    subject, identity = _verified_binding(session)
    ref = device_resource_ref(server_id=server_id, identity_id=identity,
                              device_id=device_id, public_key=public_key)
    return ensure_keycloak_resource(resource_type="device", resource_ref=ref,
                                    owner_subject=subject, owner_scopes=("use",))


def may_use_device(*, token: str, session: dict, server_id: str, device_id: str, public_key: object) -> bool:
    """Check Keycloak freshly so a revoked device is denied at the next login."""
    if not token:
        return False
    _subject, identity = _verified_binding(session)
    ref = device_resource_ref(server_id=server_id, identity_id=identity,
                              device_id=device_id, public_key=public_key)
    return ref in keycloak_authorized_objects(token, resource_type="device", refs=[(ref, ref)],
                                               scope="use", use_cache=False)


def may_use_devices(*, token: str, session: dict, server_id: str, records: list[dict]) -> set[str]:
    """Batch-check one verified owner's enabled device keys against Keycloak."""
    if not token:
        raise PermissionError("verified Keycloak token is required")
    _subject, identity = _verified_binding(session)
    owner = str(session.get("username") or "").strip()
    if not owner or not isinstance(records, list) or len(records) > 10000:
        raise ValueError("device authorization inventory is invalid or too large")
    refs, seen = [], set()
    for record in records:
        if not isinstance(record, dict) or record.get("username") != owner or type(record.get("enabled")) is not bool:
            raise ValueError("device authorization owner or state is invalid")
        identifier = normalise_device_id(record.get("device_id"))
        if identifier in seen:
            raise ValueError("device authorization contains duplicate identities")
        seen.add(identifier)
        if record['enabled']:
            refs.append((device_resource_ref(server_id=server_id, identity_id=identity,
                                             device_id=identifier, public_key=record.get("public_key")), identifier))
    return keycloak_authorized_objects(token, resource_type="device", refs=refs,
                                      scope="use", use_cache=False)


def revoke_device(*, session: dict, server_id: str, device_id: str, public_key: object) -> bool:
    """Revoke the exact key grant; never recreate it during a later check."""
    subject, identity = _verified_binding(session)
    return revoke_device_for_owner(owner_subject=subject, identity_id=identity,
                                   server_id=server_id, device_id=device_id, public_key=public_key)


def revoke_device_for_owner(*, owner_subject: str, identity_id: str, server_id: str,
                            device_id: str, public_key: object) -> bool:
    """Remove a known owner's grant after the caller's admin scope was checked."""
    subject = str(owner_subject or "").strip()
    if not subject or len(subject) > 255:
        raise ValueError("device owner subject is required")
    ref = device_resource_ref(server_id=server_id, identity_id=identity_id,
                              device_id=device_id, public_key=public_key)
    return delete_keycloak_resource(resource_type="device", resource_ref=ref,
                                    owner_subject=subject)
