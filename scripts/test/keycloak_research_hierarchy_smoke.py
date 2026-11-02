"""Real Keycloak policy test for mutable parent relationships and old tokens.

Uses a disposable, bounded container; no existing realm or image is changed.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import sqlite3

from scripts.server.build_keycloak_policies import build
from scripts.test.keycloak_cross_realm_smoke import Sandbox
from scripts.test.keycloak_research_grant_smoke import run
from server.identity.keycloak_authorization import AuthorizationUnavailable, ensure_keycloak_resource
from server.identity.keycloak import KeycloakAdminAdapter
from server.identity.keycloak_hierarchy_admin import KeycloakHierarchyProvisioner
from server.identity.keycloak_research_cutover import KeycloakResearchPolicyEvaluator
from scripts.migrations.keycloak_research_stage import build_plan, stage_plan
from scripts.test.historical_research_catalog import HistoricalResearchCatalog


def check_hierarchy(*, sandbox, realm, client_id, client_uuid, client, sessions,
                    users, manager, settings, **_):
    profile = sandbox.api("GET", realm, "users/profile")
    for name in ("tr_organization_id", "tr_parent_identity_id"):
        profile["attributes"].append({"name": name, "multivalued": False,
            "permissions": {"view": ["admin"], "edit": ["admin"]}})
    sandbox.api("PUT", realm, "users/profile", profile)

    def update(name, *, parent="", organization="org-a", enabled=True):
        user = sandbox.api("GET", realm, "users/" + users[name]["id"])
        user["enabled"] = enabled
        user["attributes"]["tr_organization_id"] = [organization]
        user["attributes"]["tr_parent_identity_id"] = ["stable-" + parent] if parent else []
        sandbox.api("PUT", realm, "users/" + user["id"], user)

    for name in users:
        update(name)
    update("owner", parent="member")
    ref = "hierarchy-policy-research"
    resource_id = ensure_keycloak_resource(resource_type="research", resource_ref=ref,
                                          owner_subject=users["owner"]["id"])
    base = "clients/" + client_uuid + "/authz/resource-server"
    assert manager._reconcile_hierarchy_grant(resource_type="research", resource_ref=ref, enabled=True)
    assert not manager._reconcile_hierarchy_grant(resource_type="research", resource_ref=ref, enabled=True,
                                                 require_identical=True)

    samples = []
    def allowed(name, scope="read"):
        started = time.perf_counter()
        result = client.authorize(sessions[name][0], audience=client_id,
                                  resource_id=resource_id, scope=scope)
        samples.append(time.perf_counter() - started)
        return result

    if not allowed("member"):
        diagnostic = sandbox.api("POST", realm, base + "/policy/evaluate", {
            "userId": users["member"]["id"], "resources": [{"_id": resource_id, "scopes": [{"name": "read"}]}]})
        raise AssertionError("hierarchy policy denied initial ancestor: " + str(diagnostic.get("status")))
    assert not allowed("late")
    assert not allowed("member", "write") and not allowed("member", "manage")
    # Administrator changes the owner's parent. Reuse every original token.
    update("owner", parent="late")
    assert not allowed("member") and allowed("late")
    # Explicit collaboration is independent of the hierarchy grant.
    manager._reconcile_user_grant(resource_type="research", resource_ref=ref, source="explicit",
        identity_id="stable-member", subject=users["member"]["id"], scopes=["read"])
    assert allowed("member")
    manager._reconcile_user_grant(resource_type="research", resource_ref=ref, source="explicit",
        identity_id="stable-member", subject=users["member"]["id"], scopes=[])
    assert not allowed("member")
    update("late", parent="member", enabled=False)
    assert not allowed("member")
    update("late", organization="org-b")
    assert not allowed("late")
    update("late", parent="owner")
    assert not allowed("late")  # cycle must not grant a valid-looking prefix
    update("late")
    update("owner", parent="missing")
    assert not allowed("late")
    update("owner", parent="member")
    update("member", parent="late")
    assert allowed("member") and allowed("late")
    # Use the real migration entry, actual Realm Group membership and actual
    # Policy Evaluation. No substitute allow-set evaluator or identity list.
    update("owner", parent="member")
    update("member")
    class Admin(KeycloakAdminAdapter):
        def _token(self):
            return sandbox.admin
    adapter = Admin(sandbox.base, realm)
    paths = ["/traderesearch", "/traderesearch/organizations", "/traderesearch/organizations/org-a"]
    group_ids, _ = KeycloakHierarchyProvisioner(adapter).ensure_groups(paths)
    for user in users.values():
        adapter._put("users/" + user["id"] + "/groups/" + group_ids[paths[-1]], {})
    accounts = [{"username": name, "tr_identity_id": "stable-" + name,
                 "organization_id": "org-a", "parent_username": "member" if name == "owner" else ""}
                for name in users]
    evaluator = KeycloakResearchPolicyEvaluator(adapter=adapter, settings=settings,
        request=lambda _adapter, uuid, body: sandbox.api("POST", realm,
            "clients/" + uuid + "/authz/resource-server/policy/evaluate", body))
    with tempfile.TemporaryDirectory(prefix="tr-hierarchy-stage-") as temporary:
        database, backup = Path(temporary) / "research.sqlite", Path(temporary) / "backup.sqlite"
        legacy = HistoricalResearchCatalog(database)
        research = legacy.create_research(owner_ref="owner", title="Hierarchy migration", visibility="superiors")
        legacy.register_report(research["research_id"], actor="owner", report_id="hierarchy-stage-report",
                               profile_ref="self", visibility="superiors")
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as saved:
            source.backup(saved)
        plan = build_plan(database, accounts, issuer=settings.get("issuer") or "http://localhost:8080/realms/" + realm)
        assert plan["summary"]["ready_researches"] == 1
        journal = []
        kwargs = dict(database=database, backup=backup, reviewed_plan=plan, accounts=accounts,
                      adapter=adapter, grants=manager, evaluator=evaluator, record=journal.append, issuer=plan["issuer"])
        staged = stage_plan(**kwargs)
        assert staged["scope_decisions"] == 63 and staged["needs_repair_researches"] == 0
        assert stage_plan(**kwargs)["scope_decisions"] == 63
        update("owner", parent="late")
        try:
            stage_plan(**kwargs)
        except AuthorizationUnavailable as error:
            assert "hierarchy differs" in str(error)
        else:
            raise AssertionError("migration accepted an administrator change after review")
        print(json.dumps({"real_hierarchy_migration_scope_decisions": staged["scope_decisions"],
                          "idempotent_stage": True, "changed_hierarchy_blocks_stale_plan": True}, sort_keys=True))
    # Reset to avoid affecting the independent catalog-grant checks.
    for name in users:
        update(name)
    print(json.dumps({"live_keycloak_hierarchy": True, "same_token_reparent": True,
        "explicit_grant_independent": True, "cycle_missing_disabled_cross_org_denied": True,
        "http_decision_samples": len(samples), "http_decision_max_seconds": round(max(samples), 3)}, sort_keys=True))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="tr-keycloak-policy-") as temporary:
        jar = Path(temporary) / "tr-policies.jar"
        build(jar)
        with Sandbox(policy_jar=jar) as sandbox:
            print(json.dumps(run(sandbox, on_ready=check_hierarchy, renamed_logins=True), sort_keys=True))
