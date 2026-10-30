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
    _protection_request,
    clear_authorization_cache,
    delete_keycloak_resource,
    ensure_keycloak_resource,
    keycloak_authorized_many,
    keycloak_request_identity,
    keycloak_resource_name,
    keycloak_resource_permission,
    keycloak_resource_uri,
    lookup_keycloak_resource,
    protection_token as _protection_token,
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
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("BEGIN")
        return legacy_authorization_snapshot_digest(db)


def legacy_authorization_snapshot_digest(db: sqlite3.Connection) -> str:
    """Hash the authorization rows inside the caller's existing transaction."""
    digest = hashlib.sha256(b"tr-research-legacy-authorization-snapshot-v1\0")
    for table, columns, order in _AUTHORIZATION_TABLES:
        header = json.dumps([table, columns], ensure_ascii=False, separators=(",", ":")).encode()
        digest.update(len(header).to_bytes(8, "big"))
        digest.update(header)
        for row in db.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}"):
            encoded = json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
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
                       resources: Iterable[tuple[str, str, tuple[str, ...]]], *,
                       fresh: bool = False) -> dict[tuple[str, str, str], bool]:
        permissions = []
        for kind, ref, scopes in resources:
            uri, name = keycloak_resource_uri(kind, ref), keycloak_resource_name(kind, ref)
            permissions.extend((uri, name, scope) for scope in scopes)
        result: dict[tuple[str, str, str], bool] = {}
        for offset in range(0, len(permissions), 256):
            batch = permissions[offset:offset + 256]
            if fresh and self._authorize_many is keycloak_authorized_many:
                allowed = self._authorize_many(identity.token, permissions=batch, use_cache=False)
            else:
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
        values = self._decisions_for(identity, [("research", ref, ("read", "use", "manage")) for ref, _status in rows], fresh=True)
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
        return self.report_access_many(viewer=viewer, reports=[(report_id, inherited)])[report_id]

    def report_access_many(self, *, viewer: str | None,
                           reports: Iterable[tuple[str, dict[str, Any] | None]]) -> dict[str, dict[str, Any]]:
        """Evaluate one bounded batch of exact report resources for the user."""
        rows = list(reports)
        identity = self._identity_provider(viewer)
        if identity is None:
            return {ref: _access(ref, False, False, False, "none") for ref, _parent in rows}
        values = self._decisions_for(identity, [("research_report", ref, ("read", "use", "manage"))
                                                for ref, _parent in rows], fresh=True)
        result = {}
        for report_id, inherited in rows:
            uri = keycloak_resource_uri("research_report", report_id)
            direct = _access(report_id, values.get((uri, "read", identity.subject), False),
                             values.get((uri, "use", identity.subject), False),
                             values.get((uri, "manage", identity.subject), False), "report")
            parent = inherited or {}
            result[report_id] = {
                "can_view": bool(direct["can_view"] or parent.get("can_view")),
                "can_preview": bool(direct["can_preview"] or parent.get("can_preview")),
                "can_download": bool(direct["can_download"] or parent.get("can_download")),
                "can_manage": bool(direct["can_manage"] or parent.get("can_manage")),
                "access_basis": (str(parent.get("access_basis")) if parent.get("can_view") else
                                 "owner" if direct["can_manage"] else direct["access_basis"]),
                "object_ref": report_id,
            }
        return result

    def may_write_profile(self, *, research_id: str, viewer: str | None, profile_ref: str) -> bool:
        identity = self._identity_provider(viewer)
        if identity is None:
            return False
        ref = profile_resource_ref(research_id, identity.identity_id, profile_ref)
        uri = keycloak_resource_uri("research_profile", ref)
        values = self._decisions_for(identity, [("research_profile", ref, ("write",))], fresh=True)
        return values.get((uri, "write", identity.subject), False)

    def profile_membership_access_many(
        self, *, viewer: str | None, profiles: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], dict[str, bool]]:
        """Evaluate the caller's exact Profiles with one bounded batch stream.

        Membership grants live on the Profile resource itself, independently
        of explicit Research shares and public/ancestor policies. The caller's
        verified stable ID is always used in the resource reference; supplied
        display names cannot select another user's Profile.
        """
        pairs = list(dict.fromkeys((str(research), str(profile)) for research, profile in profiles))
        identity = self._identity_provider(viewer)
        if identity is None:
            return {pair: {"can_view": False, "can_download": False} for pair in pairs}
        refs = {pair: profile_resource_ref(pair[0], identity.identity_id, pair[1]) for pair in pairs}
        values = self._decisions_for(identity, [
            ("research_profile", ref, ("read", "use")) for ref in refs.values()
        ], fresh=True)
        result = {}
        for pair, ref in refs.items():
            uri = keycloak_resource_uri("research_profile", ref)
            read = values.get((uri, "read", identity.subject), False)
            use = values.get((uri, "use", identity.subject), False)
            result[pair] = {"can_view": bool(read), "can_download": bool(read and use)}
        return result

    def may_write_any_profile(self, *, research_id: str, viewer: str | None,
                              profile_refs: Iterable[str]) -> bool:
        """Batch-check exact Profiles when authoring is not tied to one tab."""
        identity = self._identity_provider(viewer)
        if identity is None:
            return False
        refs = list(dict.fromkeys(profile_resource_ref(research_id, identity.identity_id, str(profile))
                                  for profile in profile_refs))
        values = self._decisions_for(identity, [("research_profile", ref, ("write",)) for ref in refs], fresh=True)
        return any(values.get((keycloak_resource_uri("research_profile", ref), "write", identity.subject), False)
                   for ref in refs)


