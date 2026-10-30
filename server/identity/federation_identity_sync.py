"""Keycloak-backed policy for cross-Manager organization identity sync.

The policy lives on the organization's Realm Group. This module keeps only
transport configuration and validation; it is not a parallel permission
store. Identity event transport is separate and must honor both the source
opt-in and destination allow policy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from server.identity.keycloak import KeycloakAdminAdapter
from server.identity.realm_groups import GROUP_ROOT
from server.identity.user_session import oidc_settings

SOURCE_ENABLED_ATTRIBUTE = "tr_identity_sync_enabled"
DESTINATION_ALLOWED_ATTRIBUTE = "tr_identity_sync_allowed"
PUBLIC_LOGIN_ROLE = "public_server:login"
ADMIN_ROLE = "admin_console:manage"
IDENTITY_SYNC_ATTRIBUTES = frozenset({
    SOURCE_ENABLED_ATTRIBUTE,
    DESTINATION_ALLOWED_ATTRIBUTE,
})


class IdentitySyncTransitionError(PermissionError):
    """A policy transition would violate public-manager admin continuity."""


class IdentitySyncVerificationUnavailable(ConnectionError):
    """The public Manager cannot provide a current sync-disable decision."""


def identity_sync_disable_signature(
    secret: str,
    *,
    requester_server_id: str,
    group_path: str,
    issued_at: int,
    request_id: str,
) -> str:
    """Sign one short-lived decision request with the requester's peer secret."""
    message = json.dumps(
        [requester_server_id, group_path, int(issued_at), request_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(str(secret).encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_identity_sync_disable_signature(
    secret: str,
    *,
    requester_server_id: str,
    group_path: str,
    issued_at: int,
    request_id: str,
    signature: str,
    now: float | None = None,
) -> bool:
    """Verify a bounded, short-lived peer decision request."""
    selected_request_id = str(request_id or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", selected_request_id):
        return False
    current = time.time() if now is None else float(now)
    if abs(current - int(issued_at)) > 30:
        return False
    expected = identity_sync_disable_signature(
        secret,
        requester_server_id=requester_server_id,
        group_path=group_path,
        issued_at=issued_at,
        request_id=selected_request_id,
    )
    return hmac.compare_digest(expected, str(signature or ""))


def manager_keycloak_admin_adapter() -> KeycloakAdminAdapter:
    """Build the least-surprising Manager Admin REST client from secret config.

    A dedicated service account is required. The user's login secret is never
    reused as a Keycloak Admin credential.
    """
    settings = oidc_settings()
    base_url = str(
        os.environ.get("TRADERESEARCH_KEYCLOAK_URL")
        or settings["backchannel_base_url"]
    ).strip().rstrip("/")
    realm = str(
        os.environ.get("TRADERESEARCH_KEYCLOAK_REALM")
        or settings["realm"]
    ).strip()
    client_id = str(
        os.environ.get("TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID") or ""
    ).strip()
    secret_path = str(
        os.environ.get("TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET_FILE") or ""
    ).strip()
    secret = (
        Path(secret_path).read_text(encoding="utf-8").strip()
        if secret_path else str(
            os.environ.get("TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET") or ""
        ).strip()
    )
    if not base_url or not realm or not client_id or not secret:
        raise RuntimeError("Manager Keycloak administration client is not configured")
    return KeycloakAdminAdapter(
        base_url,
        realm,
        client_id=client_id,
        client_secret=secret,
        timeout=5.0,
    )


def organization_group_paths(groups: list[dict[str, Any]]) -> list[str]:
    """Return only top-level organization membership groups."""
    prefix = f"{GROUP_ROOT}/organizations/"
    paths = {
        str(row.get("path") or "")
        for row in groups
        if isinstance(row, dict)
        and str(row.get("path") or "").startswith(prefix)
        and "/" not in str(row.get("path") or "")[len(prefix):]
    }
    return sorted(path for path in paths if path)


def organization_group_from_admin_scope(path: object) -> str:
    """Map one exact organization-admin group claim to its member group."""
    parts = str(path or "").strip("/").split("/")
    if (
        len(parts) != 5
        or parts[:3] != ["traderesearch", "admin-scopes", "organizations"]
        or parts[4] != "organization-admins"
        or not parts[3]
    ):
        return ""
    return f"{GROUP_ROOT}/organizations/{parts[3]}"


def group_sync_value(group: dict[str, Any], attribute: str) -> bool:
    """Interpret a missing/invalid Keycloak flag as disabled."""
    if attribute not in IDENTITY_SYNC_ATTRIBUTES:
        raise ValueError("unsupported identity-sync policy attribute")
    attributes = group.get("attributes")
    values = attributes.get(attribute) if isinstance(attributes, dict) else None
    if not isinstance(values, list) or len(values) != 1:
        return False
    return str(values[0]).strip().lower() == "true"


def set_group_sync_value(
    adapter: KeycloakAdminAdapter,
    *,
    group_path: str,
    attribute: str,
    enabled: bool,
) -> dict[str, Any]:
    """Persist and verify one explicit allow/opt-in policy in Keycloak."""
    if attribute not in IDENTITY_SYNC_ATTRIBUTES:
        raise ValueError("unsupported identity-sync policy attribute")
    return adapter.update_group_attributes(
        group_path,
        {attribute: ["true" if enabled else "false"]},
    )


def assert_destination_sync_can_be_disabled(
    adapter: KeycloakAdminAdapter,
    *,
    group_path: str,
    roles_client_id: str,
) -> None:
    """Check public-realm administrator continuity before disabling sync.

    This bounded check runs once, only when the public Manager is asked to
    disable one organization's inbound sync. Active global super administrators
    belonging to that organization must first be removed from the role, and at
    least one active super administrator in another organization must remain.
    Missing or over-limit Keycloak data fails closed. This is a precondition
    check; it never changes role assignments.
    """
    users = adapter.client_role_users(
        roles_client_id, ADMIN_ROLE, page_size=100, max_users=1000,
    )
    organization_admin_count = 0
    external_admin_count = 0
    organization_prefix = f"{GROUP_ROOT}/organizations/"
    for user in users:
        enabled = user.get("enabled")
        if type(enabled) is not bool:
            raise RuntimeError("Keycloak admin role holder omitted enabled status")
        if not enabled:
            continue
        username = str(user.get("username") or "").strip()
        user_id = str(user.get("id") or "").strip()
        if not username or not user_id:
            raise RuntimeError("Keycloak admin role holder omitted identity")
        paths = adapter.user_group_paths(user_id, page_size=100, max_groups=1000)
        organization_roots = set()
        for path in paths:
            if not path.startswith(organization_prefix):
                continue
            organization_id = path[len(organization_prefix):].split("/", 1)[0]
            if organization_id:
                organization_roots.add(
                    f"{organization_prefix}{organization_id}"
                )
        if not organization_roots:
            raise RuntimeError(
                "Keycloak super administrator has no verifiable organization membership"
            )
        belongs_to_organization = group_path in organization_roots
        if belongs_to_organization:
            organization_admin_count += 1
        else:
            external_admin_count += 1
    if not external_admin_count:
        raise IdentitySyncTransitionError(
            "sync cannot be disabled: an active super administrator in another "
            "organization must first be assigned in the public Keycloak realm"
        )
    if organization_admin_count:
        raise IdentitySyncTransitionError(
            "sync cannot be disabled yet: remove the public super administrator "
            "role from this organization's users, then retry"
        )


def public_identity_sync_eligible(
    user_roles: object, *, source_enabled: bool, destination_allowed: bool,
) -> bool:
    """Check the login-time, per-user gates before lazy public identity sync."""
    if not source_enabled or not destination_allowed:
        return False
    if not isinstance(user_roles, (tuple, list, set, frozenset)):
        return False
    return PUBLIC_LOGIN_ROLE in user_roles
