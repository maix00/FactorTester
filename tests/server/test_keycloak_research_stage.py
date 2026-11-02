from __future__ import annotations

import os
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.migrations.keycloak_research_stage import (
    _Journal, _read_private_json, _write_private_json, build_plan, stage_plan,
)
from server.manager.services.research_catalog import ResearchCatalog
from scripts.test.legacy_research_fixture import seed_share_link


ISSUER = "https://identity.invalid/realms/test"
ACCOUNTS = [{"username": "alice", "tr_identity_id": "id-a"},
            {"username": "bob", "tr_identity_id": "id-b"}]


def _backup(source, destination):
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "research.sqlite"
    catalog = ResearchCatalog(path)
    good = catalog.create_research(owner_ref="alice", title="ready")["research_id"]
    catalog.add_membership(good, actor="alice", principal_ref="bob", profile_ref="work", role="editor")
    catalog.register_report(good, actor="alice", report_id="report-good", profile_ref="self",
                            authorized_users=["bob"])
    unknown = catalog.create_research(owner_ref="alice", title="unknown")["research_id"]
    upper = catalog.create_research(owner_ref="alice", title="upper", visibility="superiors")["research_id"]
    archived = catalog.create_research(owner_ref="alice", title="archived")["research_id"]
    live_link = catalog.create_research(owner_ref="alice", title="link")["research_id"]
    catalog.update_research(archived, actor="alice", status="archived")
    seed_share_link(path, research_id=live_link, actor="alice")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_researches SET owner_ref='ghost' WHERE research_id=?", (unknown,))
        db.execute("UPDATE research_catalog_memberships SET principal_ref='ghost' WHERE research_id=?", (unknown,))
    backup = tmp_path / "backup.sqlite"
    _backup(path, backup)
    return path, backup, {"good": good, "unknown": unknown, "upper": upper,
                          "archived": archived, "live_link": live_link}


class Directory:
    def __init__(self):
        self.users = {
            "id-a": {"id": "subject-a", "username": "alice", "enabled": True,
                     "attributes": {"tr_identity_id": ["id-a"]}},
            "id-b": {"id": "subject-b", "username": "bob", "enabled": True,
                     "attributes": {"tr_identity_id": ["id-b"]}},
        }
    def _page(self, path, *, max_items):
        assert path == "users"
        return list(self.users.values())
    def group_tree_members(self, _path, **_kwargs):
        return [SimpleNamespace(subject=row["id"], enabled=True) for row in self.users.values()]
    def user_by_identity_id(self, stable):
        return self.users.get(stable)


class StagedKeycloak:
    def __init__(self, directory):
        self.directory = directory
        self.resources = {}
        self.grants = {}
        self.fail_once = False
    def ensure_resource(self, *, resource_type, resource_ref, owner_subject, owner_scopes, creation_intent):
        key = (resource_type, resource_ref)
        data = (owner_subject, tuple(owner_scopes), creation_intent)
        if key in self.resources and self.resources[key] != data:
            raise RuntimeError("resource conflict")
        self.resources[key] = data
    def _reconcile_user_grant(self, *, resource_type, resource_ref, source, identity_id, subject, scopes,
                              require_identical=False):
        assert self.directory.users[identity_id]["id"] == subject
        key = (resource_type, resource_ref, source, identity_id)
        if key in self.grants and self.grants[key] != tuple(scopes):
            raise RuntimeError("grant conflict")
        self.grants[key] = tuple(scopes)
        if self.fail_once:
            self.fail_once = False
            raise ConnectionError("response lost after policy write")
    def evaluate(self, identity_id, *, candidates):
        result = {}
        user = self.directory.users[identity_id]["id"]
        for kind, ref, scopes in candidates:
            owner, owner_scopes, _intent = self.resources[(kind, ref)]
            allowed = set(owner_scopes) if owner == user else set()
            for (grant_kind, grant_ref, _source, target), granted in self.grants.items():
                if (kind, ref, identity_id) == (grant_kind, grant_ref, target):
                    allowed.update(granted)
            result.update({(kind, ref, scope): scope in allowed for scope in scopes})
        return result
    def require_resource_share(self, **_kwargs):
        pass

    def require_link_issuer_share(self, *, identity_id, subject, research_id, resource_type, resource_ref):
        assert self.directory.users[identity_id]['id'] == subject
        decisions = self.evaluate(identity_id, candidates=[('research', research_id, ('read', 'manage')),
                                  (resource_type, resource_ref, ('share',))])
        if not all(decisions.values()):
            raise PermissionError('link issuer is not authorized')
    def identity_provider(self, username):
        for identity, user in self.directory.users.items():
            if user['username'] == username and user['enabled']:
                return SimpleNamespace(identity_id=identity, subject=user['id'], username=username)
        return None
    def user_by_identity(self, identity):
        return self.directory.users.get(identity)


