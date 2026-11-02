"""Stage legacy Research policies in Keycloak without switching authority.

The reviewed plan and journal are sensitive migration artifacts.  Incomplete
hierarchies, public links and unmapped identities are recorded as needs_repair;
they never cause a deletion or an ownership transfer.  Staging is not cutover.
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

from scripts.migrations.keycloak_research_inventory import _TABLES, _rows, plan as inventory_plan, reviewed_identity_map
from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.keycloak_research import (
    legacy_authorization_snapshot_digest, legacy_authorization_snapshot_sha256, profile_resource_ref,
)
from server.identity.keycloak_research_cutover import (
    KeycloakResearchPolicyEvaluator, _ALL_SCOPES, _active_human_subjects, compare_research_decisions,
)


def _hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _capture(database: str | Path) -> tuple[dict[str, list[dict[str, Any]]], str]:
    uri = Path(database).expanduser().resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        snapshot = {kind: _rows(db, *table) for kind, table in _TABLES.items()}
        digest = legacy_authorization_snapshot_digest(db)
    return snapshot, digest


def build_plan(database: str | Path, accounts: list[dict[str, Any]], *, issuer: str,
               now: float | None = None) -> dict[str, Any]:
    """Build one deterministic, consistent-snapshot plan; no network or writes."""
    issuer = str(issuer or "").strip().rstrip("/")
    if not issuer:
        raise ValueError("a specific Keycloak issuer is required")
    snapshot, source = _capture(database)
    inventory = inventory_plan(snapshot, accounts, now=time.time() if now is None else now)
    identities = reviewed_identity_map(accounts)
    research = {str(row["research_id"]): row for row in snapshot["researches"]}
    reports = {str(row["report_id"]): row for row in snapshot["reports"]}
    projected = {(row["kind"], row["ref"]): row for row in inventory["resources"]}
    reasons: dict[str, set[str]] = {ref: set() for ref in research}
    global_issues: set[str] = set()

    def mark(ref: str, reason: str) -> None:
        if ref not in reasons:
            global_issues.add("unscoped_" + reason)
        else:
            reasons[ref].add(reason)

    for issue in inventory["unresolved"]:
        ref = str(issue["ref"])
        parent = ref if issue["kind"] == "research" else str(reports.get(ref, {}).get("research_id") or "")
        mark(parent, "unmapped_" + str(issue["purpose"]))
    profile_associations: set[tuple[str, str, str]] = set()
    for row in snapshot["memberships"]:
        parent = str(row["research_id"])
        stable = identities.get(str(row["principal_ref"]))
        association = (parent, stable or str(row["principal_ref"]), str(row["profile_ref"]))
        if association in profile_associations:
            mark(parent, "duplicate_profile_alias_needs_review")
        profile_associations.add(association)
        if row["role"] not in {"owner", "editor", "contributor", "viewer"} or row["status"] not in {"active", "invited", "revoked"}:
            mark(parent, "invalid_membership")
        if not identities.get(str(row["principal_ref"])):
            mark(parent, "unmapped_profile_identity")
    for kind, rows, key in (("research", snapshot["researches"], "research_id"),
                            ("research_report", snapshot["reports"], "report_id")):
        for row in rows:
            ref = str(row[key])
            parent = ref if kind == "research" else str(row["research_id"])
            if row["status"] != "active":
                mark(parent, "non_active_object")
            if row["visibility"] == "superiors":
                mark(parent, "dynamic_hierarchy_not_verified")
            if row["visibility"] == "public":
                mark(parent, "public_policy_not_verified")
    links_by_research: dict[str, list[dict[str, str]]] = {}
    for link in inventory["links"]:
        if link["state"] not in {"active", "redeemed"}:
            continue
        parent = str(link.get("research_id") or "")
        kind, report_id = str(link.get("target_kind") or ""), str(link.get("report_id") or "")
        owner = identities.get(str(link.get("owner_ref") or ""), "")
        claimant_name = str(link.get("redeemed_by") or "")
        claimant = identities.get(claimant_name, "") if claimant_name else ""
        if (parent not in research or kind not in {"research", "report"}
                or (kind == "research" and report_id)
                or (kind == "report" and (report_id not in reports or str(reports[report_id]["research_id"]) != parent))
                or str(link.get("mode") or "") not in {"one_time", "permanent"}
                or not owner or (claimant_name and not claimant)
                or not str(link.get("link_id") or "")):
            mark(parent, "share_link_identity_or_target_unresolved")
            continue
        research_owner = identities.get(str(research[parent]["owner_ref"]), "")
        target_owner = (identities.get(str(reports[report_id]["owner_ref"]), "")
                        if kind == "report" else research_owner)
        if owner != research_owner or owner != target_owner:
            mark(parent, "share_link_issuer_scope_not_mapped")
            continue
        links_by_research.setdefault(parent, []).append({
            "link_id": str(link["link_id"]), "issuer_identity": owner,
            "claimant_identity": claimant, "target_kind": kind,
            "target_ref": parent if kind == "research" else report_id,
        })

    groups = []
    for research_id, row in sorted(research.items()):
        base = projected[("research", research_id)]
        child_reports = sorted((value for value in reports.values() if str(value["research_id"]) == research_id),
                               key=lambda item: str(item["report_id"]))
        group: dict[str, Any] = {
            "research_id": research_id, "state": "needs_repair" if reasons[research_id] else "ready",
            "reasons": sorted(reasons[research_id]), "resources": [], "grants": [], "links": [],
        }
        if group["state"] == "ready":
            group["resources"].append({"kind": "research", "ref": research_id,
                                       "owner_identity": base["owner_identity"], "owner_scopes": list(_ALL_SCOPES)})
            for identity in base["explicit_identities"]:
                group["grants"].append({"kind": "research", "ref": research_id, "identity": identity,
                                        "source": "explicit", "scopes": ["read", "use"]})
            for member in sorted((value for value in snapshot["memberships"]
                                  if str(value["research_id"]) == research_id),
                                 key=lambda item: (str(item["principal_ref"]), str(item["profile_ref"]))):
                identity = identities[str(member["principal_ref"])]
                ref = profile_resource_ref(research_id, identity, str(member["profile_ref"]))
                group["resources"].append({"kind": "research_profile", "ref": ref,
                                           "owner_identity": base["owner_identity"], "owner_scopes": ["share"]})
                scopes = []
                if member["status"] == "active":
                    scopes = ["read", "use"]
                    if member["role"] in {"owner", "editor", "contributor"}:
                        scopes.append("write")
                if scopes:
                    group["grants"].append({"kind": "research_profile", "ref": ref, "identity": identity,
                                            "source": "membership", "scopes": sorted(scopes)})
            for report in child_reports:
                ref = str(report["report_id"])
                item = projected[("research_report", ref)]
                group["resources"].append({"kind": "research_report", "ref": ref,
                                           "owner_identity": item["owner_identity"], "owner_scopes": list(_ALL_SCOPES)})
                for identity in item["explicit_identities"]:
                    group["grants"].append({"kind": "research_report", "ref": ref, "identity": identity,
                                            "source": "explicit", "scopes": ["read"]})
            group["resources"].sort(key=lambda item: (item["kind"], item["ref"]))
            group["grants"].sort(key=lambda item: (item["kind"], item["ref"], item["source"], item["identity"]))
            group["links"] = sorted(links_by_research.get(research_id, []), key=lambda item: item["link_id"])
            for link in group["links"]:
                kind = "research" if link["target_kind"] == "research" else "research_report"
                if link["claimant_identity"] and not _expected(group, link["claimant_identity"]).get((kind, link["target_ref"], "read"), False):
                    group.update(state="needs_repair", reasons=["share_link_claimant_access_not_mapped"],
                                 resources=[], grants=[], links=[])
                    break
        groups.append(group)
    # Orphan report rows must block the whole stage; never infer deletion.
    if any(str(row["research_id"]) not in research for row in reports.values()):
        global_issues.add("orphan_report")
    payload: dict[str, Any] = {
        "schema": "tr-research-policy-stage-v1", "issuer": issuer, "source_sha256": source,
        "directory": sorted(({"username": key, "identity": value} for key, value in identities.items()),
                            key=lambda item: item["username"]),
        "groups": groups, "global_issues": sorted(global_issues),
        "link_states": inventory["summary"]["link_states"],
    }
    payload["plan_sha256"] = _hash(payload)
    payload["summary"] = {
        "researches": len(groups), "reports": len(reports),
        "ready_researches": sum(item["state"] == "ready" for item in groups),
        "needs_repair_researches": sum(item["state"] == "needs_repair" for item in groups),
        "resources_to_stage": sum(len(item["resources"]) for item in groups),
        "grants_to_stage": sum(len(item["grants"]) for item in groups),
        "links_to_bind": sum(len(item["links"]) for item in groups),
        "unresolved_rows": inventory["summary"]["unresolved"],
        "reasons": dict(Counter(reason for item in groups for reason in item["reasons"])),
        "cutover_ready": False,
    }
    return payload


def _verify_backup(database: str | Path, backup: str | Path, expected: str) -> None:
    original, saved = Path(database).resolve(), Path(backup).resolve()
    if original == saved or not saved.is_file():
        raise ValueError("a separate SQLite backup is required")
    uri = saved.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        result = db.execute("PRAGMA quick_check").fetchall()
    if result != [("ok",)] or legacy_authorization_snapshot_sha256(saved) != expected:
        raise ValueError("Research backup is not intact or differs from the reviewed snapshot")
    if legacy_authorization_snapshot_sha256(original) != expected:
        raise ValueError("live Research authorization changed after review")


def _subjects(adapter, directory: list[dict[str, str]]) -> dict[str, str]:
    active = _active_human_subjects(adapter)
    for row in directory:
        stable, name = row["identity"], row["username"]
        user = adapter.user_by_identity_id(stable)
        attributes = user.get("attributes") if isinstance(user, dict) else None
        legacy = attributes.get("legacy_username") if isinstance(attributes, dict) else None
        if legacy is not None and (not isinstance(legacy, list) or len(legacy) != 1 or not isinstance(legacy[0], str)):
            raise AuthorizationUnavailable("Keycloak migration username is ambiguous")
        verified_names = {str(user.get("username") or ""), *(legacy or [])} if isinstance(user, dict) else set()
        if (not isinstance(user, dict) or user.get("enabled") is not True
                or not isinstance(attributes, dict) or attributes.get("tr_identity_id") != [stable]
                or user.get("id") != active.get(stable) or name not in verified_names):
            raise AuthorizationUnavailable("Keycloak migration identity differs from reviewed directory")
    return active


def _expected(group: dict[str, Any], identity: str) -> dict[tuple[str, str, str], bool]:
    results = {}
    grants = group["grants"]
    for resource in group["resources"]:
        kind, ref = resource["kind"], resource["ref"]
        scopes = set(resource["owner_scopes"]) if resource["owner_identity"] == identity else set()
        for grant in grants:
            if (grant["kind"], grant["ref"], grant["identity"]) == (kind, ref, identity):
                scopes.update(grant["scopes"])
        for scope in _ALL_SCOPES:
            results[(kind, ref, scope)] = scope in scopes
    return results


def stage_plan(*, database: str | Path, backup: str | Path, reviewed_plan: dict[str, Any],
               accounts: list[dict[str, Any]], adapter, grants, evaluator: KeycloakResearchPolicyEvaluator,
               record, issuer: str, now: float | None = None) -> dict[str, int]:
    """Idempotently stage ready graphs and compare every scope for every user.

    This is not a cutover receipt. A caller must retain a separate Keycloak
    backup and journal, quiesce legacy writes and verify cross-Manager paths.
    """
    from tools.cli.release.research_reporting.generation import report_workspace_lock
    with report_workspace_lock(Path(database).expanduser().resolve().parent / ".research-policy-stage"):
        return _stage_plan_locked(database=database, backup=backup, reviewed_plan=reviewed_plan,
                                  accounts=accounts, adapter=adapter, grants=grants, evaluator=evaluator,
                                  record=record, issuer=issuer, now=now)


def _stage_plan_locked(*, database: str | Path, backup: str | Path, reviewed_plan: dict[str, Any],
                       accounts: list[dict[str, Any]], adapter, grants, evaluator: KeycloakResearchPolicyEvaluator,
                       record, issuer: str, now: float | None) -> dict[str, int]:
    current = build_plan(database, accounts, issuer=issuer, now=now)
    if (reviewed_plan.get("plan_sha256") != current["plan_sha256"]
            or reviewed_plan.get("source_sha256") != current["source_sha256"]
            or reviewed_plan.get("issuer") != issuer.rstrip("/")):
        raise ValueError("Research migration plan or identity directory changed")
    if current["global_issues"]:
        raise ValueError("unscoped Research migration issues block staging")
    _verify_backup(database, backup, current["source_sha256"])
    subjects = _subjects(adapter, current["directory"])
    actions = decisions = 0
    link_bindings: list[tuple[str, str, str, str, str]] = []
    for group in current["groups"]:
        if group["state"] != "ready":
            continue
        if legacy_authorization_snapshot_sha256(database) != current["source_sha256"]:
            raise ValueError("Research authorization changed during staging")
        for resource in group["resources"]:
            subject = subjects[resource["owner_identity"]]
            intent = _hash(["tr-research-stage-v1", current["issuer"], current["source_sha256"],
                            resource["kind"], resource["ref"]])
            grants.ensure_resource(resource_type=resource["kind"], resource_ref=resource["ref"],
                                   owner_subject=subject, owner_scopes=tuple(resource["owner_scopes"]),
                                   creation_intent=intent)
            record({"event": "resource", "ref_sha256": _hash([resource["kind"], resource["ref"]])})
            actions += 1
        for grant in group["grants"]:
            grants._reconcile_user_grant(resource_type=grant["kind"], resource_ref=grant["ref"],
                                         source=grant["source"], identity_id=grant["identity"],
                                         subject=subjects[grant["identity"]], scopes=grant["scopes"],
                                         require_identical=True)
            record({"event": "grant", "ref_sha256": _hash([grant["kind"], grant["ref"],
                    grant["source"], grant["identity"]])})
            actions += 1
        candidates = [(item["kind"], item["ref"], _ALL_SCOPES) for item in group["resources"]]
        for identity in sorted(subjects):
            expected = _expected(group, identity)
            actual = evaluator.evaluate(identity, candidates=candidates)
            compare_research_decisions(expected, actual)
            decisions += len(actual)
        for link in group["links"]:
            issuer_identity = link["issuer_identity"]
            target_kind = "research" if link["target_kind"] == "research" else "research_report"
            # A link is not an ACL. Its issuer must still have the exact live
            # Keycloak share rights checked on every subsequent redemption.
            grants.require_link_issuer_share(identity_id=issuer_identity, subject=subjects[issuer_identity],
                research_id=group["research_id"], resource_type=target_kind, resource_ref=link["target_ref"])
            claimant = link["claimant_identity"]
            if claimant and not _expected(group, claimant).get((target_kind, link["target_ref"], "read"), False):
                raise AuthorizationUnavailable("redeemed Research link claimant has no migrated access")
            link_bindings.append((link["link_id"], issuer_identity, subjects[issuer_identity],
                                  claimant, subjects[claimant] if claimant else ""))
        record({"event": "scope_parity", "ref_sha256": _hash(group["research_id"])})
    if legacy_authorization_snapshot_sha256(database) != current["source_sha256"] or _subjects(adapter, current["directory"]) != subjects:
        raise ValueError("Research data or Keycloak directory changed during staging")
    if link_bindings:
        # Bind the existing token metadata only after policy parity. Never
        # replace an existing binding or grant: concurrent/revoked state must
        # be reviewed rather than silently resurrected.
        with sqlite3.connect(database, timeout=5) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            if legacy_authorization_snapshot_digest(db) != current["source_sha256"]:
                raise ValueError("Research authorization changed before link binding")
            from server.manager.services.research_share_links import ensure_link_journal
            ensure_link_journal(db)
            for link_id, identity, subject, claimant, claimant_subject in link_bindings:
                existing = db.execute("SELECT identity_id,subject FROM research_share_link_issuers WHERE link_id=?", (link_id,)).fetchone()
                if existing is not None and (existing["identity_id"], existing["subject"]) != (identity, subject):
                    raise ValueError("Research link issuer binding conflicts with migration")
                if existing is None:
                    db.execute("INSERT INTO research_share_link_issuers (link_id,identity_id,subject) VALUES (?,?,?)",
                               (link_id, identity, subject))
                claims = db.execute("SELECT identity_id,subject,status FROM research_share_link_claims WHERE link_id=?", (link_id,)).fetchall()
                if claimant:
                    if claims and (len(claims) != 1 or (claims[0]["identity_id"], claims[0]["subject"], claims[0]["status"]) != (claimant, claimant_subject, "applied")):
                        raise ValueError("Research link claimant binding conflicts with migration")
                    if not claims:
                        db.execute("INSERT INTO research_share_link_claims (link_id,identity_id,subject,status,created_at) VALUES (?,?,?,'applied',?)",
                                   (link_id, claimant, claimant_subject, time.time()))
                elif claims:
                    raise ValueError("Research link has unexpected claims")
            if legacy_authorization_snapshot_digest(db) != current["source_sha256"]:
                raise ValueError("Research authorization changed during link binding")
        for link_id, *_ in link_bindings:
            record({"event": "link_binding", "ref_sha256": _hash(link_id)})
    return {"actions": actions, "scope_decisions": decisions,
            "links_bound": len(link_bindings), "needs_repair_researches": current["summary"]["needs_repair_researches"]}


def _read_private_json(path: str | Path) -> Any:
    import stat
    fd = os.open(Path(path).expanduser(), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError("migration input must be an owner-only regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("migration input exceeds its size budget")
        return json.loads(raw)
    finally:
        os.close(fd)


def _write_private_json(path: str | Path, value: Any) -> None:
    fd = os.open(Path(path).expanduser(), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


class _Journal:
    """Owner-only append log; never consulted to grant permission or skip checks."""
    def __init__(self, path: str | Path, *, plan_sha256: str, issuer: str) -> None:
        import stat
        from tools.cli.release.research_reporting.generation import report_workspace_lock
        journal_path = Path(path).expanduser().absolute()
        self.plan_sha256, self.issuer = plan_sha256, issuer
        self._lock = report_workspace_lock(journal_path.parent / ".research-policy-journal")
        self._lock.__enter__()
        self.fd = -1
        try:
            self.fd = os.open(journal_path, os.O_RDWR | os.O_CREAT | os.O_APPEND
                              | getattr(os, "O_NOFOLLOW", 0), 0o600)
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError("migration journal must be an owner-only regular file")
            if info.st_size > 16 * 1024 * 1024:
                raise ValueError("migration journal exceeds its size budget")
            os.lseek(self.fd, 0, os.SEEK_SET)
            with os.fdopen(self.fd, "rb", closefd=False) as stream:
                raw = stream.read(16 * 1024 * 1024 + 1)
            complete = raw.splitlines(keepends=True)
            valid_length = 0
            recovered = 0
            for index, line in enumerate(complete):
                terminated = line.endswith(b"\n")
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    if index != len(complete) - 1 or terminated or not valid_length:
                        raise ValueError("migration journal contains an invalid record")
                    # A process can die between a partial append and fsync.
                    # The log is not authority: retry all remote operations.
                    os.ftruncate(self.fd, valid_length)
                    recovered = len(line)
                    break
                if not isinstance(value, dict):
                    raise ValueError("migration journal contains an invalid record")
                if value.get("plan_sha256") != plan_sha256 or value.get("issuer") != issuer:
                    raise ValueError("migration journal belongs to another plan or issuer")
                valid_length += len(line)
                if not terminated:
                    # A complete JSON record may have lost only its newline.
                    if os.write(self.fd, b"\n") != 1:
                        raise OSError("short write to migration journal")
                    os.fsync(self.fd)
            if recovered:
                self({"event": "recovered_incomplete_tail", "discarded_bytes": recovered})
        except BaseException:
            if self.fd >= 0:
                os.close(self.fd)
            self._lock.__exit__(None, None, None)
            raise

    def __call__(self, event: dict[str, Any]) -> None:
        raw = (json.dumps({**event, "plan_sha256": self.plan_sha256, "issuer": self.issuer,
                           "at": time.time()}, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if os.write(self.fd, raw) != len(raw):
            raise OSError("short write to migration journal")
        os.fsync(self.fd)

    def close(self) -> None:
        try:
            os.close(self.fd)
        finally:
            self._lock.__exit__(None, None, None)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    preview = subcommands.add_parser("plan", help="write an owner-only reviewed plan")
    preview.add_argument("--database", required=True)
    preview.add_argument("--reviewed-directory", required=True)
    preview.add_argument("--issuer", required=True)
    preview.add_argument("--output", required=True)
    stage = subcommands.add_parser("stage", help="stage ready policies, without switching authority")
    stage.add_argument("--database", required=True)
    stage.add_argument("--backup", required=True)
    stage.add_argument("--reviewed-directory", required=True)
    stage.add_argument("--plan", required=True)
    stage.add_argument("--journal", required=True)
    args = parser.parse_args(argv)
    directory = _read_private_json(args.reviewed_directory)
    accounts = directory.get("accounts") if isinstance(directory, dict) else None
    if not isinstance(accounts, list):
        raise ValueError("reviewed account directory is invalid")
    if args.command == "plan":
        result = build_plan(args.database, accounts, issuer=args.issuer)
        _write_private_json(args.output, result)
        print(json.dumps({**result["summary"], "plan_sha256": result["plan_sha256"]}, sort_keys=True))
        return 0

    reviewed = _read_private_json(args.plan)
    if not isinstance(reviewed, dict) or reviewed.get("schema") != "tr-research-policy-stage-v1":
        raise ValueError("reviewed Research migration plan is invalid")
    from server.identity.user_session import oidc_settings
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    from server.identity.keycloak_research import KeycloakResearchGrantManager
    settings = oidc_settings()
    if settings["issuer"] != reviewed.get("issuer"):
        raise ValueError("configured Keycloak issuer differs from the reviewed plan")
    adapter = manager_keycloak_admin_adapter()
    if adapter.realm != settings["realm"]:
        raise ValueError("Keycloak administration realm differs from the reviewed plan")
    journal = _Journal(args.journal, plan_sha256=reviewed["plan_sha256"], issuer=settings["issuer"])
    try:
        journal({"event": "stage_started"})
        try:
            result = stage_plan(database=args.database, backup=args.backup, reviewed_plan=reviewed,
                                accounts=accounts, adapter=adapter, grants=KeycloakResearchGrantManager(),
                                evaluator=KeycloakResearchPolicyEvaluator(adapter=adapter),
                                record=journal, issuer=settings["issuer"])
        except BaseException as exc:
            journal({"event": "stage_failed", "error_type": type(exc).__name__})
            raise
        journal({"event": "stage_completed", **result})
        print(json.dumps({**result, "cutover_ready": False}, sort_keys=True))
    finally:
        journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
