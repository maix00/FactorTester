"""Keycloak authorization primitives for Research and its Profile writers.

Legacy catalog membership and sharing fields are migration input, not an
authorization source for this adapter.  It evaluates only an already verified
Keycloak request, with decisions made by the existing UMA resource server.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlencode

from server.identity.keycloak_authorization import (
    AuthorizationUnavailable,
    _backchannel,
    _protection_request,
    clear_authorization_cache,
    ensure_keycloak_resource,
    keycloak_authorized_many,
    keycloak_request_identity,
    keycloak_resource_name,
    keycloak_resource_permission,
    keycloak_resource_uri,
)


# Each field is part of the old authorization decision or share-link state.
# SQL identifiers here are fixed program constants, never user input.
_AUTHORIZATION_TABLES = (
    ("research_catalog_researches", ("research_id", "owner_ref", "status", "visibility", "authorized_users_json"),
     "research_id"),
    ("research_catalog_reports", ("report_id", "research_id", "owner_ref", "status", "visibility", "authorized_users_json"),
     "report_id"),
    ("research_catalog_memberships", ("research_id", "principal_ref", "profile_ref", "role", "status"),
     "research_id, principal_ref, profile_ref"),
    ("research_catalog_share_links", ("link_id", "target_kind", "research_id", "report_id", "owner_ref", "token_hash",
                                     "mode", "expires_at", "redeemed_by", "redeemed_at", "revoked_at"),
     "link_id"),
)


def legacy_authorization_snapshot_sha256(database: str | Path) -> str:
    """Fingerprint one consistent, read-only snapshot without loading its rows.

    Length-delimited JSON and fixed table/column order avoid ambiguous joins.
    The digest is a cutover guard, not an authorization decision or ACL store.
    """
    uri = Path(database).expanduser().resolve().as_uri() + "?mode=ro"
    digest = hashlib.sha256(b"tr-research-legacy-authorization-snapshot-v1\0")
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("BEGIN")
        for table, columns, order in _AUTHORIZATION_TABLES:
            header = json.dumps([table, columns], ensure_ascii=False, separators=(",", ":")).encode()
            digest.update(len(header).to_bytes(8, "big"))
            digest.update(header)
            for row in db.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}"):
                encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
    return digest.hexdigest()


def profile_resource_ref(research_id: str, identity_id: str, profile_ref: str) -> str:
    """Use the cross-Manager stable user ID, not username or local KC subject."""
    fields = tuple(str(value or "").strip() for value in (research_id, identity_id, profile_ref))
    if any(not value or len(value) > 512 or "\x00" in value for value in fields):
        raise ValueError("research, stable identity and Profile references are required")
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ResearchRequestIdentity:
    token: str = field(repr=False, compare=False)
    issuer: str
    subject: str
    username: str
    identity_id: str


def verified_research_request(viewer: str | None) -> ResearchRequestIdentity | None:
    """Bind the stable ID to the same verified session as the UMA token."""
    identity = keycloak_request_identity()
    if identity is None or not viewer or identity.username != viewer:
        return None
    try:
        from flask import g, has_request_context
        if has_request_context():
            session = getattr(g, "keycloak_user_session", None)
        else:
            from server.identity.request_context import current_verified_identity
            context = current_verified_identity()
            session = context[1] if context and context[0] == identity.token else None
    except ImportError:
        return None
    if not isinstance(session, dict):
        return None
    stable_id = str(session.get("tr_identity_id") or "").strip()
    if (not stable_id or str(session.get("keycloak_subject") or "") != identity.subject
            or str(session.get("keycloak_issuer") or "") != identity.issuer
            or str(session.get("username") or "") != identity.username):
        return None
    return ResearchRequestIdentity(identity.token, identity.issuer, identity.subject,
                                   identity.username, stable_id)


def _access(ref: str, read: bool, use: bool, manage: bool, basis: str) -> dict[str, Any]:
    return {"can_view": read, "can_preview": read, "can_download": read and use,
            "can_manage": read and manage, "access_basis": basis if read else "none", "object_ref": ref}


class KeycloakResearchAuthorization:
    """Batched Keycloak checks with no username/owner or local-membership bypass."""

    def __init__(self, *, identity_provider: Callable = verified_research_request,
                 authorize_many: Callable = keycloak_authorized_many) -> None:
        self._identity_provider = identity_provider
        self._authorize_many = authorize_many

    def decisions(self, viewer: str | None,
                  resources: Iterable[tuple[str, str, tuple[str, ...]]]) -> dict[tuple[str, str, str], bool]:
        identity = self._identity_provider(viewer)
        if identity is None:
            return {}
        return self._decisions_for(identity, resources)

    def _decisions_for(self, identity: ResearchRequestIdentity,
                       resources: Iterable[tuple[str, str, tuple[str, ...]]]) -> dict[tuple[str, str, str], bool]:
        permissions = []
        for kind, ref, scopes in resources:
            uri, name = keycloak_resource_uri(kind, ref), keycloak_resource_name(kind, ref)
            permissions.extend((uri, name, scope) for scope in scopes)
        result: dict[tuple[str, str, str], bool] = {}
        for offset in range(0, len(permissions), 256):
            batch = permissions[offset:offset + 256]
            allowed = self._authorize_many(identity.token, permissions=batch)
            for uri, _name, scope in batch:
                result[(uri, scope, identity.subject)] = bool(allowed.get((uri, scope), False))
        return result

    def research_access(self, *, research_id: str, status: str, viewer: str | None) -> dict[str, Any]:
        return self.research_access_many(viewer=viewer, researches=[(research_id, status)])[research_id]

    def research_access_many(self, *, viewer: str | None,
                             researches: Iterable[tuple[str, str]]) -> dict[str, dict[str, Any]]:
        rows = list(researches)
        identity = self._identity_provider(viewer)
        if identity is None:
            return {ref: _access(ref, False, False, False, "none") for ref, _status in rows}
        values = self._decisions_for(identity, [("research", ref, ("read", "use", "manage")) for ref, _status in rows])
        result = {}
        for research_id, status in rows:
            uri = keycloak_resource_uri("research", research_id)
            read = values.get((uri, "read", identity.subject), False)
            manage = values.get((uri, "manage", identity.subject), False)
            if status not in {"active", "archived"} or (status == "archived" and not manage):
                read = False
            result[research_id] = _access(research_id, read, values.get((uri, "use", identity.subject), False),
                                           manage, "owner" if manage else "research")
        return result

    def report_access(self, *, report_id: str, viewer: str | None,
                      inherited: dict[str, Any] | None = None) -> dict[str, Any]:
        identity = self._identity_provider(viewer)
        if identity is None:
            return _access(report_id, False, False, False, "none")
        uri = keycloak_resource_uri("research_report", report_id)
        values = self._decisions_for(identity, [("research_report", report_id, ("read", "use", "manage"))])
        direct = _access(report_id, values.get((uri, "read", identity.subject), False),
                         values.get((uri, "use", identity.subject), False),
                         values.get((uri, "manage", identity.subject), False), "report")
        parent = inherited or {}
        return {
            "can_view": bool(direct["can_view"] or parent.get("can_view")),
            "can_preview": bool(direct["can_preview"] or parent.get("can_preview")),
            "can_download": bool(direct["can_download"] or parent.get("can_download")),
            "can_manage": bool(direct["can_manage"] or parent.get("can_manage")),
            "access_basis": (str(parent.get("access_basis")) if parent.get("can_view") else
                             "owner" if direct["can_manage"] else direct["access_basis"]),
            "object_ref": report_id,
        }

    def may_write_profile(self, *, research_id: str, viewer: str | None, profile_ref: str) -> bool:
        identity = self._identity_provider(viewer)
        if identity is None:
            return False
        ref = profile_resource_ref(research_id, identity.identity_id, profile_ref)
        uri = keycloak_resource_uri("research_profile", ref)
        values = self._decisions_for(identity, [("research_profile", ref, ("write",))])
        return values.get((uri, "write", identity.subject), False)


_USER_GRANT_SCOPES = frozenset({"read", "use", "write"})
_RESOURCE_KINDS = frozenset({"research", "research_report", "research_profile"})


def _protection_token(settings: dict[str, str]) -> str:
    from server.identity.keycloak import ServiceOIDCClient
    client = ServiceOIDCClient(_backchannel(settings), settings["realm"], settings["authz_client_id"],
                               client_secret=settings["authz_client_secret"], timeout=3.0)
    token = str(client.client_credentials().get("access_token") or "")
    if not token:
        raise AuthorizationUnavailable("Keycloak did not issue a Protection API token")
    return token


def _keycloak_user(subject: str) -> dict[str, Any]:
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    result = manager_keycloak_admin_adapter()._get(f"users/{quote(subject, safe='')}")
    if (not isinstance(result, dict) or result.get("id") != subject
            or result.get("enabled") is not True or not result.get("username")):
        raise LookupError("Keycloak grant subject is unavailable")
    return result


class KeycloakResearchGrantManager:
    """Manage one independently revocable user grant via Keycloak UMA.

    The caller must already possess Keycloak's ``share`` scope. Sources such
    as an explicit grant and each Profile membership have distinct policies,
    so revoking one does not revoke another. This primitive does not manage
    link redemption or dynamic hierarchy rules.
    """

    def __init__(self, *, identity_provider: Callable = verified_research_request,
                 may_share: Callable = keycloak_resource_permission,
                 settings_provider: Callable | None = None,
                 token_provider: Callable = _protection_token,
                 request: Callable = _protection_request,
                 user_provider: Callable = _keycloak_user,
                 ensure_resource: Callable = ensure_keycloak_resource,
                 clear_cache: Callable = clear_authorization_cache) -> None:
        if settings_provider is None:
            from server.identity.user_session import oidc_settings
            settings_provider = oidc_settings
        self.identity_provider = identity_provider
        self.may_share = may_share
        self.settings_provider = settings_provider
        self.token_provider = token_provider
        self.request = request
        self.user_provider = user_provider
        self.ensure_resource = ensure_resource
        self.clear_cache = clear_cache

    @staticmethod
    def _rows(result: object) -> list[dict[str, Any]]:
        rows = result if isinstance(result, list) else result.get("permissions") if isinstance(result, dict) else None
        if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
            raise AuthorizationUnavailable("invalid Keycloak policy list")
        return rows

    def _resource(self, settings: dict[str, str], pat: str, resource_type: str,
                  resource_ref: str) -> dict[str, Any]:
        resource_name = keycloak_resource_name(resource_type, resource_ref)
        resource_uri = keycloak_resource_uri(resource_type, resource_ref)
        query = urlencode({"name": resource_name, "first": 0, "max": 10, "deep": "true"})
        _, found, _ = self.request(settings, pat, "GET", f"resource_set?{query}")
        rows = found if isinstance(found, list) else found.get("resources", []) if isinstance(found, dict) else []
        matches = [row for row in rows if isinstance(row, dict) and row.get("name") == resource_name]
        if len(matches) != 1:
            raise AuthorizationUnavailable("Research Keycloak resource is missing or ambiguous")
        resource_id = str(matches[0].get("_id") or matches[0].get("id") or "")
        uris = matches[0].get("uris") or ([matches[0].get("uri")] if matches[0].get("uri") else [])
        if not resource_id or resource_uri not in uris:
            raise AuthorizationUnavailable("Research Keycloak resource identity changed")
        return matches[0]

    def ensure_profile_resource(self, *, actor: str, research_id: str,
                                identity_id: str, profile_ref: str) -> str:
        """Create a Profile's scope without granting its research owner write."""
        ref = profile_resource_ref(research_id, identity_id, profile_ref)
        caller = self.identity_provider(actor)
        self.clear_cache()
        if caller is None or not self.may_share(caller.token, resource_type="research",
                                                 resource_ref=research_id, scope="share"):
            raise PermissionError("Keycloak did not authorize Research sharing")
        settings = self.settings_provider()
        resource = self._resource(settings, self.token_provider(settings), "research", research_id)
        owners = (resource.get("attributes") or {}).get("traderesearch_owner_subject")
        if not isinstance(owners, list) or len(owners) != 1 or not isinstance(owners[0], str) or not owners[0]:
            raise AuthorizationUnavailable("Research Keycloak owner is unavailable")
        return self.ensure_resource(resource_type="research_profile", resource_ref=ref,
                                    owner_subject=owners[0], owner_scopes=("share",))

    def set_user_grant(self, *, actor: str, resource_type: str, resource_ref: str,
                       source: str, identity_id: str, subject: str,
                       scopes: Iterable[str]) -> bool:
        """Create, update or revoke a specific grant; return whether it changed."""
        if resource_type not in _RESOURCE_KINDS:
            raise ValueError("unsupported Research resource type")
        source, identity_id, subject = (str(v or "").strip() for v in (source, identity_id, subject))
        if any(not v or len(v) > 512 or "\x00" in v for v in (source, identity_id, subject)):
            raise ValueError("grant source and stable/Keycloak identities are required")
        normalized_scopes = sorted(set(scopes))
        if any(scope not in _USER_GRANT_SCOPES for scope in normalized_scopes):
            raise ValueError("Research user grants cannot delegate administration")
        caller = self.identity_provider(actor)
        # A grant or revocation is an infrequent administrative action; do
        # not rely on the short-lived cache when checking the caller's rights.
        self.clear_cache()
        if caller is None or not self.may_share(caller.token, resource_type=resource_type,
                                                 resource_ref=resource_ref, scope="share"):
            raise PermissionError("Keycloak did not authorize Research sharing")
        # Resolve both local Keycloak subject and its username; Keycloak may
        # return either representation in a policy. Never infer a subject from
        # a display name or legacy owner reference.
        user = self.user_provider(subject)
        attributes = user.get("attributes")
        if (str(user.get("id") or "") != subject or not user.get("username") or user.get("enabled") is not True
                or not isinstance(attributes, dict) or attributes.get("tr_identity_id") != [identity_id]):
            raise LookupError("Keycloak grant subject is unavailable")
        labels = {subject, str(user["username"])}
        settings = self.settings_provider()
        pat = self.token_provider(settings)
        resource_name = keycloak_resource_name(resource_type, resource_ref)
        resource = self._resource(settings, pat, resource_type, resource_ref)
        resource_id = str(resource.get("_id") or resource.get("id"))
        policy_hash = hashlib.sha256(json.dumps([source, identity_id], ensure_ascii=False,
                                                separators=(",", ":")).encode()).hexdigest()
        policy_name = f"{resource_name}:grant:{policy_hash}"
        description = json.dumps({"schema": "tr-research-grant-v1", "source": source,
                                  "identity_id": identity_id}, ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":"))

        def matching_policies() -> list[dict[str, Any]]:
            found_rows: list[dict[str, Any]] = []
            for offset in range(0, 5000, 100):
                query = urlencode({"resource": resource_id, "first": offset, "max": 100})
                _, result, _ = self.request(settings, pat, "GET", f"uma-policy?{query}")
                page = self._rows(result)
                found_rows.extend(row for row in page if row.get("name") == policy_name)
                if len(page) < 100:
                    break
            else:
                raise AuthorizationUnavailable("Research policy list exceeds its budget")
            if len(found_rows) > 1:
                raise AuthorizationUnavailable("duplicate Research Keycloak grants")
            return found_rows

        existing = matching_policies()
        if existing:
            policy = existing[0]
            policy_id = str(policy.get("id") or "")
            users = policy.get("users")
            previous_scopes = policy.get("scopes")
            if (not policy_id or policy.get("description") != description
                    or not isinstance(users, list) or len(users) != 1 or users[0] not in labels
                    or not isinstance(previous_scopes, list) or any(s not in _USER_GRANT_SCOPES for s in previous_scopes)
                    or any(policy.get(key) for key in ("roles", "groups", "clients"))
                    or str(policy.get("logic") or "POSITIVE") != "POSITIVE"):
                raise AuthorizationUnavailable("Research grant conflicts with existing Keycloak policy")
            if sorted(previous_scopes) == normalized_scopes:
                return False
        elif not normalized_scopes:
            return False
        else:
            policy_id = ""

        payload = {"name": policy_name, "description": description, "users": [subject],
                   "scopes": normalized_scopes, "logic": "POSITIVE"}
        if not normalized_scopes:
            self.request(settings, pat, "DELETE", f"uma-policy/{quote(policy_id, safe='')}")
        elif policy_id:
            self.request(settings, pat, "PUT", f"uma-policy/{quote(policy_id, safe='')}", payload)
        else:
            self.request(settings, pat, "POST", f"uma-policy/{quote(resource_id, safe='')}", payload)
        confirmed = matching_policies()
        if normalized_scopes:
            if (len(confirmed) != 1 or confirmed[0].get("description") != description
                    or sorted(confirmed[0].get("scopes") or []) != normalized_scopes
                    or len(confirmed[0].get("users") or []) != 1
                    or confirmed[0]["users"][0] not in labels
                    or any(confirmed[0].get(key) for key in ("roles", "groups", "clients"))
                    or str(confirmed[0].get("logic") or "POSITIVE") != "POSITIVE"):
                raise AuthorizationUnavailable("Research Keycloak grant update was not confirmed")
        elif confirmed:
            raise AuthorizationUnavailable("Research Keycloak grant revocation was not confirmed")
        self.clear_cache()
        return True
