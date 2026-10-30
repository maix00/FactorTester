import sqlite3
import json

import pytest

from server.identity.keycloak import Identity
from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.keycloak_research import legacy_authorization_snapshot_sha256
from server.identity.keycloak_research_cutover import (
    KeycloakResearchPolicyEvaluator,
    compare_research_decisions,
    research_candidate_universe,
    verify_live_profile_policy_parity,
    verify_live_research_policy_parity,
)


class Directory:
    def _get(self, path):
        assert path.startswith("clients?")
        return [{"clientId": "tr-resources", "id": "client-uuid"}]

    def user_by_identity_id(self, identity):
        return {"id": "subject-" + identity, "enabled": True,
                "attributes": {"tr_identity_id": [identity]}}


def test_real_policy_evaluation_shape_is_batched_and_returns_explicit_denials():
    lookups, requests = [], []
    def lookup(_settings, _pat, kind, ref):
        lookups.append((kind, ref))
        return {"_id": kind + ":" + ref}
    def request(_adapter, client_uuid, payload):
        assert client_uuid == "client-uuid"
        requests.append(payload)
        return {"results": [{"resource": {"_id": item["_id"]}, "scopes": item["scopes"],
                             "status": "PERMIT" if item["scopes"][0]["name"] == "read" else "DENY",
                             "allowedScopes": [scope for scope in item["scopes"] if scope["name"] == "read"]}
                            for item in payload["resources"]]}
    evaluator = KeycloakResearchPolicyEvaluator(adapter=Directory(), settings={"authz_client_id": "tr-resources"},
        protection_token="pat", resource_lookup=lookup, request=request)
    candidates = [("research", str(i), ("read", "manage")) for i in range(33)]
    actual = evaluator.evaluate("identity-a", candidates=candidates)
    assert len(actual) == 66 and actual[("research", "0", "read")]
    assert not actual[("research", "0", "manage")]
    assert [len(item["resources"]) for item in requests] == [32, 1, 32, 1]
    assert {item["userId"] for item in requests} == {"subject-identity-a"}
    evaluator.evaluate("identity-b", candidates=candidates)
    assert len(lookups) == 33  # resolve once; decisions are still evaluated for each subject
    assert requests[-1]["userId"] == "subject-identity-b"


@pytest.mark.parametrize("response", [
    {"results": []},
    {"results": [{"resource": {"_id": "unexpected"}, "scopes": [{"name": "read"}], "allowedScopes": []}]},
    {"results": [{"resource": {"_id": "research:r"}, "scopes": [], "allowedScopes": []}]},
    {"results": [{"resource": {"_id": "research:r"}, "scopes": [{"name": "read"}], "allowedScopes": [{"name": "write"}]}]},
])
def test_incomplete_or_unexpected_policy_results_never_pass(response):
    evaluator = KeycloakResearchPolicyEvaluator(adapter=Directory(), settings={"authz_client_id": "tr-resources"},
        protection_token="pat", resource_lookup=lambda _s, _p, kind, ref: {"_id": kind + ":" + ref},
        request=lambda *_args: response)
    with pytest.raises(AuthorizationUnavailable):
        evaluator.evaluate("identity-a", candidates=[("research", "r", ("read",))])


def test_equal_counts_are_not_enough_for_authorization_parity():
    baseline = {("research", "r1", "read"): True, ("research", "r2", "read"): False}
    compare_research_decisions(baseline, dict(baseline))
    with pytest.raises(AuthorizationUnavailable, match="decisions differ"):
        compare_research_decisions(baseline, {("research", "r1", "read"): False,
                                              ("research", "r2", "read"): True})
    with pytest.raises(AuthorizationUnavailable, match="coverage differs"):
        compare_research_decisions(baseline, {("research", "r1", "read"): True})


