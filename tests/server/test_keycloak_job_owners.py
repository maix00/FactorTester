"""Focused contract for audited Job-to-Keycloak identity cutover."""
from __future__ import annotations

from collections import namedtuple
import json
import sqlite3

import pytest

from scripts.migrations import keycloak_job_owners as migration


ISSUER = "https://manager.invalid/identity/realms/traderesearch"
ALICE = "8f18bf8d-8702-48a3-a6e8-76a706952b9a"
BOB = "62e4cd35-8929-4e6a-9cc4-13365e741323"


class FakeKeycloak:
    realm = "traderesearch"
    base_url = "https://keycloak.invalid/identity"

    def __init__(self):
        self.users = {
            identity: {"id": subject, "enabled": True, "attributes": {
                "tr_identity_id": [identity], "legacy_username": [name],
            }} for name, identity, subject in (
                ("Alice", ALICE, "subject-a"), ("Bob", BOB, "subject-b"),
            )
        }

    def user_by_identity_id(self, identity):
        return self.users.get(identity)


@pytest.fixture
def case(tmp_path):
    path = tmp_path / "jobs.sqlite"
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE research_jobs (
        job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
        owner_issuer TEXT NOT NULL DEFAULT '', owner_subject TEXT NOT NULL DEFAULT '',
        job_spec_json TEXT NOT NULL, updated_at REAL NOT NULL, other BLOB
    )""")
    db.executemany("INSERT INTO research_jobs VALUES (?, ?, '', '', ?, ?, ?)", [
        ("job-1", "Alice", '{"factor": "v1"}', 1.0, b"a"),
        ("job-2", "Bob", '{"factor": "v2"}', 2.0, b"b"),
    ])
    db.commit()
    accounts = [{"username": "Alice", "tr_identity_id": ALICE},
                {"username": "Bob", "tr_identity_id": BOB}]
    adapter = FakeKeycloak()
    yield db, path, accounts, adapter, tmp_path
    db.close()


def reviewed(case):
    _, path, accounts, adapter, _ = case
    return migration.plan(migration.read_inventory(path), accounts, adapter, ISSUER,
                          verify_discovery=False)


def do_apply(case, plan):
    db, _, _, adapter, directory = case
    return migration.apply(db, plan, adapter, ISSUER,
                           backup_path=directory / "backup.sqlite",
                           receipt_path=directory / "receipt.json",
                           expected_sha256=plan["sha256"], verify_discovery=False)


def test_real_sqlite_backup_transaction_and_selective_rollback(case):
    db, _, _, _, directory = case
    plan = reviewed(case)
    assert migration.summary(plan)["changes"] == 2
    assert migration.summary(plan)["conflicts"] == {}
    result = do_apply(case, plan)
    assert result["changed"] == 2
    assert len(result["backup_sha256"]) == 64
    assert (directory / "backup.sqlite").stat().st_mode & 0o777 == 0o600
    assert (directory / "receipt.json").stat().st_mode & 0o777 == 0o600
    assert [tuple(row) for row in db.execute(
        "SELECT job_id, owner_issuer, owner_subject, job_spec_json FROM research_jobs ORDER BY job_id"
    )] == [("job-1", ISSUER, "subject-a", '{"factor": "v1"}'),
           ("job-2", ISSUER, "subject-b", '{"factor": "v2"}')]
    # A new Job after the cutover must survive a field-level rollback.
    db.execute("INSERT INTO research_jobs VALUES ('job-3','Alice',?,?,'{}',3.0,NULL)",
               (ISSUER, "subject-a"))
    db.commit()
    assert migration.rollback(db, json.loads((directory / "receipt.json").read_text())) == {"changed": 2}
    assert [tuple(row) for row in db.execute(
        "SELECT job_id, owner_issuer, owner_subject FROM research_jobs ORDER BY job_id"
    )] == [("job-1", "", ""), ("job-2", "", ""), ("job-3", ISSUER, "subject-a")]


def test_backup_preserves_original_identity_and_all_job_data(case):
    plan = reviewed(case)
    do_apply(case, plan)
    with sqlite3.connect(case[-1] / "backup.sqlite") as backup:
        assert migration.inventory(backup) == migration._job_snapshot(plan["snapshot"])


@pytest.mark.parametrize("mutation,reason", [
    ("UPDATE research_jobs SET owner='Carol' WHERE job_id='job-2'", "unresolved_owner"),
    ("UPDATE research_jobs SET owner_issuer='different' WHERE job_id='job-2'", "existing_binding_conflict"),
    ("UPDATE research_jobs SET owner_subject='subject-b' WHERE job_id='job-2'", "existing_binding_conflict"),
    ("UPDATE research_jobs SET owner_issuer='other', owner_subject='subject-b' WHERE job_id='job-2'", "existing_binding_conflict"),
])
def test_unknown_or_partially_bound_owner_blocks_entire_plan(case, mutation, reason):
    db = case[0]
    db.execute(mutation)
    db.commit()
    plan = reviewed(case)
    assert migration.summary(plan)["status"] == "blocked"
    assert any(conflict["reason"] == reason for conflict in plan["conflicts"])
    with pytest.raises(ValueError, match="unresolved"):
        do_apply(case, plan)
    assert not (case[-1] / "backup.sqlite").exists()


@pytest.mark.parametrize("field", ["subject", "legacy", "identity", "disabled", "absent"])
def test_changed_or_unverified_keycloak_identity_blocks_write(case, field):
    plan = reviewed(case)
    db, _, _, adapter, directory = case
    user = adapter.users[ALICE]
    if field == "subject":
        user["id"] = "other-subject"
    elif field == "legacy":
        user["attributes"]["legacy_username"] = ["Different"]
    elif field == "identity":
        user["attributes"]["tr_identity_id"] = [BOB]
    elif field == "disabled":
        user["enabled"] = False
    else:
        del adapter.users[ALICE]
    with pytest.raises(ValueError):
        do_apply(case, plan)
    assert not (directory / "backup.sqlite").exists()
    assert db.execute("SELECT COUNT(*) FROM research_jobs WHERE owner_subject<>''").fetchone()[0] == 0


def test_changed_job_after_review_aborts_before_backup(case):
    plan = reviewed(case)
    db = case[0]
    db.execute("UPDATE research_jobs SET job_spec_json=? WHERE job_id='job-1'", ('{"different":1}',))
    db.commit()
    with pytest.raises(ValueError, match="backup Job state differs"):
        do_apply(case, plan)
    assert not (case[-1] / "backup.sqlite").exists()
    assert db.execute("SELECT COUNT(*) FROM research_jobs WHERE owner_subject<>''").fetchone()[0] == 0


def test_changed_job_after_backup_aborts_before_writing(case, monkeypatch):
    plan = reviewed(case)
    make_backup = migration.make_backup

    def backup_then_change(db, path, expected):
        digest = make_backup(db, path, expected)
        with sqlite3.connect(case[1]) as concurrent:
            concurrent.execute("UPDATE research_jobs SET job_spec_json='changed' WHERE job_id='job-1'")
        return digest

    monkeypatch.setattr(migration, "make_backup", backup_then_change)
    with pytest.raises(ValueError, match="inventory changed"):
        do_apply(case, plan)
    assert case[0].execute("SELECT COUNT(*) FROM research_jobs WHERE owner_subject<>''").fetchone()[0] == 0
    assert (case[-1] / "backup.sqlite").exists()


def test_backup_size_and_disk_reserve_limits_block_before_writes(case, monkeypatch):
    plan = reviewed(case)
    monkeypatch.setattr(migration, "BACKUP_MAX_BYTES", 1)
    with pytest.raises(ValueError, match="size budget"):
        do_apply(case, plan)
    assert not (case[-1] / "backup.sqlite").exists()
    monkeypatch.setattr(migration, "BACKUP_MAX_BYTES", 8 * 1024 ** 3)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(migration.shutil, "disk_usage", lambda _: usage(10, 9, 1))
    with pytest.raises(ValueError, match="disk reserve"):
        do_apply(case, plan)
    assert not (case[-1] / "backup.sqlite").exists()


def test_existing_backup_is_never_overwritten(case):
    plan = reviewed(case)
    (case[-1] / "backup.sqlite").write_text("keep")
    with pytest.raises(FileExistsError):
        do_apply(case, plan)
    assert (case[-1] / "backup.sqlite").read_text() == "keep"


def test_sql_error_rolls_back_every_job(case):
    db = case[0]
    db.execute("""CREATE TRIGGER deny_second BEFORE UPDATE ON research_jobs
                  WHEN OLD.job_id='job-2' BEGIN SELECT RAISE(ABORT, 'blocked'); END""")
    db.commit()
    plan = reviewed(case)
    with pytest.raises(sqlite3.IntegrityError):
        do_apply(case, plan)
    assert db.execute("SELECT COUNT(*) FROM research_jobs WHERE owner_subject<>''").fetchone()[0] == 0
    assert (case[-1] / "backup.sqlite").exists()
    assert (case[-1] / "receipt.json").exists()


def test_rollback_refuses_all_if_any_job_changed(case):
    db, _, _, _, directory = case
    plan = reviewed(case)
    do_apply(case, plan)
    db.execute("UPDATE research_jobs SET job_spec_json='new' WHERE job_id='job-2'")
    db.commit()
    with pytest.raises(ValueError, match="rollback refused"):
        migration.rollback(db, json.loads((directory / "receipt.json").read_text()))
    assert db.execute("SELECT COUNT(*) FROM research_jobs WHERE owner_subject<>''").fetchone()[0] == 2


def test_plan_digest_and_source_file_are_enforced(case, tmp_path):
    db, _, _, adapter, directory = case
    plan = reviewed(case)
    with pytest.raises(ValueError, match="reviewed digest"):
        migration.apply(db, plan, adapter, ISSUER, backup_path=directory / "backup.sqlite",
                        receipt_path=directory / "receipt.json", expected_sha256="bad",
                        verify_discovery=False)
    other = sqlite3.connect(tmp_path / "different.sqlite")
    try:
        db.backup(other)
        with pytest.raises(ValueError, match="another database"):
            migration.apply(other, plan, adapter, ISSUER, backup_path=directory / "backup.sqlite",
                            receipt_path=directory / "receipt.json", expected_sha256=plan["sha256"],
                            verify_discovery=False)
    finally:
        other.close()


def test_identical_existing_bindings_are_retained(case):
    db = case[0]
    db.execute("UPDATE research_jobs SET owner_issuer=?, owner_subject='subject-a' WHERE job_id='job-1'", (ISSUER,))
    db.commit()
    plan = reviewed(case)
    assert migration.summary(plan)["already_bound"] == 1
    assert do_apply(case, plan)["changed"] == 1
    receipt = json.loads((case[-1] / "receipt.json").read_text())
    assert migration.rollback(db, receipt)["changed"] == 1
    assert tuple(db.execute("SELECT owner_issuer, owner_subject FROM research_jobs WHERE job_id='job-1'").fetchone()) == (ISSUER, "subject-a")


def test_duplicate_directory_and_changed_issuer_are_rejected(case):
    db, path, accounts, adapter, _ = case
    with pytest.raises(ValueError, match="duplicate"):
        migration.plan(migration.read_inventory(path), accounts + [accounts[0]], adapter, ISSUER,
                       verify_discovery=False)
    plan = reviewed(case)
    with pytest.raises(ValueError, match="issuer changed"):
        migration.revalidate_identities(plan, adapter, "https://other.invalid/realms/traderesearch",
                                        verify_discovery=False)


def test_discovery_must_identify_the_manager_issuer(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, *args):
            return json.dumps({"issuer": ISSUER}).encode()
    monkeypatch.setattr(migration.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    assert migration.checked_issuer(FakeKeycloak(), ISSUER) == ISSUER
    with pytest.raises(ValueError, match="does not match Manager"):
        migration.checked_issuer(FakeKeycloak(), "https://other.invalid/realms/traderesearch")
