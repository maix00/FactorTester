"""Read-only, bounded inventory of legacy Profile authorization projections.

Output contains only authorization metadata, never conversation text or
credentials. SQLite is read in one transaction; cache files have independent
snapshots and are explicitly not asserted to be atomic with it. Client files
and PostgreSQL are deliberately not claimed as inventoried by this tool.
This is an inventory, not authorization or an instruction to delete data.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

_MAX_ROWS = 100_000
_MAX_FILE = 4 * 1024 * 1024
_PAGE = 500
_MAX_PRINCIPALS = 64


def _text(value, *, optional=False):
    if value in (None, "") and optional:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError("Profile inventory identity is invalid")
    return value.strip()


def _users(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or len(value) > _MAX_ROWS:
        raise ValueError("Profile authorization list is invalid")
    return sorted({_text(item) for item in value})


def _principals(values):
    if not isinstance(values, (list, tuple, set)) or not values:
        raise ValueError("an explicit principal scope is required")
    result = sorted({_text(value) for value in values})
    if len(result) > _MAX_PRINCIPALS:
        raise ValueError("principal scope exceeds its budget")
    return result


def _observation(*, source, principal, profile_id, profile, deleted=False,
                 pending=False, origin_manager_id=""):
    if not isinstance(profile, dict):
        raise ValueError("Profile projection is invalid")
    binding = profile.get("session_binding")
    if binding is not None and not isinstance(binding, dict):
        raise ValueError("Profile session binding is invalid")
    binding = binding or {}
    principal, profile_id = _text(principal), _text(profile_id)
    bound_owner = _text(binding.get("principal_ref"), optional=True)
    bound_profile = _text(profile.get("profile_id"), optional=True)
    visibility = str(profile.get("visibility") or profile.get("profile_visibility") or "private").strip().lower()
    if visibility not in {"private", "authorized", "public"}:
        raise ValueError("Profile visibility is invalid")
    sharing = profile.get("conversation_sharing")
    # SQLite json_extract returns booleans as integer 0/1. Anything else is
    # ambiguous and must not be normalized into a grant.
    if sharing is not None and (not isinstance(sharing, (bool, int)) or sharing not in (0, 1)):
        raise ValueError("Profile conversation sharing value is invalid")
    return {"source": source, "principal": principal, "profile_id": profile_id,
            "binding_owner": bound_owner, "binding_profile_id": bound_profile,
            "owner_identity_id": _text(binding.get("principal_identity_id") or profile.get("owner_identity_id"), optional=True),
            "visibility": visibility, "authorized_users": _users(profile.get("authorized_users")),
            "conversation_sharing": None if sharing is None else bool(sharing),
            "deleted": bool(deleted), "pending": bool(pending),
            "origin_manager_id": _text(origin_manager_id, optional=True)}


def _read_file(path: Path) -> dict:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_FILE:
            raise ValueError("Profile projection file is not a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(_MAX_FILE + 1)
        after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError("Profile projection changed during inventory")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Profile projection document is invalid")
        return value
    finally:
        os.close(fd)


def read_cache(root: str | Path, *, principals) -> tuple[list[dict], set[tuple[str, str]]]:
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Profile cache is unavailable")
    result, pending_refs = [], set()
    for expected_principal in _principals(principals):
        item = path / (hashlib.sha256(expected_principal.encode("utf-8")).hexdigest() + ".json")
        if not os.path.lexists(item):
            continue
        value = _read_file(item)
        principal = _text(value.get("principal"))
        if principal != expected_principal:
            raise ValueError("Profile cache filename does not match its owner")
        profiles = value.get("profiles")
        pending = value.get("pending_profile_ids") or []
        if not isinstance(profiles, list) or not isinstance(pending, list):
            raise ValueError("Profile cache contents are invalid")
        pending_ids = {_text(value) for value in pending}
        pending_refs.update((principal, profile_id) for profile_id in pending_ids)
        if len(pending_refs) > _MAX_ROWS:
            raise ValueError("Profile cache pending count exceeds its budget")
        for profile in profiles:
            if not isinstance(profile, dict):
                raise ValueError("Profile cache row is invalid")
            profile_id = _text(profile.get("profile_id"))
            result.append(_observation(source="cache", principal=principal, profile_id=profile_id,
                                       profile=profile, pending=profile_id in pending_ids))
            if len(result) > _MAX_ROWS:
                raise ValueError("Profile cache row count exceeds its budget")
    return result, pending_refs


def read_sqlite(path: str | Path, *, principals) -> tuple[list[dict], set[tuple[str, str]], set[tuple[str, str]], dict[tuple[str, str], bool], set[tuple[str, str]]]:
    uri = Path(path).expanduser().resolve().as_uri() + "?mode=ro"
    selected = _principals(principals)
    placeholders = ",".join("?" for _ in selected)
    values, pending, conflicts, sharing, referenced = [], set(), set(), {}, set()
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        for table, output, where in (("account_domain_outbox", pending, ""),
                                     ("account_domain_conflicts", conflicts, " AND status='open'")):
            for row in db.execute(f"SELECT DISTINCT principal,entity_id FROM {table} "
                                  f"WHERE entity_type='profile' AND principal IN ({placeholders}){where} LIMIT ?",
                                  (*selected, _MAX_ROWS + 1)):
                output.add((_text(row["principal"]), _text(row["entity_id"])))
            if len(output) > _MAX_ROWS:
                raise ValueError("Profile pending/conflict count exceeds its budget")
        # The sharing toggle and runtime references live outside Profile
        # projections. Do not inspect conversation content or claim details.
        for row in db.execute("SELECT principal,profile_id,share_to_parent "
                              f"FROM manager_agent_profile_conversation_sharing WHERE principal IN ({placeholders}) LIMIT ?",
                              (*selected, _MAX_ROWS + 1)):
            key = (_text(row["principal"]), _text(row["profile_id"]))
            if row["share_to_parent"] not in (0, 1):
                raise ValueError("Profile parent-sharing flag is invalid")
            sharing[key] = bool(row["share_to_parent"])
        if len(sharing) > _MAX_ROWS:
            raise ValueError("Profile sharing count exceeds its budget")
        for table in ("manager_profile_runtime_bindings", "manager_profile_agent_claims"):
            for row in db.execute(f"SELECT DISTINCT principal,profile_id FROM {table} "
                                  f"WHERE principal IN ({placeholders}) LIMIT ?", (*selected, _MAX_ROWS + 1)):
                referenced.add((_text(row["principal"]), _text(row["profile_id"])))
                if len(referenced) > _MAX_ROWS:
                    raise ValueError("Profile runtime reference count exceeds its budget")
        for offset in range(0, _MAX_ROWS + 1, _PAGE):
            rows = db.execute(f"""SELECT principal,entity_id,deleted,origin_manager_id,
                json_extract(payload_json,'$.profile_id') AS profile_id,
                json_extract(payload_json,'$.session_binding.principal_ref') AS binding_owner,
                json_extract(payload_json,'$.session_binding.principal_identity_id') AS owner_identity_id,
                json_extract(payload_json,'$.visibility') AS visibility,
                json_extract(payload_json,'$.profile_visibility') AS profile_visibility,
                json_extract(payload_json,'$.authorized_users') AS authorized_users,
                json_extract(payload_json,'$.conversation_sharing') AS conversation_sharing
                FROM account_domain_entities WHERE entity_type='profile' AND principal IN ({placeholders})
                ORDER BY principal,entity_id LIMIT ? OFFSET ?""", (*selected, _PAGE, offset)).fetchall()
            for row in rows:
                principal, profile_id = _text(row["principal"]), _text(row["entity_id"])
                if row["deleted"] not in (0, 1):
                    raise ValueError("Profile tombstone flag is invalid")
                projected = {"profile_id": row["profile_id"], "visibility": row["visibility"],
                    "profile_visibility": row["profile_visibility"], "authorized_users": row["authorized_users"],
                    "conversation_sharing": row["conversation_sharing"], "session_binding": {
                        "principal_ref": row["binding_owner"], "principal_identity_id": row["owner_identity_id"]}}
                values.append(_observation(source="account_mirror", principal=principal, profile_id=profile_id,
                    profile=projected, deleted=row["deleted"], pending=(principal, profile_id) in pending,
                    origin_manager_id=row["origin_manager_id"]))
            if len(values) > _MAX_ROWS:
                raise ValueError("Profile mirror row count exceeds its budget")
            if len(rows) < _PAGE:
                break
    return values, pending, conflicts, sharing, referenced


def build_inventory(observations: list[dict], *, manager_id: str,
                    pending: set[tuple[str, str]], conflicts: set[tuple[str, str]],
                    sharing: dict[tuple[str, str], bool], referenced: set[tuple[str, str]],
                    principals) -> dict:
    manager = _text(manager_id)
    selected = _principals(principals)
    if len(observations) > _MAX_ROWS:
        raise ValueError("Profile observation count exceeds its budget")
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for value in observations:
        grouped[(_text(value.get("principal")), _text(value.get("profile_id")))].append(value)
    # A pending or conflicting record absent from every projection is retained
    # as an unresolved identity rather than interpreted as a deletion.
    for key in pending | conflicts | set(sharing) | referenced:
        grouped.setdefault(key, [])
    if any(owner not in selected for owner, _profile_id in grouped):
        raise ValueError("Profile observation is outside the requested principal scope")
    objects = []
    for (owner, profile_id), rows in sorted(grouped.items()):
        reasons = set()
        if not rows:
            reasons.add("missing_profile_projection")
        if (owner, profile_id) in pending or any(row["pending"] for row in rows):
            reasons.add("pending_synchronization")
        if (owner, profile_id) in conflicts:
            reasons.add("open_synchronization_conflict")
        if (owner, profile_id) in sharing:
            # Existing local and federated endpoints do not consistently
            # interpret this toggle; an explicit policy comparison is needed.
            reasons.add("conversation_sharing_policy_not_verified")
        for row in rows:
            if row["binding_owner"] and row["binding_owner"] != owner:
                reasons.add("owner_binding_conflict")
            if row["binding_profile_id"] and row["binding_profile_id"] != profile_id:
                reasons.add("profile_binding_conflict")
            if row["deleted"]:
                reasons.add("tombstone_requires_review")
            if not row["origin_manager_id"]:
                reasons.add("source_manager_unverified")
            if row["visibility"] in {"public", "authorized"}:
                reasons.add("local_remote_conversation_policy_differs")
        semantics = {(row["visibility"], tuple(row["authorized_users"]), row["owner_identity_id"])
                     for row in rows if not row["deleted"]}
        if len(semantics) > 1:
            reasons.add("projection_authorization_conflict")
        reasons.add("postgres_snapshot_not_verified")
        reasons.add("client_source_not_verified")
        # A reviewed account snapshot provides an inventory scope only; it is
        # not proof that current Keycloak subjects still have that identity.
        reasons.add("current_keycloak_identity_not_verified")
        # Parent/administrator grants are dynamic and must be reproduced with
        # live Keycloak policies before a cutover receipt can be issued.
        reasons.add("dynamic_hierarchy_policy_not_verified")
        objects.append({"principal": owner, "profile_id": profile_id, "state": "needs_repair" if reasons else "ready",
                        "reasons": sorted(reasons), "legacy_share_to_parent": sharing.get((owner, profile_id)),
                        "observations": sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))})
    canonical = {"schema": "tr-profile-authorization-inventory-v1", "manager_id": manager, "principal_scope": selected,
                 "objects": objects, "postgres_checked": False,
                 "client_checked": False, "cross_source_atomic": False}
    canonical["sha256"] = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    canonical["summary"] = {"principals": len(selected), "profiles": len(objects), "observations": len(observations),
        "by_source": dict(sorted(Counter(row["source"] for row in observations).items())),
        "needs_repair": sum(item["state"] == "needs_repair" for item in objects),
        "reasons": dict(sorted(Counter(reason for item in objects for reason in item["reasons"]).items())),
        "cutover_ready": False}
    return canonical


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--manager-id", required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--principal", action="append",
                       help="exact account owner to inventory; repeat for each approved principal")
    scope.add_argument("--reviewed-directory", help="protected reviewed account snapshot used only to select principals")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    selected = args.principal
    if args.reviewed_directory:
        document = _read_file(Path(args.reviewed_directory).expanduser())
        accounts = document.get("accounts")
        if not isinstance(accounts, list) or any(not isinstance(item, dict) for item in accounts):
            raise ValueError("reviewed account directory is invalid")
        selected = [account.get("username") for account in accounts]
    selected = _principals(selected)
    started_at = datetime.now(timezone.utc).isoformat()
    rows, pending, conflicts, sharing, referenced = read_sqlite(args.database, principals=selected)
    cached, cache_pending = read_cache(args.cache_root, principals=selected)
    rows.extend(cached)
    pending.update(cache_pending)
    value = build_inventory(rows, manager_id=args.manager_id, pending=pending, conflicts=conflicts,
                            sharing=sharing, referenced=referenced, principals=selected)
    value["observed_from_utc"] = started_at
    value["observed_until_utc"] = datetime.now(timezone.utc).isoformat()
    fd = os.open(Path(args.output).expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True)
        output.write("\n")
    print(json.dumps({**value["summary"], "sha256": value["sha256"],
                      "observed_from_utc": value["observed_from_utc"],
                      "observed_until_utc": value["observed_until_utc"]}, sort_keys=True))


if __name__ == "__main__":
    main()
