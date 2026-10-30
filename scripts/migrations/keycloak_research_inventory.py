"""Inventory legacy Research authorization before Keycloak cutover.

This module is intentionally read-only.  It describes ownership, explicit
grants, Profile-specific writers, inheritance and link state separately; it
does not infer deletion or transfer ownership when an identity is missing.
The resulting plan is sensitive metadata and must be stored owner-only.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any


_PAGE_SIZE = 500
_MAX_ROWS = 100_000
_TABLES = {
    "researches": ("research_catalog_researches", ("research_id", "owner_ref", "status", "visibility", "authorized_users_json"), "research_id"),
    "reports": ("research_catalog_reports", ("report_id", "research_id", "owner_ref", "status", "visibility", "authorized_users_json"), "report_id"),
    "memberships": ("research_catalog_memberships", ("research_id", "principal_ref", "profile_ref", "role", "status"), "research_id, principal_ref, profile_ref"),
    "links": ("research_catalog_share_links", ("link_id", "target_kind", "research_id", "report_id", "owner_ref", "token_hash", "mode", "expires_at", "redeemed_by", "redeemed_at", "revoked_at"), "link_id"),
}


def _rows(db: sqlite3.Connection, table: str, columns: tuple[str, ...], order: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in range(0, _MAX_ROWS, _PAGE_SIZE):
        batch = db.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order} LIMIT ? OFFSET ?",
            (_PAGE_SIZE, offset),
        ).fetchall()
        rows.extend(dict(row) for row in batch)
        if len(batch) < _PAGE_SIZE:
            return rows
    raise ValueError(f"{table} exceeds the inventory budget")


def read_snapshot(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    uri = Path(path).expanduser().resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        # A single read transaction avoids mixing two revisions while pages
        # are being read.  It never starts schema initialization or writes.
        db.execute("BEGIN")
        return {kind: _rows(db, *table) for kind, table in _TABLES.items()}


def _explicit(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list) or any(not isinstance(item, str) or not item.strip() for item in parsed):
        raise ValueError("invalid explicit Research authorization list")
    return sorted(set(item.strip() for item in parsed))


def plan(snapshot: dict[str, list[dict[str, Any]]], accounts: list[dict[str, Any]], *, now: float) -> dict[str, Any]:
    """Create a deterministic migration inventory using stable identities.

    Hierarchy and public rules remain symbolic: freezing the current ancestor
    list would make future Keycloak hierarchy changes grant stale access.
    Report inheritance also stays a reference so revocation is immediate.
    """
    identity_by_name: dict[str, str] = {}
    known_identities: set[str] = set()
    for account in accounts:
        name, identity = str(account.get("username") or "").strip(), str(account.get("tr_identity_id") or "").strip()
        if not name or not identity or name in identity_by_name or identity in known_identities:
            raise ValueError("reviewed directory has missing or duplicate stable identities")
        identity_by_name[name] = identity
        known_identities.add(identity)
    issues: list[dict[str, str]] = []

    def identity(name: str, kind: str, ref: str, purpose: str) -> str:
        found = identity_by_name.get(str(name or "").strip(), "")
        if not found:
            issues.append({"kind": kind, "ref": ref, "purpose": purpose, "principal": str(name or "")})
        return found

    research_refs = {str(row["research_id"]) for row in snapshot["researches"]}
    members: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot["memberships"]:
        if row["status"] != "active":
            continue
        ref = str(row["research_id"])
        principal = identity(row["principal_ref"], "research", ref, "active_membership")
        if ref not in research_refs:
            issues.append({"kind": "research", "ref": ref, "purpose": "missing_research", "principal": str(row["principal_ref"])})
        members.setdefault(ref, []).append({
            "identity": principal, "profile_ref": str(row["profile_ref"]),
            "role": str(row["role"]),
        })

    resources: list[dict[str, Any]] = []
    for kind, rows, key in (("research", snapshot["researches"], "research_id"), ("research_report", snapshot["reports"], "report_id")):
        for row in rows:
            ref = str(row[key])
            owner = identity(row["owner_ref"], kind, ref, "owner")
            visibility = str(row["visibility"])
            if visibility not in {"private", "public", "authorized", "superiors"}:
                raise ValueError("unrecognized Research visibility")
            explicit = [identity(name, kind, ref, "explicit_grant") for name in _explicit(row["authorized_users_json"])]
            research_ref = str(row.get("research_id") or ref)
            if research_ref not in research_refs:
                issues.append({"kind": kind, "ref": ref, "purpose": "missing_research", "principal": ""})
            resources.append({
                "kind": kind, "ref": ref, "owner_identity": owner,
                "status": str(row["status"]), "visibility": visibility,
                "explicit_identities": sorted(set(x for x in explicit if x)),
                "memberships": sorted(members.get(ref, []), key=lambda item: (item["identity"], item["profile_ref"])) if kind == "research" else [],
                "inherit_research": research_ref if kind == "research_report" else "",
                "public_policy_required": visibility == "public",
                "ancestor_policy_required": visibility == "superiors",
            })

    links: list[dict[str, Any]] = []
    for row in snapshot["links"]:
        state = ("revoked" if float(row["revoked_at"] or 0) > 0 else
                 "expired" if float(row["expires_at"] or 0) > 0 and float(row["expires_at"]) <= now else
                 "redeemed" if row["mode"] == "one_time" and row["redeemed_by"] else "active")
        links.append({**row, "state": state})
    resources.sort(key=lambda item: (item["kind"], item["ref"]))
    issues.sort(key=lambda item: (item["kind"], item["ref"], item["purpose"], item["principal"]))
    links.sort(key=lambda item: str(item["link_id"]))
    # The digest includes link hashes and all authorization inputs but is the
    # only part of that data printed on stdout.
    frozen = {"resources": resources, "unresolved": issues, "links": links}
    digest = hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**frozen, "summary": {
        "resources": len(resources), "kinds": dict(Counter(row["kind"] for row in resources)),
        "unresolved": len(issues), "link_states": dict(Counter(row["state"] for row in links)),
        "ancestor_policies": sum(row["ancestor_policy_required"] for row in resources),
        "public_policies": sum(row["public_policy_required"] for row in resources),
        "sha256": digest,
    }}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database")
    source.add_argument("--snapshot", help="protected, bounded read-only export from another Manager")
    parser.add_argument("--reviewed-directory", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    accounts = json.loads(Path(args.reviewed_directory).read_text())["accounts"]
    snapshot = read_snapshot(args.database) if args.database else json.loads(Path(args.snapshot).read_text())
    result = plan(snapshot, accounts, now=time.time())
    path = Path(args.output).expanduser()
    # Avoid exposing grants or token hashes via permissive defaults.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(result, output, ensure_ascii=False, sort_keys=True)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
