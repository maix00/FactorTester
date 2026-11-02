#!/usr/bin/env python3
"""Review and bind existing Job owners to a Manager's Keycloak identities.

The inventory and plan contain sensitive object identities: keep them in
owner-only files.  This tool never modifies JobSpec, deletes Jobs or guesses
an owner.  Each Manager must use its own issuer and Keycloak subjects.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import urllib.request
from uuid import UUID


MAX_JOBS = 100_000
BATCH_ROWS = 128
IDENTITY_COLUMNS = frozenset(("owner_issuer", "owner_subject"))
BACKUP_MAX_BYTES = 8 * 1024 ** 3
BACKUP_RESERVE_BYTES = 2 * 1024 ** 3
MAX_FOREIGN_KEY_VIOLATIONS = 100_000


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _hash_record(row, columns):
    """Hash typed non-identity columns without exporting their contents."""
    digest = hashlib.sha256()
    for name in columns:
        value = row[name]
        if value is None:
            kind, data = b"n", b""
        elif isinstance(value, bytes):
            kind, data = b"b", value
        elif isinstance(value, int):
            kind, data = b"i", str(value).encode()
        elif isinstance(value, float):
            kind, data = b"f", value.hex().encode()
        else:
            kind, data = b"s", str(value).encode("utf-8")
        for part in (name.encode(), kind, data):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def inventory(db):
    """Read an ordered, bounded snapshot within the caller's transaction."""
    columns = [row[1] for row in db.execute("PRAGMA table_info(research_jobs)")]
    if not {"job_id", "owner", "owner_issuer", "owner_subject", "job_spec_json"}.issubset(columns):
        raise ValueError("Job table is missing required identity columns")
    frozen_columns = [column for column in columns if column not in IDENTITY_COLUMNS]
    db.row_factory = sqlite3.Row
    cursor = db.execute("SELECT * FROM research_jobs ORDER BY job_id")
    jobs = []
    while True:
        rows = cursor.fetchmany(BATCH_ROWS)
        if not rows:
            break
        if len(jobs) + len(rows) > MAX_JOBS:
            raise ValueError("Job inventory exceeds its configured budget")
        for row in rows:
            jobs.append({
                "job_id": str(row["job_id"]), "owner": str(row["owner"] or ""),
                "issuer": str(row["owner_issuer"] or ""),
                "subject": str(row["owner_subject"] or ""),
                "other_columns_sha256": _hash_record(row, frozen_columns),
            })
    return {"version": 1, "jobs": jobs, "columns": columns}


def read_inventory(path):
    uri = Path(path).expanduser().resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("BEGIN")
        result = inventory(db)
        result["source_db"] = _database_identity(db)
        return result


def _database_identity(db):
    """Bind the plan to this database file, not merely equal-looking rows."""
    file_path = next((row[2] for row in db.execute("PRAGMA database_list")
                      if row[1] == "main"), "")
    if not file_path:
        raise ValueError("migration requires a persistent SQLite database")
    real_path = os.path.realpath(file_path)
    stat = os.stat(real_path)
    return _digest([real_path, stat.st_dev, stat.st_ino])


def _job_snapshot(snapshot):
    return {key: value for key, value in snapshot.items() if key != "source_db"}


def checked_issuer(adapter, issuer):
    """Require Admin API realm discovery to match the Manager's OIDC issuer."""
    issuer = str(issuer).rstrip("/")
    if not issuer or issuer.rpartition("/realms/")[2] != adapter.realm:
        raise ValueError("issuer and Keycloak realm do not match")
    url = f"{adapter.base_url}/realms/{adapter.realm}/.well-known/openid-configuration"
    with urllib.request.urlopen(url, timeout=5) as response:
        discovery = json.load(response)
    if str(discovery.get("issuer") or "").rstrip("/") != issuer:
        raise ValueError("Keycloak discovery issuer does not match Manager")
    return issuer


def _verified_identity(account, adapter):
    name = str(account.get("username") or "")
    identity = str(account.get("tr_identity_id") or "")
    if not name or name != name.strip() or not identity:
        raise ValueError("reviewed identity is incomplete")
    try:
        if str(UUID(identity)) != identity.lower():
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise ValueError("reviewed stable identity is invalid") from None
    user = adapter.user_by_identity_id(identity)
    attributes = (user or {}).get("attributes") or {}
    if (not isinstance(user, dict) or user.get("enabled") is not True
            or not str(user.get("id") or "")
            or attributes.get("tr_identity_id") != [identity]
            or attributes.get("legacy_username") != [name]):
        raise ValueError("Keycloak identity missing, disabled or inconsistent")
    return {"owner": name, "identity": identity, "subject": str(user["id"])}