def test_plan_preserves_unmapped_hierarchy_links_and_uses_transaction_snapshot(legacy):
    path, _backup_path, ids = legacy
    before = path.read_bytes()
    result = build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)
    groups = {item["research_id"]: item for item in result["groups"]}
    assert groups[ids["good"]]["state"] == "ready"
    assert "unmapped_owner" in groups[ids["unknown"]]["reasons"]
    assert "dynamic_hierarchy_not_verified" in groups[ids["upper"]]["reasons"]
    assert "non_active_object" in groups[ids["archived"]]["reasons"]
    assert groups[ids["live_link"]]["state"] == "ready"
    assert len(groups[ids["live_link"]]["links"]) == 1
    assert result["summary"]["ready_researches"] == 2
    assert result["summary"]["needs_repair_researches"] == 3
    assert result["summary"]["cutover_ready"] is False
    assert not any(item["resources"] or item["grants"] for item in groups.values()
                   if item["state"] == "needs_repair")
    assert path.read_bytes() == before
    assert result["plan_sha256"] == build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)["plan_sha256"]


def test_staging_retries_uncertain_remote_write_and_compares_all_scopes(legacy):
    path, backup, ids = legacy
    reviewed = build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)
    directory = Directory()
    keycloak = StagedKeycloak(directory)
    keycloak.fail_once = True
    journal = []
    kwargs = dict(database=path, backup=backup, reviewed_plan=reviewed, accounts=ACCOUNTS,
                  adapter=directory, grants=keycloak, evaluator=keycloak, record=journal.append,
                  issuer=ISSUER, now=1)
    with pytest.raises(ConnectionError, match="response lost"):
        stage_plan(**kwargs)
    resources, policies = len(keycloak.resources), len(keycloak.grants)
    result = stage_plan(**kwargs)
    ready = [group for group in reviewed["groups"] if group["state"] == "ready"]
    assert len(keycloak.resources) == sum(len(group["resources"]) for group in ready) >= resources
    assert len(keycloak.grants) == sum(len(group["grants"]) for group in ready) >= policies
    assert result["scope_decisions"] == sum(len(group["resources"]) for group in ready) * len(directory.users) * 7
    assert result["needs_repair_researches"] == 3 and result['links_bound'] == 1
    assert any(event["event"] == "scope_parity" for event in journal)


def test_redeemed_and_unused_links_keep_exact_keycloak_identities(tmp_path):
    path = tmp_path / 'research.sqlite'
    catalog = ResearchCatalog(path)
    research = catalog.create_research(owner_ref='alice', title='Links')['research_id']
    used = seed_share_link(path, research_id=research, actor='alice', redeemed_by='bob')
    unused = seed_share_link(path, research_id=research, actor='alice')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_researches SET authorized_users_json=? WHERE research_id=?",
                   ('["bob"]', research))
    backup = tmp_path / 'backup.sqlite'; _backup(path, backup)
    reviewed = build_plan(path, ACCOUNTS, issuer=ISSUER)
    directory = Directory(); keycloak = StagedKeycloak(directory); journal = []
    kwargs = dict(database=path, backup=backup, reviewed_plan=reviewed, accounts=ACCOUNTS,
                  adapter=directory, grants=keycloak, evaluator=keycloak, record=journal.append, issuer=ISSUER)
    assert stage_plan(**kwargs)['links_bound'] == 2
    assert stage_plan(**kwargs)['links_bound'] == 2
    with sqlite3.connect(path) as db:
        issuers = db.execute('SELECT link_id,identity_id,subject FROM research_share_link_issuers ORDER BY link_id').fetchall()
        claims = db.execute('SELECT link_id,identity_id,subject,status FROM research_share_link_claims').fetchall()
    assert issuers == sorted([(used['link_id'], 'id-a', 'subject-a'), (unused['link_id'], 'id-a', 'subject-a')])
    assert claims == [(used['link_id'], 'id-b', 'subject-b', 'applied')]
    assert all('token' not in event for event in journal)
    migrated = ResearchCatalog(path, research_authorizer=object(), profile_authorizer=object(), profile_grant_manager=keycloak)
    with pytest.raises(PermissionError, match='already been redeemed'):
        migrated.redeem_share_link(used['token'], actor='alice')
    assert migrated.redeem_share_link(used['token'], actor='bob')['research_id'] == research
    assert migrated.redeem_share_link(unused['token'], actor='bob')['research_id'] == research
    with pytest.raises(PermissionError, match='already been redeemed'):
        migrated.redeem_share_link(unused['token'], actor='alice')


