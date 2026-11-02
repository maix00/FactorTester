"""Rename reviewed Keycloak login names without changing identity or credentials.

The input explicitly supplies login_username and tr_identity_id. A display
alias is never interpreted as proof of identity or used to link users.
"""
from __future__ import annotations


def plan_login_names(accounts, adapter):
    planned = []
    seen = set()
    for account in accounts:
        name = str(account.get("login_username") or "").strip()
        identity = str(account.get("tr_identity_id") or "").strip()
        if not name or not identity or any(ord(c) < 32 for c in name):
            raise ValueError("explicit login username and stable identity required")
        if name.casefold() in seen:
            raise ValueError("duplicate login username")
        seen.add(name.casefold())
        current = adapter.user_by_identity_id(identity)
        if not current or not current.get("id"):
            raise ValueError("stable identity is missing")
        named = adapter.user_representation(name)
        if named and named["id"] != current["id"]:
            raise ValueError("login username belongs to another identity")
        planned.append((current, name))
    return planned


def apply_login_names(accounts, adapter, *, dry_run=True):
    # Complete every collision check before the first write.
    planned = plan_login_names(accounts, adapter)
    changed = 0
    for current, name in planned:
        if str(current["username"]).casefold() == name.casefold():
            continue
        changed += 1
        if dry_run:
            continue
        subject = str(current["id"])
        # Preserve attributes (including the legacy owner label), groups,
        # roles, credentials and the immutable Keycloak subject.
        adapter._put(f"users/{subject}", {"username": name})
        confirmed = adapter.user_by_identity_id(
            current["attributes"]["tr_identity_id"][0])
        if (not confirmed or confirmed["id"] != subject
                or str(confirmed["username"]).casefold() != name.casefold()
                or confirmed.get("attributes") != current.get("attributes")):
            raise RuntimeError("login rename did not preserve the identity attributes")
    return {"dry_run": dry_run, "reviewed": len(planned), "changed": changed}
