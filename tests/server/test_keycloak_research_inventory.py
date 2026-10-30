import json
import sqlite3

import pytest

from scripts.migrations.keycloak_research_inventory import plan, read_snapshot


def test_inventory_keeps_inheritance_profile_members_and_dynamic_visibility():
    snapshot = {
        "researches": [{"research_id": "r", "owner_ref": "alice", "status": "active",
                         "visibility": "superiors", "authorized_users_json": '["bob"]'}],
        "reports": [{"report_id": "p", "research_id": "r", "owner_ref": "alice",
                     "status": "active", "visibility": "public", "authorized_users_json": "[]"}],
        "memberships": [{"research_id": "r", "principal_ref": "bob", "profile_ref": "work",
                         "role": "editor", "status": "active"},
                        {"research_id": "r", "principal_ref": "alice", "profile_ref": "old",
                         "role": "viewer", "status": "revoked"}],
        "links": [{"link_id": "l", "target_kind": "research", "research_id": "r", "report_id": "",
                   "owner_ref": "alice", "token_hash": "opaque", "mode": "one_time", "expires_at": 0,
                   "redeemed_by": "", "redeemed_at": 0, "revoked_at": 3}],
    }
    accounts = [{"username": "alice", "tr_identity_id": "id-a"}, {"username": "bob", "tr_identity_id": "id-b"}]
    result = plan(snapshot, accounts, now=10)
    research, report = result["resources"]
    assert research["ancestor_policy_required"] and research["explicit_identities"] == ["id-b"]
    assert research["memberships"] == [{"identity": "id-b", "profile_ref": "work", "role": "editor"}]
    assert report["public_policy_required"] and report["inherit_research"] == "r"
    assert result["summary"]["link_states"] == {"revoked": 1}
    assert result["summary"]["unresolved"] == 0


def test_unknown_owner_and_grant_are_reported_without_reassignment():
    snapshot = {"researches": [{"research_id": "r", "owner_ref": "deleted", "status": "active",
                                "visibility": "authorized", "authorized_users_json": '["missing"]'}],
                "reports": [], "memberships": [], "links": []}
    result = plan(snapshot, [{"username": "alice", "tr_identity_id": "id-a"}], now=0)
    assert result["resources"][0]["owner_identity"] == ""
    assert {item["purpose"] for item in result["unresolved"]} == {"owner", "explicit_grant"}
    assert result["summary"]["unresolved"] == 2


def test_live_single_use_link_is_not_discarded():
    snapshot = {"researches": [], "reports": [], "memberships": [],
                "links": [{"link_id": "l", "mode": "one_time", "expires_at": 20,
                           "redeemed_by": "", "revoked_at": 0, "token_hash": "digest"}]}
    result = plan(snapshot, [], now=10)
    assert result["links"][0]["state"] == "active"
    assert result["links"][0]["token_hash"] == "digest"


def test_invalid_identity_mapping_and_grant_lists_fail_closed():
    empty = {"researches": [], "reports": [], "memberships": [], "links": []}
    with pytest.raises(ValueError, match="duplicate"):
        plan(empty, [{"username": "a", "tr_identity_id": "x"}, {"username": "b", "tr_identity_id": "x"}], now=0)
    empty["researches"] = [{"research_id": "r", "owner_ref": "a", "status": "active",
                            "visibility": "authorized", "authorized_users_json": json.dumps({"a": True})}]
    with pytest.raises(ValueError, match="authorization list"):
        plan(empty, [{"username": "a", "tr_identity_id": "x"}], now=0)


def test_snapshot_is_read_only_and_uses_a_consistent_projection(tmp_path):
    db = tmp_path / "metadata.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript('''
        CREATE TABLE research_catalog_researches(research_id, owner_ref, status, visibility, authorized_users_json);
        CREATE TABLE research_catalog_reports(report_id, research_id, owner_ref, status, visibility, authorized_users_json);
        CREATE TABLE research_catalog_memberships(research_id, principal_ref, profile_ref, role, status);
        CREATE TABLE research_catalog_share_links(link_id, target_kind, research_id, report_id, owner_ref, token_hash, mode, expires_at, redeemed_by, redeemed_at, revoked_at);
        INSERT INTO research_catalog_researches VALUES ('r', 'a', 'active', 'private', '[]');
        ''')
    before = db.read_bytes()
    snapshot = read_snapshot(db)
    assert snapshot["researches"][0]["research_id"] == "r"
    assert db.read_bytes() == before