def plan(snapshot, accounts, adapter, issuer, *, verify_discovery=True):
    """Build an explicit mapping; unknown or ambiguous owners block all writes."""
    if verify_discovery:
        issuer = checked_issuer(adapter, issuer)
    if snapshot.get("version") != 1 or not isinstance(snapshot.get("jobs"), list):
        raise ValueError("invalid Job inventory")
    directory = {}
    names_folded, identities = set(), set()
    for account in accounts:
        name = str(account.get("username") or "")
        identity = str(account.get("tr_identity_id") or "")
        if not name or name in directory or name.casefold() in names_folded or not identity or identity in identities:
            raise ValueError("reviewed directory has duplicate or missing identities")
        directory[name] = account
        names_folded.add(name.casefold())
        identities.add(identity)
    owners = sorted({row["owner"] for row in snapshot["jobs"]})
    verified, conflicts = {}, []
    for owner in owners:
        if owner not in directory:
            conflicts.append({"owner": owner, "reason": "owner_not_in_reviewed_directory"})
            continue
        try:
            verified[owner] = _verified_identity(directory[owner], adapter)
        except (ValueError, LookupError):
            conflicts.append({"owner": owner, "reason": "keycloak_identity_unresolved"})
    subjects = [entry["subject"] for entry in verified.values()]
    if len(subjects) != len(set(subjects)):
        conflicts.append({"owner": "", "reason": "ambiguous_subject"})
    targets = []
    seen_jobs = set()
    for row in snapshot["jobs"]:
        job_id, owner = row["job_id"], row["owner"]
        if not job_id or job_id in seen_jobs:
            raise ValueError("duplicate or missing Job reference")
        seen_jobs.add(job_id)
        identity = verified.get(owner)
        if not identity:
            conflicts.append({"job_id": job_id, "owner": owner, "reason": "unresolved_owner"})
            continue
        before = (row["issuer"], row["subject"])
        after = (issuer, identity["subject"])
        if before != ("", "") and before != after:
            conflicts.append({"job_id": job_id, "owner": owner, "reason": "existing_binding_conflict"})
            continue
        targets.append({"job_id": job_id, "owner": owner,
                        "identity": identity["identity"], "subject": identity["subject"],
                        "before_issuer": before[0], "before_subject": before[1]})
    result = {"version": 1, "issuer": issuer, "snapshot": snapshot,
              "identities": list(verified.values()), "targets": targets,
              "conflicts": conflicts}
    result["sha256"] = _digest(result)
    return result


def summary(reviewed):
    conflicts = reviewed["conflicts"]
    return {"status": "blocked" if conflicts else "planned",
            "jobs": len(reviewed["snapshot"]["jobs"]),
            "owners": len({row["owner"] for row in reviewed["snapshot"]["jobs"]}),
            "jobs_per_owner": sorted(Counter(row["owner"] for row in reviewed["snapshot"]["jobs"]).values(), reverse=True),
            "changes": sum(not row["before_issuer"] for row in reviewed["targets"]),
            "already_bound": sum(bool(row["before_issuer"]) for row in reviewed["targets"]),
            "conflicts": dict(sorted(Counter(row["reason"] for row in conflicts).items())),
            "sha256": reviewed["sha256"]}


def _validate_plan(reviewed):
    body = dict(reviewed)
    sha = body.pop("sha256", "")
    if not sha or _digest(body) != sha or reviewed.get("version") != 1:
        raise ValueError("migration plan checksum is invalid")
    if reviewed.get("conflicts") or len(reviewed["targets"]) != len(reviewed["snapshot"]["jobs"]):
        raise ValueError("migration plan has unresolved Jobs")


