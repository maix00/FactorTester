"""Shared live Keycloak directory checks for administrative migrations only.

Never used as an end-user authorization source or as a persisted user directory.
"""
from __future__ import annotations

from urllib.parse import quote, urlencode
from server.identity.keycloak_authorization import AuthorizationUnavailable


def active_human_subjects(adapter) -> dict[str, str]:
    """Enumerate the entire bounded directory, not just legacy ACL members.

    An enabled service-account row may be excluded only after verifying its
    Keycloak client and the client's service-account-user association. Every
    other enabled account must have exactly one stable ID and belong to the
    organization group tree. Malformed or ambiguous rows block verification.
    """
    subjects: dict[str, str] = {}
    known_subjects: set[str] = set()
    for user in adapter._page("users", max_items=20_000):
        if not isinstance(user, dict) or type(user.get("enabled")) is not bool:
            raise AuthorizationUnavailable("Keycloak user directory is invalid")
        if user["enabled"] is False:
            continue
        subject = str(user.get("id") or "").strip()
        service_client_id = user.get("serviceAccountClientId")
        if service_client_id:
            if not isinstance(service_client_id, str):
                raise AuthorizationUnavailable("Keycloak service account client is invalid")
            clients = adapter._get("clients?" + urlencode({"clientId": service_client_id, "first": 0, "max": 3}))
            if not isinstance(clients, list):
                raise AuthorizationUnavailable("Keycloak service account client lookup failed")
            matching = [row for row in clients if isinstance(row, dict)
                        and row.get("clientId") == service_client_id and row.get("id")]
            if len(matching) != 1:
                raise AuthorizationUnavailable("Keycloak service account client is ambiguous")
            linked = adapter._get(f"clients/{quote(str(matching[0]['id']), safe='')}/service-account-user")
            if not isinstance(linked, dict) or not subject or linked.get("id") != subject:
                raise AuthorizationUnavailable("Keycloak service account binding is invalid")
            continue
        attributes = user.get("attributes")
        stable_ids = attributes.get("tr_identity_id") if isinstance(attributes, dict) else None
        if (not subject or not isinstance(stable_ids, list) or len(stable_ids) != 1
                or not isinstance(stable_ids[0], str) or not stable_ids[0].strip()
                or len(stable_ids[0]) > 128):
            raise AuthorizationUnavailable("Keycloak enabled user lacks a stable identity")
        identity = stable_ids[0]
        if identity in subjects or subject in known_subjects:
            raise AuthorizationUnavailable("Keycloak stable identities are ambiguous")
        subjects[identity] = subject
        known_subjects.add(subject)

    members = adapter.group_tree_members("/traderesearch/organizations", max_groups=4096, max_users=20_000)
    org_subjects = {member.subject for member in members if member.enabled}
    if set(subjects.values()) != org_subjects:
        raise AuthorizationUnavailable("Keycloak active user organization coverage differs")
    return subjects


def verified_migration_subjects(adapter, identity_by_principal: dict[str, str]) -> dict[str, str]:
    """Verify reviewed exact aliases against the live Keycloak directory.

    Several names may identify one human (current login plus protected legacy
    name). A second user claiming either name is ambiguous, not another Profile.
    This administrative migration check never grants runtime authorization.
    """
    if (not isinstance(identity_by_principal, dict) or not identity_by_principal
            or any(not isinstance(name, str) or not name or name != name.strip()
                   or not isinstance(stable, str) or not stable or stable != stable.strip()
                   for name, stable in identity_by_principal.items())):
        raise AuthorizationUnavailable("reviewed identities are missing or ambiguous")
    subjects = active_human_subjects(adapter)
    names: dict[str, str] = {}
    for stable, subject in subjects.items():
        user = adapter.user_by_identity_id(stable)
        attrs = user.get("attributes") if isinstance(user, dict) else None
        if (not isinstance(user, dict) or user.get("id") != subject or user.get("enabled") is not True
                or not isinstance(attrs, dict) or attrs.get("tr_identity_id") != [stable]):
            raise AuthorizationUnavailable("Keycloak identity is invalid or ambiguous")
        legacy = attrs.get("legacy_username")
        if legacy is not None and (not isinstance(legacy, list) or len(legacy) != 1
                                   or not isinstance(legacy[0], str) or not legacy[0].strip()):
            raise AuthorizationUnavailable("Keycloak migration username is ambiguous")
        username = user.get("username")
        if not isinstance(username, str) or not username.strip():
            raise AuthorizationUnavailable("Keycloak migration username is ambiguous")
        for name in {username, *(legacy or [])}:
            if name in names and names[name] != stable:
                raise AuthorizationUnavailable("Keycloak migration username is ambiguous")
            names[name] = stable
    if any(names.get(name) != stable for name, stable in identity_by_principal.items()):
        raise AuthorizationUnavailable("Keycloak migration identity differs from reviewed directory or is ambiguous")
    return subjects


