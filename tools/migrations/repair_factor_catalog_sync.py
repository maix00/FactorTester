"""Prepare a scoped, frozen-identity-checked recovery of migration tombstones.

The control plan is applied by migrate_factor_control_domain, which allocates
fresh globally ordered revisions. This module never guesses missing source or
changes authored parameter inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from server.manager.services.account_domain_projection import _restore_legacy_factor_identity
from server.manager.storage.account_domain.payloads import public_payload
from tools.factors.formula_identity import require_frozen_factor
from tools.factors.factor_set_identity import require_frozen_factor_set


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def read_local(database: Path, principal: str):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        rows = [dict(row) for row in conn.execute(
            "SELECT principal, entity_type, entity_id, payload_json, deleted, remote_revision FROM account_domain_entities "
            "WHERE principal=? AND entity_type IN ('factor_param_config','factor_set')", (principal,),
        )]
        sets = [json.loads(row[0]) for row in conn.execute(
            "SELECT payload_json FROM account_factor_sets WHERE username=?", (principal,),
        )]
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    return rows, sets


def frozen_config(payload):
    values = payload.get("resolved_factors")
    if not isinstance(values, list) or not values:
        raise ValueError("no valid frozen factors")
    result = [{**item, **require_frozen_factor(_restore_legacy_factor_identity(item))} for item in values]
    cleaned = public_payload({**payload, "schema_version": 2, "resolved_factors": result})
    for item in cleaned["resolved_factors"]:
        require_frozen_factor(item)
    return cleaned


def build_plan(principal: str, local_rows: list, authority_rows: list, authored_sets: list, manager_id: str):
    local = {(row["entity_type"], row["entity_id"]): row for row in local_rows if row["principal"] == principal}
    remote = {(row["entity_type"], row["entity_id"]): row for row in authority_rows if row["principal"] == principal}
    rows, expectations, skipped = [], [], []
    refs = set()

    def append(key, target, deleted=False):
        previous = remote.get(key)
        rows.append({"principal": principal, "entity_type": key[0], "entity_id": key[1],
            "expected_revision": int((previous or {}).get("revision") or 0),
            "old_payload": previous["payload"] if previous else None,
            "old_deleted": bool(previous["deleted"]) if previous else True,
            "new_payload": target, "new_deleted": deleted, "origin_manager_id": manager_id})
        expectations.append({"entity_type": key[0], "entity_id": key[1], "snapshot": local.get(key)})

    for key, row in sorted(local.items()):
        if key[0] != "factor_param_config" or row["deleted"]:
            continue
        authority = remote.get(key)
        migration_deleted = authority and authority["deleted"] and authority["payload"].get("discarded_reason") == "incompatible formula identity"
        if authority and authority["deleted"] and not migration_deleted:
            skipped.append({"entity_id": key[1], "reason": "authority has an explicit deletion; preserved"})
            continue
        try:
            target = frozen_config(row["payload"])
            local_refs = {item["ref"] for item in target["resolved_factors"]}
            if authority and not authority["deleted"] and authority["payload"].get("resolved_factors"):
                authority_refs = {item["ref"] for item in frozen_config(authority["payload"])["resolved_factors"]}
                if not authority_refs <= local_refs:
                    raise ValueError("authority contains additional frozen identities; union needs authoring review")
            refs.update(local_refs)
            append(key, target)
        except (KeyError, TypeError, ValueError) as exc:
            skipped.append({"entity_id": key[1], "reason": str(exc)})
            if migration_deleted and not row["payload"].get("resolved_factors"):
                # Keep the unresolvable authoring inputs in their original table.
                # Accept the existing mirror state, without publishing a deletion.
                append(key, authority["payload"], True)

    set_expectations = []
    for value in authored_sets:
        frozen = require_frozen_factor_set(value)
        key = ("factor_set", frozen["ref"])
        if remote.get(key, {}).get("deleted"):
            skipped.append({"entity_id": key[1], "reason": "existing set deletion preserved"})
            continue
        target = public_payload({**value, **frozen, "owner_username": principal})
        require_frozen_factor_set(target)
        append(key, target)
        set_expectations.append({"ref": frozen["ref"], "digest": digest(value)})
    plan = {"schema_version": 1, "principal": principal, "rows": rows,
            "local_expectations": expectations, "authored_set_expectations": set_expectations,
            "skipped": skipped, "factor_count": len(refs), "factor_refs_sha256": digest(sorted(refs))}
    plan["plan_hash"] = digest(plan)
    return plan


def build_acceptance_plan(principal, local_rows, authority_rows, manager_id):
    """Accept a verified authority snapshot without dropping local frozen refs."""
    local = {(r["entity_type"], r["entity_id"]): r for r in local_rows if r["principal"] == principal}
    remote = {(r["entity_type"], r["entity_id"]): r for r in authority_rows if r["principal"] == principal}
    refs, rows, expectations = set(), [], []
    for key, current in local.items():
        if current["deleted"]:
            continue
        target = remote.get(key)
        if key[0] == "factor_param_config" and current["payload"].get("resolved_factors"):
            local_refs = {r["ref"] for r in frozen_config(current["payload"])["resolved_factors"]}
            remote_refs = {r["ref"] for r in frozen_config(target["payload"])["resolved_factors"]} if target and not target["deleted"] else set()
            if not local_refs <= remote_refs:
                raise ValueError("authority would discard local frozen identities")
        elif key[0] == "factor_set":
            # An explicit local set absent from authority requires reconciliation.
            try:
                frozen = require_frozen_factor_set(current["payload"])
            except (ValueError, KeyError, TypeError):
                continue
            if not target or target["deleted"] or require_frozen_factor_set(target["payload"])["ref"] != frozen["ref"]:
                raise ValueError("authority would discard a local frozen set")
    for key, target in sorted(remote.items()):
        rows.append({"principal": principal, "entity_type": key[0], "entity_id": key[1],
            "expected_revision": target["revision"], "old_payload": target["payload"],
            "old_deleted": bool(target["deleted"]), "new_payload": target["payload"],
            "new_deleted": bool(target["deleted"]), "origin_manager_id": manager_id})
        expectations.append({"entity_type": key[0], "entity_id": key[1], "snapshot": local.get(key)})
        if key[0] == "factor_param_config" and not target["deleted"]:
            refs.update(r["ref"] for r in frozen_config(target["payload"])["resolved_factors"])
    plan = {"schema_version": 1, "principal": principal, "rows": rows,
        "local_expectations": expectations, "authored_set_expectations": [], "skipped": [],
        "factor_count": len(refs), "factor_refs_sha256": digest(sorted(refs))}
    plan["plan_hash"] = digest(plan)
    verify_plan(plan)
    return plan


def verify_plan(plan):
    if plan.get("plan_hash") != digest({key: value for key, value in plan.items() if key != "plan_hash"}):
        raise ValueError("recovery plan hash mismatch")
    principal = plan["principal"]
    for row in plan["rows"]:
        if row["principal"] != principal:
            raise ValueError("cross-principal recovery plan")
        if not row["new_deleted"]:
            if row["entity_type"] == "factor_set": require_frozen_factor_set(row["new_payload"])
            elif row["entity_type"] == "factor_param_config": frozen_config(row["new_payload"])
            else: raise ValueError("unsupported recovery kind")


def apply_local(database: Path, plan: dict, receipt: dict):
    """Reconcile the original local mirror only after applying the checked control plan."""
    verify_plan(plan)
    from server.manager.storage.account_domain.local import LocalAccountDomainStore, _encode, _materialize_factor_entries
    LocalAccountDomainStore(database)  # Schema initialization precedes the bounded transaction.
    revisions = {(row["entity_type"], row["entity_id"]): row["revision"] for row in receipt["rows"]}
    targets = {(row["entity_type"], row["entity_id"]): row for row in plan["rows"]}
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        for expected in plan["local_expectations"]:
            key = (expected["entity_type"], expected["entity_id"])
            current = conn.execute("SELECT payload_json, deleted, remote_revision FROM account_domain_entities WHERE principal=? AND entity_type=? AND entity_id=?", (plan["principal"], *key)).fetchone()
            snapshot = expected["snapshot"]
            if snapshot is None:
                if current is not None: raise ValueError("local recovery target appeared after planning")
            elif current is None or json.loads(current["payload_json"]) != snapshot["payload"] or bool(current["deleted"]) != bool(snapshot["deleted"]) or current["remote_revision"] != snapshot["remote_revision"]:
                raise ValueError("local recovery precondition changed")
        for expected in plan["authored_set_expectations"]:
            row = conn.execute("SELECT payload_json FROM account_factor_sets WHERE username=? AND target_ref=?", (plan["principal"], expected["ref"])).fetchone()
            if row is None or digest(json.loads(row[0])) != expected["digest"]:
                raise ValueError("authored factor set changed after planning")
        for key, target in targets.items():
            revision = int(revisions[key])
            args = (plan["principal"], *key)
            conn.execute("INSERT INTO account_domain_entities(principal, entity_type, entity_id, payload_json, deleted, remote_revision, base_revision, origin_manager_id, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(principal,entity_type,entity_id) DO UPDATE SET payload_json=excluded.payload_json, deleted=excluded.deleted, remote_revision=excluded.remote_revision, base_revision=excluded.base_revision, updated_at=excluded.updated_at",
                (*args, _encode(target["new_payload"]), int(target["new_deleted"]), revision, revision, target["origin_manager_id"], time.time()))
            conn.execute("DELETE FROM account_domain_outbox WHERE principal=? AND entity_type=? AND entity_id=?", args)
            conn.execute("UPDATE account_domain_conflicts SET status='resolved', resolved_at=? WHERE principal=? AND entity_type=? AND entity_id=? AND status='open'", (time.time(), *args))
            _materialize_factor_entries(conn, *args, target["new_payload"], target["new_deleted"], target["origin_manager_id"])
    return len(targets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--authority-snapshot", type=Path)
    parser.add_argument("--manager-id", default="local-feat-docker-staging")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--accept-authority", action="store_true")
    parser.add_argument("--apply-local", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--environment", type=Path, default=Path("/run/secrets/control-db.env"))
    args = parser.parse_args()
    if args.apply_local:
        plan = json.loads(args.plan.read_text())
        receipt = json.loads(args.receipt.read_text())
        if plan["principal"] != args.principal or receipt["plan_sha256"] != hashlib.sha256(args.plan.read_bytes()).hexdigest():
            raise ValueError("recovery receipt identity mismatch")
        import psycopg
        from tools.migrations.migrate_factor_control_domain import _database_url
        revisions = {(row["entity_type"], row["entity_id"]): row["revision"] for row in receipt["rows"]}
        with psycopg.connect(_database_url(args.environment)) as control:
            control.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("factortester:account-domain:revision",))
            for target in plan["rows"]:
                key = (target["entity_type"], target["entity_id"])
                current = control.execute("SELECT payload, deleted, revision FROM control_account_domain_entities WHERE principal=%s AND entity_type=%s AND entity_id=%s", (args.principal, *key)).fetchone()
                if current is None or current[0] != target["new_payload"] or bool(current[1]) != target["new_deleted"] or current[2] != revisions[key]:
                    raise ValueError("authority changed after control recovery; regenerate plan")
            count = apply_local(args.database, plan, receipt)
        print(json.dumps({"applied_local": count, "plan_hash": plan["plan_hash"]}))
    else:
        local, sets = read_local(args.database, args.principal)
        authority = json.loads(args.authority_snapshot.read_text())
        plan = (build_acceptance_plan(args.principal, local, authority, args.manager_id) if args.accept_authority
                else build_plan(args.principal, local, authority, sets, args.manager_id))
        fd = os.open(args.plan, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream: json.dump(plan, stream, ensure_ascii=False, sort_keys=True)
        print(json.dumps({key: plan[key] for key in ("principal", "plan_hash", "factor_count", "factor_refs_sha256", "skipped")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