def test_link_binding_conflict_rolls_back_all_new_bindings(legacy):
    path, backup, ids = legacy
    seed_share_link(path, research_id=ids['live_link'], actor='alice')
    _backup(path, backup)
    reviewed = build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)
    links = next(item for item in reviewed['groups'] if item['research_id'] == ids['live_link'])['links']
    assert len(links) == 2
    link_id = links[-1]['link_id']
    with sqlite3.connect(path) as db:
        from server.manager.services.research_share_links import ensure_link_journal
        ensure_link_journal(db)
        db.execute('INSERT INTO research_share_link_issuers VALUES (?,?,?)', (link_id, 'other', 'subject-other'))
    directory = Directory(); keycloak = StagedKeycloak(directory)
    with pytest.raises(ValueError, match='issuer binding conflicts'):
        stage_plan(database=path, backup=backup, reviewed_plan=reviewed, accounts=ACCOUNTS,
                   adapter=directory, grants=keycloak, evaluator=keycloak, record=lambda _x: None, issuer=ISSUER, now=1)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT link_id,identity_id,subject FROM research_share_link_issuers').fetchall() == [(link_id, 'other', 'subject-other')]


def test_link_with_missing_issuer_blocks_that_research(legacy):
    path, _backup_path, ids = legacy
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_share_links SET owner_ref='unknown' WHERE research_id=?", (ids['live_link'],))
    group = next(item for item in build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)['groups'] if item['research_id'] == ids['live_link'])
    assert group['state'] == 'needs_repair'
    assert 'share_link_identity_or_target_unresolved' in group['reasons']
    assert not group['links'] and not group['resources']


def test_link_issuer_must_still_have_live_keycloak_share(legacy):
    path, backup, ids = legacy
    reviewed = build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)
    class RevokedKeycloak(StagedKeycloak):
        def require_link_issuer_share(self, **_kwargs):
            raise PermissionError('link issuer is not authorized')
    directory = Directory(); keycloak = RevokedKeycloak(directory)
    with pytest.raises(PermissionError, match='link issuer is not authorized'):
        stage_plan(database=path, backup=backup, reviewed_plan=reviewed, accounts=ACCOUNTS,
                   adapter=directory, grants=keycloak, evaluator=keycloak, record=lambda _x: None, issuer=ISSUER, now=1)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='research_share_link_issuers'").fetchall()


def test_link_issuer_without_mapped_share_scope_requires_repair(legacy):
    path, _backup_path, ids = legacy
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_share_links SET owner_ref='bob' WHERE research_id=?", (ids['live_link'],))
    group = next(item for item in build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)['groups'] if item['research_id'] == ids['live_link'])
    assert group['state'] == 'needs_repair'
    assert 'share_link_issuer_scope_not_mapped' in group['reasons']


@pytest.mark.parametrize('claimant,expected', [
    ('unknown', 'share_link_identity_or_target_unresolved'),
    ('bob', 'share_link_claimant_access_not_mapped'),
])
def test_redeemed_link_without_verified_claimant_access_requires_repair(legacy, claimant, expected):
    path, _backup_path, ids = legacy
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_share_links SET redeemed_by=?,redeemed_at=1 WHERE research_id=?", (claimant, ids['live_link']))
    group = next(item for item in build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)['groups'] if item['research_id'] == ids['live_link'])
    assert group['state'] == 'needs_repair'
    assert expected in group['reasons']
    assert not group['links'] and not group['resources']