def revalidate_identities(reviewed, adapter, issuer, *, verify_discovery=True):
    if verify_discovery:
        issuer = checked_issuer(adapter, issuer)
    if issuer != reviewed["issuer"]:
        raise ValueError("Manager issuer changed after review")
    for identity in reviewed["identities"]:
        current = _verified_identity({"username": identity["owner"],
                                      "tr_identity_id": identity["identity"]}, adapter)
        if current != identity:
            raise ValueError("Keycloak subject changed after review")


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_json(path, value):
    fd = os.open(Path(path).expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(Path(path).expanduser().parent)


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _backup_capacity(path, total_bytes):
    """Bound backup growth and retain operational space throughout the copy."""
    if total_bytes > BACKUP_MAX_BYTES:
        raise ValueError("database backup exceeds its configured size budget")
    if shutil.disk_usage(path.parent).free < BACKUP_RESERVE_BYTES:
        raise ValueError("insufficient disk reserve for database backup")


def _integrity_check(db):
    rows = db.execute("PRAGMA integrity_check").fetchall()
    if len(rows) != 1 or rows[0][0] != "ok":
        raise ValueError("database integrity check failed")


def _foreign_key_summary(db):
    """Compare exact pre-existing violations without printing object identities."""
    cursor = db.execute("PRAGMA foreign_key_check")
    violations = []
    while True:
        rows = cursor.fetchmany(BATCH_ROWS)
        if not rows:
            break
        if len(violations) + len(rows) > MAX_FOREIGN_KEY_VIOLATIONS:
            raise ValueError("foreign-key inventory exceeds its configured budget")
        violations.extend(json.dumps(list(row), separators=(",", ":")) for row in rows)
    violations.sort()
    return {"count": len(violations), "sha256": _digest(violations)}


def make_backup(db, path, expected):
    """Make and integrity-check an exclusive consistent SQLite online backup."""
    path = Path(path).expanduser()
    page_size = int(db.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(db.execute("PRAGMA page_count").fetchone()[0])
    estimate = page_size * page_count
    _backup_capacity(path, estimate)
    if shutil.disk_usage(path.parent).free < estimate + BACKUP_RESERVE_BYTES:
        raise ValueError("insufficient disk capacity for database backup and reserve")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(path) as backup:
            def progress(_status, _remaining, total):
                _backup_capacity(path, int(total) * page_size)

            db.backup(backup, pages=256, sleep=0.01, progress=progress)
            _integrity_check(backup)
            if inventory(backup) != _job_snapshot(expected):
                raise ValueError("backup Job state differs from reviewed inventory")
            foreign_keys = _foreign_key_summary(backup)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
        return {"sha256": _file_sha256(path), "foreign_keys": foreign_keys}
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _apply_job_binding(db, issuer, target):
    result = db.execute(
        "UPDATE research_jobs SET owner_issuer=?, owner_subject=? "
        "WHERE job_id=? AND owner=? AND owner_issuer='' AND owner_subject=''",
        (issuer, target["subject"], target["job_id"], target["owner"]),
    )
    if result.rowcount != 1:
        raise ValueError("Job changed while applying identity binding")


def apply(db, reviewed, adapter, issuer, *, backup_path, receipt_path,
          expected_sha256, verify_discovery=True):
    _validate_plan(reviewed)
    if expected_sha256 != reviewed["sha256"]:
        raise ValueError("migration plan does not match the reviewed digest")
    if _database_identity(db) != reviewed["snapshot"].get("source_db"):
        raise ValueError("migration plan is for another database")
    revalidate_identities(reviewed, adapter, issuer, verify_discovery=verify_discovery)
    backup = make_backup(db, backup_path, reviewed["snapshot"])
    receipt = {"version": 1, "plan": reviewed, "backup": backup}
    _protected_json(receipt_path, receipt)
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='research_jobs' LIMIT 1").fetchone():
            raise ValueError("unexpected Job trigger requires separate review")
        if inventory(db) != _job_snapshot(reviewed["snapshot"]):
            raise ValueError("Job inventory changed after review or backup")
        if _foreign_key_summary(db) != backup["foreign_keys"]:
            raise ValueError("foreign-key inventory changed after backup")
        changed = 0
        for target in reviewed["targets"]:
            if target["before_issuer"]:
                continue
            _apply_job_binding(db, reviewed["issuer"], target)
            changed += 1
        actual = inventory(db)
        expected = json.loads(json.dumps(_job_snapshot(reviewed["snapshot"])))
        by_job = {target["job_id"]: target for target in reviewed["targets"]}
        for row in expected["jobs"]:
            target = by_job[row["job_id"]]
            row["issuer"], row["subject"] = reviewed["issuer"], target["subject"]
        if actual != expected:
            raise ValueError("Job identity or non-identity data failed verification")
        if _foreign_key_summary(db) != backup["foreign_keys"]:
            raise ValueError("foreign-key inventory changed during migration")
        _integrity_check(db)
        db.commit()
        return {"changed": changed, "jobs": len(actual["jobs"]),
                "before_sha256": _digest(_job_snapshot(reviewed["snapshot"])),
                "after_sha256": _digest(actual), "backup_sha256": backup["sha256"],
                "foreign_keys": backup["foreign_keys"], "integrity": "ok"}
    except BaseException:
        db.rollback()
        raise


def rollback(db, receipt):
    """Compare-and-swap only migration-written fields, preserving newer Jobs."""
    reviewed = receipt["plan"]
    _validate_plan(reviewed)
    if _database_identity(db) != reviewed["snapshot"].get("source_db"):
        raise ValueError("migration receipt is for another database")
    before = {row["job_id"]: row for row in reviewed["snapshot"]["jobs"]}
    db.execute("BEGIN IMMEDIATE")
    try:
        actual = {row["job_id"]: row for row in inventory(db)["jobs"]}
        for target in reviewed["targets"]:
            if target["before_issuer"]:
                continue
            original = before[target["job_id"]]
            current = actual.get(target["job_id"])
            if (not current or current["owner"] != target["owner"]
                    or current["other_columns_sha256"] != original["other_columns_sha256"]
                    or current["issuer"] != reviewed["issuer"]
                    or current["subject"] != target["subject"]):
                raise ValueError("Job changed after migration; rollback refused")
        changed = 0
        for target in reviewed["targets"]:
            if target["before_issuer"]:
                continue
            result = db.execute(
                "UPDATE research_jobs SET owner_issuer='', owner_subject='' "
                "WHERE job_id=? AND owner=? AND owner_issuer=? AND owner_subject=?",
                (target["job_id"], target["owner"], reviewed["issuer"], target["subject"]),
            )
            if result.rowcount != 1:
                raise ValueError("Job changed while rolling back identity binding")
            changed += 1
        db.commit()
        return {"changed": changed}
    except BaseException:
        db.rollback()
        raise


def _database(args):
    if args.settings:
        import settings
        return str(settings.CACHE_DB_PATH)
    return args.database


def _keycloak():
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    from server.identity.user_session import oidc_settings
    return manager_keycloak_admin_adapter(), oidc_settings()["issuer"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "apply", "rollback"):
        command = commands.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--database")
        source.add_argument("--settings", action="store_true")
        if name == "inventory":
            command.add_argument("--output", required=True, help="protected path, or - for a trusted pipe")
        elif name == "apply":
            command.add_argument("--plan", required=True)
            command.add_argument("--backup", required=True)
            command.add_argument("--receipt", required=True)
            command.add_argument("--expected-sha256", required=True)
        else:
            command.add_argument("--receipt", required=True)
    command = commands.add_parser("plan")
    command.add_argument("--inventory", required=True)
    command.add_argument("--reviewed-directory", required=True)
    command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        selected = read_inventory(_database(args))
        if args.output == "-":
            json.dump(selected, sys.stdout, ensure_ascii=False, sort_keys=True)
        else:
            _protected_json(args.output, selected)
            print(json.dumps({"jobs": len(selected["jobs"]), "sha256": _digest(selected)}))
    elif args.command == "plan":
        adapter, issuer = _keycloak()
        reviewed = plan(json.loads(Path(args.inventory).read_text()),
                        json.loads(Path(args.reviewed_directory).read_text())["accounts"],
                        adapter, issuer)
        _protected_json(args.output, reviewed)
        print(json.dumps(summary(reviewed), ensure_ascii=False, sort_keys=True))
        return 2 if reviewed["conflicts"] else 0
    else:
        uri = Path(_database(args)).expanduser().resolve().as_uri() + "?mode=rw"
        db = sqlite3.connect(uri, uri=True, timeout=30)
        try:
            if args.command == "apply":
                adapter, issuer = _keycloak()
                result = apply(db, json.loads(Path(args.plan).read_text()), adapter, issuer,
                               backup_path=args.backup, receipt_path=args.receipt,
                               expected_sha256=args.expected_sha256)
            else:
                result = rollback(db, json.loads(Path(args.receipt).read_text()))
            print(json.dumps(result, sort_keys=True))
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