_USER_GRANT_SCOPES = frozenset({"read", "use", "write"})
_RESOURCE_KINDS = frozenset({"research", "research_report", "research_profile"})


def _keycloak_user(subject: str) -> dict[str, Any]:
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    result = manager_keycloak_admin_adapter()._get(f"users/{quote(subject, safe='')}")
    if (not isinstance(result, dict) or result.get("id") != subject
            or type(result.get("enabled")) is not bool or not result.get("username")):
        raise LookupError("Keycloak grant subject is unavailable")
    return result


def _keycloak_user_by_identity(identity_id: str) -> dict[str, Any]:
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    result = manager_keycloak_admin_adapter().user_by_identity_id(identity_id)
    attrs = result.get("attributes") if isinstance(result, dict) else None
    if (not isinstance(result, dict) or not result.get("id") or not result.get("username")
            or type(result.get("enabled")) is not bool or not isinstance(attrs, dict)
            or attrs.get("tr_identity_id") != [identity_id]):
        raise LookupError("Research grant identity is unavailable or ambiguous")
    return result


def resolve_keycloak_research_member(principal: str) -> dict[str, str]:
    """Resolve one exact legacy/display principal to a stable KC identity.

    The caller's Research share authorization must be checked first. Exact
    post-filtering prevents Keycloak's attribute query syntax from turning a
    supplied name into a broader match. Ambiguity never picks the first user.
    """
    selected = str(principal or "").strip()
    if not selected or len(selected) > 256 or "\x00" in selected:
        raise ValueError("invalid Research principal")
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    adapter = manager_keycloak_admin_adapter()
    direct = adapter.user_representation(selected)
    query = "users?" + urlencode({"q": f"legacy_username:{selected}"})
    rows = adapter._page(query, max_items=20_000)
    if direct is not None:
        rows.append(direct)
    matches: dict[str, dict] = {}
    for row in rows:
        attributes = row.get("attributes") if isinstance(row, dict) else None
        identities = attributes.get("tr_identity_id") if isinstance(attributes, dict) else None
        legacy = attributes.get("legacy_username") if isinstance(attributes, dict) else None
        if not isinstance(identities, list) or len(identities) != 1 or not isinstance(identities[0], str) or not identities[0]:
            continue
        if legacy is not None and (not isinstance(legacy, list) or len(legacy) != 1 or not isinstance(legacy[0], str)):
            raise LookupError("Research member's Keycloak name is ambiguous")
        effective = legacy[0] if legacy else str(row.get("username") or "")
        subject = str(row.get("id") or "")
        if effective == selected and subject:
            matches[subject] = row
    if len(matches) != 1:
        raise LookupError("Research member's Keycloak identity is missing or ambiguous")
    subject, row = next(iter(matches.items()))
    if type(row.get("enabled")) is not bool:
        raise LookupError("Research member's Keycloak status is unavailable")
    stable_id = row["attributes"]["tr_identity_id"][0]
    verified = adapter.user_by_identity_id(stable_id)
    if not isinstance(verified, dict) or verified.get("id") != subject:
        raise LookupError("Research member's stable identity is missing or ambiguous")
    return {"identity_id": stable_id, "subject": subject}


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
                 user_by_identity: Callable = _keycloak_user_by_identity,
                 link_policy_evaluator: Callable | None = None,
                 ensure_resource: Callable = ensure_keycloak_resource,
                 delete_resource: Callable = delete_keycloak_resource,
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
        self.user_by_identity = user_by_identity
        self.link_policy_evaluator = link_policy_evaluator
        self.ensure_resource = ensure_resource
        self.delete_resource = delete_resource
        self.clear_cache = clear_cache

    @staticmethod
    def _rows(result: object) -> list[dict[str, Any]]:
        rows = result if isinstance(result, list) else result.get("permissions") if isinstance(result, dict) else None
        if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
            raise AuthorizationUnavailable("invalid Keycloak policy list")
        return rows

    def _resource(self, settings: dict[str, str], pat: str, resource_type: str,
                  resource_ref: str) -> dict[str, Any]:
        return lookup_keycloak_resource(settings, pat, resource_type, resource_ref, request=self.request)

    def ensure_profile_resource(self, *, actor: str, research_id: str,
                                identity_id: str, profile_ref: str) -> str:
        """Create a Profile's scope without granting its research owner write."""
        ref = profile_resource_ref(research_id, identity_id, profile_ref)
        self.require_membership_manager(actor=actor, research_id=research_id)
        settings = self.settings_provider()
        resource = self._resource(settings, self.token_provider(settings), "research", research_id)
        owners = (resource.get("attributes") or {}).get("traderesearch_owner_subject")
        if not isinstance(owners, list) or len(owners) != 1 or not isinstance(owners[0], str) or not owners[0]:
            raise AuthorizationUnavailable("Research Keycloak owner is unavailable")
        return self.ensure_resource(resource_type="research_profile", resource_ref=ref,
                                    owner_subject=owners[0], owner_scopes=("share",))

    def create_research_resource(self, *, actor: str, research_id: str) -> ResearchRequestIdentity:
        """Register a new random Research identity only for its verified owner."""
        caller = self.identity_provider(actor)
        if caller is None:
            raise PermissionError("Research creation requires a verified Keycloak identity")
        settings = self.settings_provider()
        pat = self.token_provider(settings)
        name = keycloak_resource_name("research", research_id)
        query = urlencode({"name": name, "first": 0, "max": 10, "deep": "true"})
        _, found, _ = self.request(settings, pat, "GET", f"resource_set?{query}")
        rows = found if isinstance(found, list) else found.get("resources", []) if isinstance(found, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise AuthorizationUnavailable("invalid Keycloak Research resource search")
        if any(row.get("name") == name for row in rows):
            raise AuthorizationUnavailable("new Research identity already exists in Keycloak")
        try:
            self.ensure_resource(resource_type="research", resource_ref=research_id, owner_subject=caller.subject)
        except Exception as exc:
            # The create request may have succeeded before an owner-policy
            # response failed. The exact random resource was verified absent
            # above; remove only a matching resource owned by this subject.
            try:
                self.delete_resource(resource_type="research", resource_ref=research_id,
                                     owner_subject=caller.subject)
            except Exception:
                raise RuntimeError(f"Research Keycloak resource needs cleanup: {research_id}") from exc
            raise
        return caller

    def require_membership_manager(self, *, actor: str, research_id: str) -> None:
        """Require current Research share permission before creating an intent."""
        caller = self.identity_provider(actor)
        self.clear_cache()
        if caller is None or not self.may_share(caller.token, resource_type="research",
                                                 resource_ref=research_id, scope="share"):
            raise PermissionError("Keycloak did not authorize Research sharing")

    def require_resource_share(self, *, actor: str, resource_type: str, resource_ref: str) -> None:
        if resource_type not in {"research", "research_report"}:
            raise ValueError("unsupported Research sharing target")
        caller = self.identity_provider(actor)
        self.clear_cache()
        if caller is None or not self.may_share(caller.token, resource_type=resource_type,
                                                 resource_ref=resource_ref, scope="share"):
            raise PermissionError("Keycloak did not authorize sharing this resource")

    def require_link_issuer_share(self, *, identity_id: str, subject: str,
                                  research_id: str, resource_type: str, resource_ref: str) -> None:
        """Evaluate a link issuer's *current* share scope in its home realm.

        The link carries the stable identity and exact subject recorded when a
        verified user created it. This is an administrative evaluation of that
        principal, not an end-user session or a username-based impersonation.
        """
        if resource_type not in {"research", "research_report"}:
            raise ValueError("unsupported Research sharing target")
        try:
            user = self.user_by_identity(identity_id)
        except (LookupError, AuthorizationUnavailable):
            raise
        except Exception as exc:
            raise AuthorizationUnavailable("Research link issuer lookup is unavailable") from exc
        attrs = user.get("attributes") if isinstance(user, dict) else None
        if (not isinstance(user, dict) or user.get("enabled") is not True
                or user.get("id") != subject or not isinstance(attrs, dict)
                or attrs.get("tr_identity_id") != [identity_id]):
            raise PermissionError("Research link issuer identity is unavailable")
        try:
            if self.link_policy_evaluator is None:
                from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator
                evaluator = KeycloakPolicyEvaluator(allowed_kinds={"research", "research_report"},
                                                    allowed_scopes={"read", "manage", "share"})
            else:
                evaluator = self.link_policy_evaluator()
            decisions = evaluator.evaluate(identity_id, candidates=[
                ("research", research_id, ("read", "manage")),
                (resource_type, resource_ref, ("share",)),
            ])
        except (LookupError, ValueError, AuthorizationUnavailable):
            raise
        except Exception as exc:
            raise AuthorizationUnavailable("Research link issuer authorization is unavailable") from exc
        if any(decisions.get(candidate) is not True for candidate in (
                ("research", research_id, "read"), ("research", research_id, "manage"),
                (resource_type, resource_ref, "share"))):
            raise PermissionError("Keycloak no longer authorizes the Research link issuer")

    def list_user_grants(self, *, actor: str, resource_type: str, resource_ref: str) -> list[dict[str, Any]]:
        """List explicit user grants from Keycloak, not the old ACL column."""
        self.require_resource_share(actor=actor, resource_type=resource_type, resource_ref=resource_ref)
        settings = self.settings_provider()
        pat = self.token_provider(settings)
        resource = self._resource(settings, pat, resource_type, resource_ref)
        resource_id = str(resource.get("_id") or resource.get("id"))
        resource_name = keycloak_resource_name(resource_type, resource_ref)
        result, seen = [], set()
        for policy in self._resource_policies(settings, pat, resource_id):
            try:
                description = json.loads(policy.get("description") or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(description, dict) or description.get("schema") != "tr-research-grant-v1" or description.get("source") != "explicit":
                continue
            stable = str(description.get("identity_id") or "").strip()
            if not stable or stable in seen:
                raise AuthorizationUnavailable("Research explicit grants are invalid or ambiguous")
            expected_hash = hashlib.sha256(json.dumps(["explicit", stable], ensure_ascii=False,
                                                     separators=(",", ":")).encode()).hexdigest()
            user = self.user_by_identity(stable)
            scopes, users = policy.get("scopes"), policy.get("users")
            if (policy.get("name") != f"{resource_name}:grant:{expected_hash}"
                    or not isinstance(scopes, list) or any(scope not in _USER_GRANT_SCOPES for scope in scopes)
                    or not isinstance(users, list) or len(users) != 1
                    or users[0] not in {str(user.get("id") or ""), str(user.get("username") or "")}
                    or any(policy.get(key) for key in ("roles", "groups", "clients"))
                    or str(policy.get("logic") or "POSITIVE") != "POSITIVE"):
                raise AuthorizationUnavailable("Research explicit grant conflicts with Keycloak")
            seen.add(stable)
            result.append({"identity_id": stable, "subject": str(user["id"]),
                           "username": str(user["username"]), "enabled": bool(user["enabled"]),
                           "scopes": sorted(set(scopes))})
        return sorted(result, key=lambda row: (row["username"].casefold(), row["identity_id"]))

    def _resource_policies(self, settings, pat, resource_id):
        rows = []
        for offset in range(0, 5000, 100):
            query = urlencode({"resource": resource_id, "first": offset, "max": 100})
            _, result, _ = self.request(settings, pat, "GET", f"uma-policy?{query}")
            page = self._rows(result)
            rows.extend(page)
            if len(page) < 100:
                return rows
        raise AuthorizationUnavailable("Research policy list exceeds its budget")

    def report_registration_identity(self, *, actor: str, research_id: str) -> ResearchRequestIdentity:
        """Require a live Research sharing decision and the real request identity."""
        caller = self.identity_provider(actor)
        self.require_membership_manager(actor=actor, research_id=research_id)
        if caller is None:
            raise PermissionError("report registration requires a verified Keycloak identity")
        return caller

    def ensure_new_report_resource(self, *, actor: str, research_id: str, report_id: str,
                                   creation_intent: str) -> ResearchRequestIdentity:
        """Resume only the exact pending creation; never adopt a foreign resource."""
        caller = self.report_registration_identity(actor=actor, research_id=research_id)
        self.ensure_resource(resource_type="research_report", resource_ref=report_id,
                             owner_subject=caller.subject, creation_intent=creation_intent)
        return caller

    def require_report_resource(self, *, actor: str, research_id: str, report_id: str) -> None:
        """Existing reports must already have an authorized, matching resource."""
        caller = self.report_registration_identity(actor=actor, research_id=research_id)
        settings = self.settings_provider()
        resource = self._resource(settings, self.token_provider(settings), "research_report", report_id)
        if (resource.get("attributes") or {}).get("traderesearch_owner_subject") != [caller.subject]:
            raise AuthorizationUnavailable("Research report Keycloak owner does not match")
        self.clear_cache()
        if not self.may_share(caller.token, resource_type="research_report", resource_ref=report_id,
                              scope="manage"):
            raise PermissionError("Keycloak did not authorize Research report management")

    def set_user_grant(self, *, actor: str, resource_type: str, resource_ref: str,
                       source: str, identity_id: str, subject: str,
                       scopes: Iterable[str]) -> bool:
        """Create, update or revoke a specific grant; return whether it changed."""
        normalized_scopes = self._validate_grant(resource_type, source, identity_id, subject, scopes)
        caller = self.identity_provider(actor)
        # A grant or revocation is an infrequent administrative action; do
        # not rely on the short-lived cache when checking the caller's rights.
        self.clear_cache()
        if caller is None or not self.may_share(caller.token, resource_type=resource_type,
                                                 resource_ref=resource_ref, scope="share"):
            raise PermissionError("Keycloak did not authorize Research sharing")
        return self._reconcile_user_grant(resource_type=resource_type, resource_ref=resource_ref,
                                          source=source, identity_id=identity_id, subject=subject,
                                          scopes=normalized_scopes)

    @staticmethod
    def _validate_grant(resource_type: str, source: str, identity_id: str, subject: str,
                        scopes: Iterable[str]) -> list[str]:
        if resource_type not in _RESOURCE_KINDS:
            raise ValueError("unsupported Research resource type")
        source, identity_id, subject = (str(v or "").strip() for v in (source, identity_id, subject))
        if any(not v or len(v) > 512 or "\x00" in v for v in (source, identity_id, subject)):
            raise ValueError("grant source and stable/Keycloak identities are required")
        normalized_scopes = sorted(set(scopes))
        if any(scope not in _USER_GRANT_SCOPES for scope in normalized_scopes):
            raise ValueError("Research user grants cannot delegate administration")
        return normalized_scopes

    def _reconcile_user_grant(self, *, resource_type: str, resource_ref: str,
                              source: str, identity_id: str, subject: str,
                              scopes: Iterable[str], require_identical: bool = False) -> bool:
        """Reconcile a grant after caller authorization or guarded offline migration."""
        normalized_scopes = self._validate_grant(resource_type, source, identity_id, subject, scopes)
        source, identity_id, subject = (str(v or "").strip() for v in (source, identity_id, subject))
        # Resolve both local Keycloak subject and its username; Keycloak may
        # return either representation in a policy. Never infer a subject from
        # a display name or legacy owner reference.
        user = self.user_provider(subject)
        attributes = user.get("attributes") if isinstance(user, dict) else None
        if (not isinstance(user, dict) or str(user.get("id") or "") != subject or not user.get("username")
                or (bool(normalized_scopes) and user.get("enabled") is not True)
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
            found_rows = [row for row in self._resource_policies(settings, pat, resource_id)
                          if row.get("name") == policy_name]
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
            if require_identical:
                raise AuthorizationUnavailable("Research migration grant conflicts with existing scopes")
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

    def set_profile_membership(self, *, actor: str, research_id: str,
                               identity_id: str, subject: str, profile_ref: str,
                               role: str, status: str) -> bool:
        """Update exactly one Profile membership policy; no Research grant copy."""
        if role not in {"owner", "editor", "contributor", "viewer"}:
            raise ValueError("invalid Research Profile role")
        if status not in {"active", "invited", "revoked"}:
            raise ValueError("invalid Research Profile status")
        scopes = []
        if status == "active":
            scopes = ["read", "use"]
            if role in {"owner", "editor", "contributor"}:
                scopes.append("write")
        self.ensure_profile_resource(actor=actor, research_id=research_id,
                                     identity_id=identity_id, profile_ref=profile_ref)
        return self.set_user_grant(
            actor=actor, resource_type="research_profile",
            resource_ref=profile_resource_ref(research_id, identity_id, profile_ref),
            source="membership", identity_id=identity_id, subject=subject, scopes=scopes,
        )
