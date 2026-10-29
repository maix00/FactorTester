"""Keycloak-backed policy for cross-Manager organization identity sync.

The policy lives on the organization's Realm Group. This module keeps only
transport configuration and validation; it is not a parallel permission
store. Identity event transport is separate and must honor both the source
opt-in and destination allow policy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from server.identity.keycloak import KeycloakAdminAdapter
from server.identity.realm_groups import GROUP_ROOT
from server.identity.user_session import oidc_settings
from server.identity.realm_groups import organization_group_path


SOURCE_ENABLED_ATTRIBUTE = "tr_identity_sync_enabled"
DESTINATION_ALLOWED_ATTRIBUTE = "tr_identity_sync_allowed"
PUBLIC_LOGIN_ROLE = "public_server:login"
ADMIN_ROLE = "admin_console:manage"
GTHT_ORGANIZATION_ID = "GTHT"
GTHT_SYNC_HANDOFF_SUPER_ADMIN = "MaxJJW"
IDENTITY_SYNC_ATTRIBUTES = frozenset({
    SOURCE_ENABLED_ATTRIBUTE,
    DESTINATION_ALLOWED_ATTRIBUTE,
})


class IdentitySyncTransitionError(PermissionError):
    """A policy transition would violate the GTHT admin handoff invariant."""


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


def assert_source_sync_can_be_disabled(
    adapter: KeycloakAdminAdapter,
    *,
    group_path: str,
    roles_client_id: str,
) -> None:
    """Require a completed MaxJJW handoff before disabling GTHT sync.

    The role-holder list is fetched only when an administrator requests this
    transition. An unavailable, malformed, or over-limit Keycloak result
    fails closed; no role is removed implicitly by this operation.
    """
    if group_path != organization_group_path(GTHT_ORGANIZATION_ID):
        return
    users = adapter.client_role_users(roles_client_id, ADMIN_ROLE)
    enabled_usernames: list[str] = []
    for user in users:
        if user.get("enabled") is not True:
            continue
        username = str(user.get("username") or "").strip()
        if not username:
            raise RuntimeError("Keycloak admin role holder has no username")
        enabled_usernames.append(username)
    folded = [name.casefold() for name in enabled_usernames]
    if len(set(folded)) != len(folded):
        raise RuntimeError("Keycloak admin role holders have ambiguous usernames")
    handoff = GTHT_SYNC_HANDOFF_SUPER_ADMIN.casefold()
    if handoff in folded:
        if len(enabled_usernames) == 1:
            raise IdentitySyncTransitionError(
                "GTHT public sync cannot be disabled while MaxJJW is the only "
                "active super administrator; assign another super administrator "
                "first, then remove MaxJJW's super administrator role"
            )
        raise IdentitySyncTransitionError(
            "Remove MaxJJW's super administrator role in Keycloak before "
            "disabling GTHT public sync"
        )
    if not enabled_usernames:
        raise IdentitySyncTransitionError(
            "GTHT public sync cannot be disabled until another active super "
            "administrator is assigned in Keycloak"
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
