"""Resolve permission subjects for a username (Keycloak-aware, fail closed)."""

from __future__ import annotations

import os


def subjects_for_user(username: str) -> list[str]:
    subjects = [f"user:{username}"]
    base_url = os.environ.get("TRADERESEARCH_KEYCLOAK_URL", "") or os.environ.get(
        "FACTORTESTER_KEYCLOAK_URL", ""
    )
    realm = os.environ.get("TRADERESEARCH_KEYCLOAK_REALM", "") or os.environ.get(
        "FACTORTESTER_KEYCLOAK_REALM", ""
    )
    if not (base_url and realm and username):
        return subjects
    try:
        from server.identity.keycloak import KeycloakAdminAdapter, permission_subjects

        identity = KeycloakAdminAdapter(
            base_url, realm,
            client_id=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_ID", "admin-cli"),
            client_secret=os.environ.get("TRADERESEARCH_KEYCLOAK_CLIENT_SECRET", ""),
        ).user(username)
        if identity is not None:
            return list(permission_subjects(identity))
    except Exception:
        pass
    return subjects
