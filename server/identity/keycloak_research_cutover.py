"""Read-only Keycloak evaluation for Research migration parity checks.

This is an administrative verification tool, never a request authorization
shortcut. It does not create sessions or pretend to be the evaluated user.
The browser/UMA and transfer paths must be tested independently at cutover.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from collections.abc import Iterable
from itertools import chain
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import Request

from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.keycloak_research import (
    KeycloakResearchGrantManager, _protection_token,
    legacy_authorization_snapshot_sha256, profile_resource_ref,
)


_KINDS = frozenset({"research", "research_report", "research_profile"})
_SCOPES = frozenset({"read", "use", "write", "manage", "share", "delete", "publish"})
_BATCH_RESOURCES = 32
_MAX_RESOURCES = 20_000
_RESPONSE_LIMIT = 2 * 1024 * 1024
_ALL_SCOPES = tuple(sorted(_SCOPES))


def _policy_evaluation_request(adapter, client_uuid: str, payload: dict[str, Any]) -> dict[str, Any]:
    from server.manager.domain.federation_transport import FederationTransport

    request = Request(
        f"{adapter.base_url}/admin/realms/{quote(adapter.realm, safe='')}/clients/"
        f"{quote(client_uuid, safe='')}/authz/resource-server/policy/evaluate",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {adapter._token()}", "Content-Type": "application/json"},
    )
    with FederationTransport().open(request, timeout=adapter.timeout) as response:
        raw = response.read(_RESPONSE_LIMIT + 1)
    if len(raw) > _RESPONSE_LIMIT:
        raise AuthorizationUnavailable("Keycloak evaluation response exceeds budget")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise AuthorizationUnavailable("Keycloak evaluation response is invalid")
    return result


class KeycloakResearchPolicyEvaluator:
    """Evaluate a complete Research resource/scope set for one real user.

    Resource IDs are resolved against the real Protection API once per
    evaluator, while decisions are fetched afresh for each subject. Results
    include explicit denials so callers cannot confuse a missing response with
    an evaluated denial. The object should be used only for a bounded cutover
    audit; it is not a cross-request authorization cache.
    """

    def __init__(self, *, adapter=None, settings: dict[str, str] | None = None,
                 protection_token: str | None = None,
                 resource_lookup: Callable | None = None,
                 request: Callable = _policy_evaluation_request) -> None:
        if adapter is None:
            from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
            adapter = manager_keycloak_admin_adapter()
        if settings is None:
            from server.identity.user_session import oidc_settings
            settings = oidc_settings()
        self.adapter, self.settings, self.request = adapter, settings, request
        self._token = protection_token or _protection_token(settings)
        grant_manager = KeycloakResearchGrantManager(settings_provider=lambda: settings)
        self._lookup = resource_lookup or grant_manager._resource
        self._resolved: dict[tuple[str, str], str] = {}
        self._resource_ids: set[str] = set()
        client_id = str(settings.get("authz_client_id") or "").strip()
        if not client_id:
            raise AuthorizationUnavailable("Keycloak resource client is not configured")
        rows = adapter._get("clients?" + urlencode({"clientId": client_id, "first": 0, "max": 3}))
        matches = [row for row in rows if isinstance(row, dict) and row.get("clientId") == client_id]
        if len(matches) != 1 or not matches[0].get("id"):
            raise AuthorizationUnavailable("Keycloak resource client is missing or ambiguous")
        self._client_uuid = str(matches[0]["id"])

    def _resource_id(self, kind: str, ref: str) -> str:
        key = (kind, ref)
        if key not in self._resolved:
            row = self._lookup(self.settings, self._token, kind, ref)
            identifier = str(row.get("_id") or row.get("id") or "").strip()
            if not identifier:
                raise AuthorizationUnavailable("Keycloak Research resource has no ID")
            if identifier in self._resource_ids:
                raise AuthorizationUnavailable("Keycloak Research resources do not have distinct IDs")
            self._resolved[key] = identifier
            self._resource_ids.add(identifier)
        return self._resolved[key]

    def evaluate(self, identity_id: str, *,
                 candidates: Iterable[tuple[str, str, tuple[str, ...]]]) -> dict[tuple[str, str, str], bool]:
        stable = str(identity_id or "").strip()
        if not stable or len(stable) > 128:
            raise ValueError("stable identity is required")
        user = self.adapter.user_by_identity_id(stable)
        attrs = user.get("attributes") if isinstance(user, dict) else None
        subject = str(user.get("id") or "") if isinstance(user, dict) else ""
        if (not subject or user.get("enabled") is not True or not isinstance(attrs, dict)
                or attrs.get("tr_identity_id") != [stable]):
            raise AuthorizationUnavailable("Keycloak audit identity is unavailable or ambiguous")

        requested: dict[tuple[str, str], set[str]] = {}
        for kind, ref, scopes in candidates:
            kind, ref = str(kind or "").strip(), str(ref or "").strip()
            scope_set = set(scopes)
            if (kind not in _KINDS or not ref or len(ref) > 2048 or not scope_set
                    or any(scope not in _SCOPES for scope in scope_set)):
                raise ValueError("invalid Research authorization candidate")
            requested.setdefault((kind, ref), set()).update(scope_set)
            if len(requested) > _MAX_RESOURCES:
                raise ValueError("Research authorization audit exceeds its resource budget")

        records = [(kind, ref, sorted(scopes), self._resource_id(kind, ref))
                   for (kind, ref), scopes in sorted(requested.items())]
        decisions: dict[tuple[str, str, str], bool] = {}
        # Keycloak can omit denied scopes when the same resource has multiple
        # requested scopes and at least one is permitted. Evaluate one scope
        # per resource, while still batching distinct resources in each call.
        for scope in sorted(_SCOPES):
            scoped = [(kind, ref, resource_id) for kind, ref, scopes, resource_id in records if scope in scopes]
            for offset in range(0, len(scoped), _BATCH_RESOURCES):
                batch = scoped[offset:offset + _BATCH_RESOURCES]
                by_id = {resource_id: (kind, ref) for kind, ref, resource_id in batch}
                payload = {"userId": subject, "resources": [
                    {"_id": resource_id, "scopes": [{"name": scope}]}
                    for _kind, _ref, resource_id in batch
                ]}
                response = self.request(self.adapter, self._client_uuid, payload)
                rows = response.get("results") if isinstance(response, dict) else None
                if not isinstance(rows, list) or len(rows) != len(batch):
                    raise AuthorizationUnavailable("Keycloak evaluation omitted Research resources")
                seen: set[str] = set()
                for row in rows:
                    resource = row.get("resource") if isinstance(row, dict) else None
                    resource_id = str(resource.get("_id") or resource.get("id") or "") if isinstance(resource, dict) else ""
                    if resource_id not in by_id or resource_id in seen:
                        raise AuthorizationUnavailable("Keycloak evaluation returned an unexpected resource")
                    seen.add(resource_id)
                    kind, ref = by_id[resource_id]
                    scopes = row.get("scopes")
                    allowed = row.get("allowedScopes")
                    if (not isinstance(scopes, list) or not isinstance(allowed, list)
                            or any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
                                   for item in [*scopes, *allowed])):
                        raise AuthorizationUnavailable("Keycloak evaluation omitted scope decisions")
                    actual_scopes = [item["name"] for item in scopes]
                    allowed_scopes = [item["name"] for item in allowed]
                    status = str(row.get("status") or "")
                    if (actual_scopes != [scope] or allowed_scopes not in ([], [scope])
                            or status not in {"PERMIT", "DENY"}
                            or (status == "PERMIT") != bool(allowed_scopes)):
                        raise AuthorizationUnavailable("Keycloak evaluation scope set changed")
                    decisions[(kind, ref, scope)] = bool(allowed_scopes)
        return decisions


def compare_research_decisions(expected: dict[tuple[str, str, str], bool],
                               actual: dict[tuple[str, str, str], bool]) -> None:
    """Require equal, complete allow/deny sets; never print protected refs."""
    if set(expected) != set(actual):
        raise AuthorizationUnavailable("Research authorization coverage differs")
    if any(type(value) is not bool for value in chain(expected.values(), actual.values())):
        raise ValueError("Research authorization decisions must be booleans")
    if any(expected[key] != actual[key] for key in expected):
        raise AuthorizationUnavailable("Research authorization decisions differ")


def research_candidate_universe(database: str | Path, *,
                                identity_by_principal: dict[str, str]) -> list[tuple[str, str, tuple[str, ...]]]:
    """Derive the complete policy comparison universe from the real catalog.

    Old identities remain required for Profile resource identity even when a
    human account has been removed. Mapping an orphan to a system owner is a
    separate reviewed migration decision; this function never guesses one.
    """
    uri = Path(database).expanduser().resolve().as_uri() + "?mode=ro"
    result: set[tuple[str, str, tuple[str, ...]]] = set()
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("BEGIN")
        for research_id, owner, authorized in db.execute(
            "SELECT research_id, owner_ref, authorized_users_json FROM research_catalog_researches ORDER BY research_id"
        ):
            _verify_legacy_principals(owner, authorized, identity_by_principal)
            result.add(("research", str(research_id), _ALL_SCOPES))
        for report_id, owner, authorized in db.execute(
            "SELECT report_id, owner_ref, authorized_users_json FROM research_catalog_reports ORDER BY report_id"
        ):
            _verify_legacy_principals(owner, authorized, identity_by_principal)
            result.add(("research_report", str(report_id), _ALL_SCOPES))
        for research_id, principal, profile_ref in db.execute(
            "SELECT research_id, principal_ref, profile_ref FROM research_catalog_memberships "
            "ORDER BY research_id, principal_ref, profile_ref"
        ):
            stable = identity_by_principal.get(str(principal))
            if not stable:
                raise AuthorizationUnavailable("unmapped Research Profile principal blocks cutover")
            result.add(("research_profile", profile_resource_ref(str(research_id), stable, str(profile_ref)),
                        _ALL_SCOPES))
            if len(result) > _MAX_RESOURCES:
                raise AuthorizationUnavailable("Research candidate universe exceeds budget")
    if len(result) > _MAX_RESOURCES:
        raise AuthorizationUnavailable("Research candidate universe exceeds budget")
    return sorted(result)


def _verify_legacy_principals(owner: object, authorized: object, identities: dict[str, str]) -> None:
    if not identities.get(str(owner or "")):
        raise AuthorizationUnavailable("unmapped Research owner blocks cutover")
    try:
        members = json.loads(str(authorized or "[]"))
    except (TypeError, ValueError) as exc:
        raise AuthorizationUnavailable("invalid legacy Research grant list") from exc
    if not isinstance(members, list) or any(not isinstance(item, str) or not identities.get(item) for item in members):
        raise AuthorizationUnavailable("unmapped explicit Research grant blocks cutover")


def _active_human_subjects(adapter) -> dict[str, str]:
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


def verify_live_profile_policy_parity(*, database: str | Path, source_sha256: str,
                                      identity_by_principal: dict[str, str],
                                      evaluator: KeycloakResearchPolicyEvaluator) -> dict[str, int]:
    """Compare every old Profile member to live Keycloak, including denials.

    This is one necessary migration check, not a cutover receipt: Research
    reads, links, hierarchy, visitors and transfer paths require independent
    evidence. The caller must quiesce membership changes while using the
    result; a source hash alone cannot lock concurrent Keycloak policy edits.
    """
    if legacy_authorization_snapshot_sha256(database) != source_sha256:
        raise AuthorizationUnavailable("legacy Research authorization snapshot changed")
    identities = list(identity_by_principal.values())
    if (any(not isinstance(item, str) or not item.strip() for item in identities)
            or len(set(identities)) != len(identities)):
        raise AuthorizationUnavailable("reviewed Research identities are missing or ambiguous")
    # Validates owner/explicit/member mappings as well; no unknown legacy
    # principal may silently disappear when a Profile is migrated.
    universe = research_candidate_universe(database, identity_by_principal=identity_by_principal)
    candidates = [(kind, ref, ("read", "use", "write")) for kind, ref, _scopes in universe
                  if kind == "research_profile"]
    memberships: dict[tuple[str, str], set[str]] = {}
    uri = Path(database).expanduser().resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("BEGIN")
        for research, principal, profile, role, status in db.execute(
                "SELECT research_id, principal_ref, profile_ref, role, status "
                "FROM research_catalog_memberships ORDER BY research_id, principal_ref, profile_ref"):
            if role not in {"owner", "editor", "contributor", "viewer"} or status not in {"active", "invited", "revoked"}:
                raise AuthorizationUnavailable("legacy Research Profile membership is invalid")
            identity = identity_by_principal.get(str(principal))
            if not identity:
                raise AuthorizationUnavailable("unmapped Research Profile principal blocks verification")
            ref = profile_resource_ref(str(research), identity, str(profile))
            if (ref, identity) in memberships:
                raise AuthorizationUnavailable("duplicate legacy Research Profile membership")
            scopes: set[str] = set()
            if status == "active":
                scopes.update({"read", "use"})
                if role in {"owner", "editor", "contributor"}:
                    scopes.add("write")
            memberships[(ref, identity)] = scopes
    subjects = _active_human_subjects(evaluator.adapter)
    if not subjects:
        raise AuthorizationUnavailable("Keycloak has no active Research audit identities")
    checked = 0
    for identity in sorted(subjects):
        expected = {(kind, ref, scope): scope in memberships.get((ref, identity), set())
                    for kind, ref, scopes in candidates for scope in scopes}
        actual = evaluator.evaluate(identity, candidates=candidates)
        compare_research_decisions(expected, actual)
        checked += len(actual)
    if legacy_authorization_snapshot_sha256(database) != source_sha256:
        raise AuthorizationUnavailable("legacy Research authorization changed during verification")
    if _active_human_subjects(evaluator.adapter) != subjects:
        raise AuthorizationUnavailable("Keycloak user directory changed during verification")
    return {"principals": len(subjects), "profiles": len(candidates), "decisions": checked}


def verify_live_research_policy_parity(*, database: str | Path, source_sha256: str,
                                       identity_by_principal: dict[str, str],
                                       expected_by_identity: dict[str, dict[tuple[str, str, str], bool]],
                                       evaluator: KeycloakResearchPolicyEvaluator) -> dict[str, int]:
    """Compare complete source decisions to current Keycloak for active users.

    Expected decisions must come from a protected, reviewed legacy snapshot.
    No receipt flag or count can replace live Keycloak evaluation. Unknown
    identities, missing resources, partial results and source drift all fail.
    This verifies policy parity only, not browser, link or 7997 behavior.
    """
    if legacy_authorization_snapshot_sha256(database) != source_sha256:
        raise AuthorizationUnavailable("legacy Research authorization snapshot changed")
    candidates = research_candidate_universe(database, identity_by_principal=identity_by_principal)
    subjects = _active_human_subjects(evaluator.adapter)
    for identity, subject in subjects.items():
        user = evaluator.adapter.user_by_identity_id(identity)
        attrs = user.get("attributes") if isinstance(user, dict) else None
        if (not isinstance(attrs, dict) or attrs.get("tr_identity_id") != [identity]
                or user.get("enabled") is not True or user.get("id") != subject):
            raise AuthorizationUnavailable("Keycloak Research identity is invalid or ambiguous")
    if not subjects or set(expected_by_identity) != set(subjects):
        raise AuthorizationUnavailable("Research authorization principal coverage differs")
    required = {(kind, ref, scope) for kind, ref, scopes in candidates for scope in scopes}
    checked = 0
    for identity in sorted(subjects):
        expected = expected_by_identity[identity]
        if set(expected) != required:
            raise AuthorizationUnavailable("Research authorization candidate coverage differs")
        actual = evaluator.evaluate(identity, candidates=candidates)
        compare_research_decisions(expected, actual)
        checked += len(actual)
    if legacy_authorization_snapshot_sha256(database) != source_sha256:
        raise AuthorizationUnavailable("legacy Research authorization changed during verification")
    if _active_human_subjects(evaluator.adapter) != subjects:
        raise AuthorizationUnavailable("Keycloak user directory changed during verification")
    return {"principals": len(subjects), "resources": len(candidates), "decisions": checked}