def test_staging_rejects_backup_source_or_plan_drift_before_keycloak_writes(legacy):
    path, backup, _ids = legacy
    reviewed = build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)
    directory = Directory()
    keycloak = StagedKeycloak(directory)
    kwargs = dict(database=path, backup=backup, reviewed_plan=reviewed, accounts=ACCOUNTS,
                  adapter=directory, grants=keycloak, evaluator=keycloak, record=lambda _x: None,
                  issuer=ISSUER, now=1)
    with sqlite3.connect(backup) as db:
        db.execute("UPDATE research_catalog_researches SET visibility='public' WHERE title='ready'")
    with pytest.raises(ValueError, match="backup"):
        stage_plan(**kwargs)
    assert not keycloak.resources
    _backup(path, backup)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE research_catalog_researches SET visibility='authorized' WHERE title='ready'")
    with pytest.raises(ValueError, match="plan or identity directory changed"):
        stage_plan(**kwargs)
    assert not keycloak.resources


def test_concurrent_staging_serializes_before_keycloak_calls(legacy):
    path, backup, _ids = legacy
    reviewed = build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)
    directory = Directory()
    entered, release = threading.Event(), threading.Event()
    class BlockingKeycloak(StagedKeycloak):
        running, max_running, blocked = 0, 0, False
        def ensure_resource(self, **kwargs):
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            try:
                if not self.blocked:
                    self.blocked = True
                    entered.set()
                    assert release.wait(timeout=5)
                return super().ensure_resource(**kwargs)
            finally:
                self.running -= 1
    keycloak = BlockingKeycloak(directory)
    kwargs = dict(database=path, backup=backup, reviewed_plan=reviewed, accounts=ACCOUNTS,
                  adapter=directory, grants=keycloak, evaluator=keycloak, record=lambda _x: None,
                  issuer=ISSUER, now=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(stage_plan, **kwargs)
        assert entered.wait(timeout=5)
        second = pool.submit(stage_plan, **kwargs)
        assert keycloak.max_running == 1
        release.set()
        assert first.result(timeout=5) == second.result(timeout=5)
    assert keycloak.max_running == 1


def test_source_change_during_staging_prevents_success_receipt(legacy):
    path, backup, _ids = legacy
    reviewed = build_plan(path, ACCOUNTS, issuer=ISSUER, now=1)
    directory = Directory()
    class ChangedSource(StagedKeycloak):
        changed = False
        def ensure_resource(self, **kwargs):
            super().ensure_resource(**kwargs)
            if not self.changed:
                self.changed = True
                with sqlite3.connect(path) as db:
                    db.execute("UPDATE research_catalog_researches SET visibility='authorized' WHERE title='ready'")
    keycloak = ChangedSource(directory)
    with pytest.raises(ValueError, match="changed during staging"):
        stage_plan(database=path, backup=backup, reviewed_plan=reviewed, accounts=ACCOUNTS,
                   adapter=directory, grants=keycloak, evaluator=keycloak, record=lambda _x: None,
                   issuer=ISSUER, now=1)


def test_protected_plan_and_resume_journal_reject_other_plan_and_symlinks(tmp_path):
    plan_path = tmp_path / "plan.json"
    _write_private_json(plan_path, {"x": 1})
    assert _read_private_json(plan_path) == {"x": 1}
    assert plan_path.stat().st_mode & 0o777 == 0o600
    journal_path = tmp_path / "journal.jsonl"
    journal = _Journal(journal_path, plan_sha256="a" * 64, issuer=ISSUER)
    journal({"event": "stage_started"})
    journal.close()
    with journal_path.open("ab") as stream:
        stream.write(b'{"event":"interrupted')
    resumed = _Journal(journal_path, plan_sha256="a" * 64, issuer=ISSUER)
    resumed.close()
    entries = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert [item["event"] for item in entries] == ["stage_started", "recovered_incomplete_tail"]
    with pytest.raises(ValueError, match="another plan"):
        _Journal(journal_path, plan_sha256="b" * 64, issuer=ISSUER)
    link = tmp_path / "link"
    link.symlink_to(plan_path)
    with pytest.raises(OSError):
        _read_private_json(link)
    os.chmod(plan_path, 0o644)
    with pytest.raises(PermissionError, match="owner-only"):
        _read_private_json(plan_path)
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_bytes(b'{"not-a-migration-record')
    invalid.chmod(0o600)
    with pytest.raises(ValueError, match="invalid record"):
        _Journal(invalid, plan_sha256="a" * 64, issuer=ISSUER)
    assert invalid.read_bytes() == b'{"not-a-migration-record'