@pytest.fixture
def legacy_catalog(tmp_path):
    path = tmp_path / "research.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE research_catalog_researches(research_id, owner_ref, status, visibility, authorized_users_json);
        CREATE TABLE research_catalog_reports(report_id, research_id, owner_ref, status, visibility, authorized_users_json);
        CREATE TABLE research_catalog_memberships(research_id, principal_ref, profile_ref, role, status);
        CREATE TABLE research_catalog_share_links(link_id, target_kind, research_id, report_id, owner_ref, token_hash, mode, expires_at, redeemed_by, redeemed_at, revoked_at);
        INSERT INTO research_catalog_researches VALUES ('r', 'alice', 'active', 'private', '["bob"]');
        INSERT INTO research_catalog_reports VALUES ('report', 'r', 'alice', 'active', 'private', '[]');
        INSERT INTO research_catalog_memberships VALUES ('r', 'bob', 'profile', 'editor', 'active');
        ''')
    return path


class LiveDirectory(Directory):
    def __init__(self):
        self.active = {"a", "b", "new-user"}
        self.org_members = None

    def _page(self, path, *, max_items):
        assert path == "users" and max_items == 20_000
        return [self.user_by_identity_id(identity) for identity in sorted(self.active)]

    def group_tree_members(self, path, *, max_groups, max_users):
        assert path == "/traderesearch/organizations"
        users = self.active if self.org_members is None else self.org_members
        return [Identity(username=name, subject="subject-" + name) for name in sorted(users)]


class AuditEvaluator:
    def __init__(self):
        self.adapter = LiveDirectory()
        self.after_evaluate = None

    def evaluate(self, identity, *, candidates):
        result = {(kind, ref, scope): identity == "a" and scope == "read"
                  for kind, ref, scopes in candidates for scope in scopes}
        if self.after_evaluate:
            self.after_evaluate()
        return result


def _audit_arguments(path):
    mapping = {"alice": "a", "bob": "b"}
    candidates = research_candidate_universe(path, identity_by_principal=mapping)
    evaluator = AuditEvaluator()
    expected = {identity: evaluator.evaluate(identity, candidates=candidates)
                for identity in evaluator.adapter.active}
    return {"database": path, "source_sha256": legacy_authorization_snapshot_sha256(path),
            "identity_by_principal": mapping, "expected_by_identity": expected,
            "evaluator": evaluator}


def test_real_catalog_scope_universe_requires_auditing_even_users_absent_from_old_acl(legacy_catalog):
    args = _audit_arguments(legacy_catalog)
    result = verify_live_research_policy_parity(**args)
    assert result == {"principals": 3, "resources": 3, "decisions": 63}
    # An enabled new user is not in the old ACL but still must be audited.
    del args["expected_by_identity"]["new-user"]
    with pytest.raises(AuthorizationUnavailable, match="principal coverage"):
        verify_live_research_policy_parity(**args)


def test_parity_rejects_equal_count_decision_changes_and_missing_candidate(legacy_catalog):
    args = _audit_arguments(legacy_catalog)
    expected = args["expected_by_identity"]["b"]
    key = next(iter(expected))
    expected[key] = not expected[key]
    with pytest.raises(AuthorizationUnavailable, match="decisions differ"):
        verify_live_research_policy_parity(**args)
    del expected[key]
    with pytest.raises(AuthorizationUnavailable, match="candidate coverage"):
        verify_live_research_policy_parity(**args)


def test_orphan_or_unmapped_explicit_grantee_blocks_instead_of_being_silently_dropped(legacy_catalog):
    with pytest.raises(AuthorizationUnavailable, match="unmapped"):
        research_candidate_universe(legacy_catalog, identity_by_principal={"alice": "a"})
    with sqlite3.connect(legacy_catalog) as db:
        db.execute("UPDATE research_catalog_researches SET owner_ref = 'removed-user'")
    with pytest.raises(AuthorizationUnavailable, match="owner"):
        research_candidate_universe(legacy_catalog, identity_by_principal={"alice": "a", "bob": "b"})


def test_catalog_or_user_directory_changes_abort_policy_comparison(legacy_catalog):
    args = _audit_arguments(legacy_catalog)
    def change_catalog():
        with sqlite3.connect(legacy_catalog) as db:
            db.execute("UPDATE research_catalog_memberships SET role = 'reader'")
    args["evaluator"].after_evaluate = change_catalog
    with pytest.raises(AuthorizationUnavailable, match="changed during"):
        verify_live_research_policy_parity(**args)
    args = _audit_arguments(legacy_catalog)
    args["evaluator"].after_evaluate = lambda: args["evaluator"].adapter.active.add("late-user")
    with pytest.raises(AuthorizationUnavailable, match="directory changed"):
        verify_live_research_policy_parity(**args)


def test_directory_missing_organization_or_ambiguous_identity_blocks_parity(legacy_catalog):
    args = _audit_arguments(legacy_catalog)
    args["evaluator"].adapter.org_members = {"a", "b"}
    with pytest.raises(AuthorizationUnavailable, match="organization coverage"):
        verify_live_research_policy_parity(**args)


def test_profile_parity_covers_every_user_and_rejects_an_extra_writer(legacy_catalog):
    evaluator = AuditEvaluator()
    extra = set()
    def evaluate(identity, *, candidates):
        return {(kind, ref, "write"): (json.loads(ref)[1] == identity or identity in extra)
                for kind, ref, _scopes in candidates}
    evaluator.evaluate = evaluate
    args = {"database": legacy_catalog, "source_sha256": legacy_authorization_snapshot_sha256(legacy_catalog),
            "identity_by_principal": {"alice": "a", "bob": "b"}, "evaluator": evaluator}
    assert verify_live_profile_policy_parity(**args) == {"principals": 3, "profiles": 1, "decisions": 3}
    extra.add("new-user")
    with pytest.raises(AuthorizationUnavailable, match="decisions differ"):
        verify_live_profile_policy_parity(**args)


def test_profile_parity_rejects_revoked_write_and_identity_collapse(legacy_catalog):
    evaluator = AuditEvaluator()
    evaluator.evaluate = lambda identity, *, candidates: {
        (kind, ref, "write"): json.loads(ref)[1] == identity for kind, ref, _scopes in candidates
    }
    with sqlite3.connect(legacy_catalog) as db:
        db.execute("UPDATE research_catalog_memberships SET status='revoked'")
    args = {"database": legacy_catalog, "source_sha256": legacy_authorization_snapshot_sha256(legacy_catalog),
            "identity_by_principal": {"alice": "a", "bob": "b"}, "evaluator": evaluator}
    with pytest.raises(AuthorizationUnavailable, match="decisions differ"):
        verify_live_profile_policy_parity(**args)
    args["identity_by_principal"] = {"alice": "a", "bob": "a"}
    with pytest.raises(AuthorizationUnavailable, match="ambiguous"):
        verify_live_profile_policy_parity(**args)
