"""Frozen historical policy oracle for migration fixtures only.

Application modules must never import this fixture. It builds pre-Keycloak
snapshots so parity checks can compare historical allow sets independently.
"""
import hashlib
import time
from typing import Any
from tools.data.sqlite.db import connect_sqlite
from server.manager.services.research_catalog import (
    ResearchCatalog, _access, _loads_list, _principal, _json,
    _authorized_users, VISIBILITIES, KeycloakResearchCreationUnavailable,
)


class HistoricalResearchCatalog(ResearchCatalog):
    def __init__(self, database, *, account_provider=None, **kwargs):
        self._account_provider = account_provider
        super().__init__(database, **kwargs)

    def create_research(self, **kwargs):
        self._seeding_historical_row = True
        try:
            return super().create_research(**kwargs)
        finally:
            self._seeding_historical_row = False

    def require_keycloak_research_creation(self):
        if self._research_authorizer is None and getattr(self, "_seeding_historical_row", False):
            return
        return super().require_keycloak_research_creation()

    def _research_access_values(
        self,
        *,
        research_id: str,
        owner: str,
        status: str,
        visibility: str,
        authorized_users_json: Any,
        viewer: str,
        membership=None,
        profile_access=None,
        keycloak_access=None,
    ) -> dict[str, Any]:
        if self._research_authorizer is not None:
            return super()._research_access_values(research_id=research_id, owner=owner,
                status=status, visibility=visibility, authorized_users_json=authorized_users_json,
                viewer=viewer, membership=membership, profile_access=profile_access,
                keycloak_access=keycloak_access)
        if viewer and viewer == owner:
            return _access(True, True, True, True, "owner", research_id)
        if status == "archived":
            return _access(False, False, False, False, "none", research_id)
        if self._profile_authorizer is not None and (profile_access or {}).get("can_view"):
            return _access(True, True, bool(profile_access.get("can_download")), False, "research", research_id)
        if self._profile_authorizer is None and membership is not None and str(membership["status"]) == "active":
            return _access(
                True, True, True,
                False,  # Membership grants collaboration, never research administration.
                "research", research_id,
            )
        if visibility == "public":
            return _access(True, True, True, False, "research", research_id)
        if visibility == "superiors" and self._is_superior(viewer, owner):
            return _access(True, True, True, False, "research", research_id)
        if viewer and viewer in _loads_list(authorized_users_json):
            return _access(True, True, True, False, "research", research_id)
        return _access(False, False, False, False, "none", research_id)

    def _report_access(
        self, row, viewer: str | None, *, research_access=None, keycloak_access=None,
    ) -> dict[str, Any]:
        viewer_ref = str(viewer or "").strip()
        if self._research_authorizer is not None:
            return super()._report_access(row, viewer, research_access=research_access,
                                          keycloak_access=keycloak_access)
        if viewer_ref and viewer_ref == str(row["owner_ref"]):
            return _access(True, True, True, True, "owner", str(row["report_id"]))
        if research_access is None:
            try:
                research = self._research_row(str(row["research_id"]))
            except KeyError:
                research = None
            if research is not None:
                research_access = self._research_access(research, viewer_ref)
        if research_access and research_access["can_view"]:
            return _access(
                True,
                True,
                research_access["can_download"],
                research_access["can_manage"],
                research_access["access_basis"],
                str(row["report_id"]),
            )
        if str(row["visibility"]) == "public":
            return _access(True, True, False, False, "report", str(row["report_id"]))
        if str(row["visibility"]) == "superiors" and self._is_superior(
            viewer_ref, str(row["owner_ref"]),
        ):
            return _access(True, True, False, False, "report", str(row["report_id"]))
        if viewer_ref and viewer_ref in _loads_list(row["authorized_users_json"]):
            return _access(True, True, False, False, "report", str(row["report_id"]))
        return _access(False, False, False, False, "none", str(row["report_id"]))

    def _is_superior(self, viewer: str, owner: str) -> bool:
        """Resolve the owner's active parent chain from the account authority."""
        if not viewer or not owner or not callable(self._account_provider):
            return False
        try:
            accounts = list(self._account_provider() or [])
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        by_username = {
            str(item.get("username") or "").strip(): item
            for item in accounts if isinstance(item, dict)
        }
        current = owner
        visited: set[str] = set()
        while current and current not in visited:
            visited.add(current)
            account = by_username.get(current)
            if account is None or account.get("active", True) is False:
                return False
            parent = str(account.get("parent_username") or "").strip()
            if parent == viewer:
                superior = by_username.get(parent)
                return superior is not None and superior.get("active", True) is not False
            current = parent
        return False

    def can_read_authoring_publication(self, record, viewer):
        if self._profile_authorizer is not None:
            return super().can_read_authoring_publication(record, viewer)
        if not viewer or not self.can_read_publication(record, viewer):
            return False
        row = self._report_row(str(record["report_id"]))
        if str(row["owner_ref"]) == viewer:
            return True
        with connect_sqlite(self.db_path, readonly=True) as conn:
            return conn.execute(
                """SELECT 1 FROM research_catalog_memberships WHERE research_id=?
                   AND principal_ref=? AND status='active' AND role IN ('owner','editor','contributor')""",
                (str(row["research_id"]), viewer),
            ).fetchone() is not None


    def create_share_link(self, *, target_kind, research_id, actor, report_id="", mode="permanent", expires_at=0):
        if self._research_authorizer is not None:
            return super().create_share_link(target_kind=target_kind, research_id=research_id,
                actor=actor, report_id=report_id, mode=mode, expires_at=expires_at)
        from scripts.test.legacy_research_fixture import seed_share_link
        link = seed_share_link(self.db_path, research_id=research_id, actor=actor, mode=mode,
                               target_kind=target_kind, report_id=report_id)
        with self._write(research_id) as db:
            db.execute("UPDATE research_catalog_share_links SET expires_at=? WHERE link_id=?", (expires_at, link["link_id"]))
        return link

    def redeem_share_link(self, token, *, actor):
        if self._research_authorizer is not None:
            return super().redeem_share_link(token, actor=actor)
        import hashlib, json
        with connect_sqlite(self.db_path) as db:
            link = db.execute("SELECT * FROM research_catalog_share_links WHERE token_hash=?",
                              (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        with self._write(link["research_id"]) as db:
            row = db.execute("SELECT authorized_users_json FROM research_catalog_researches WHERE research_id=?", (link["research_id"],)).fetchone()
            users = sorted(set(_loads_list(row["authorized_users_json"]) + [actor]))
            db.execute("UPDATE research_catalog_researches SET authorized_users_json=? WHERE research_id=?", (json.dumps(users), link["research_id"]))
        return {"research_id": link["research_id"]}

    def migrate_reports(
        self, records: list[dict[str, Any]], *, actor: str,
    ) -> dict[str, Any]:
        """Idempotently import report metadata supplied by existing stores.

        The method accepts projections from client/server/public report stores
        rather than importing those stores itself.  This keeps the migration
        explicit and makes it possible to run once against each source without
        making request-time reads mutate the catalog.
        """
        if self._research_authorizer is not None:
            raise KeycloakResearchCreationUnavailable("Legacy report import requires a Keycloak migration")
        principal = _principal(actor)
        canonical_report_ids, legacy_report_ids = _canonical_migration_report_ids(
            records, principal,
        )
        counts = {"seen": 0, "migrated": 0, "already_migrated": 0, "failed": 0}
        results: list[dict[str, Any]] = []
        for item in records:
            counts["seen"] += 1
            if not isinstance(item, dict):
                counts["failed"] += 1
                results.append({"status": "failed", "error": "report record must be an object"})
                continue
            source_kind = str(item.get("source_kind") or item.get("source") or "report")
            source_ref = str(item.get("source_ref") or item.get("report_id") or "").strip()
            owner = str(item.get("owner_ref") or principal).strip()
            report_id = canonical_report_ids.get(
                _legacy_report_workspace_key(item, principal),
                legacy_report_ids.get(
                    str(item.get("report_id") or "").strip(),
                    str(item.get("report_id") or source_ref).strip(),
                ),
            )
            if not source_ref or not report_id or owner != principal:
                counts["failed"] += 1
                results.append({
                    "source_ref": source_ref,
                    "status": "failed",
                    "error": "owner, source_ref and report_id are required",
                })
                continue
            try:
                result = self._migrate_one_report(
                    item,
                    actor=principal,
                    source_kind=source_kind,
                    source_ref=source_ref,
                    report_id=report_id,
                )
            except (KeyError, TypeError, ValueError, PermissionError) as exc:
                self._mark_migration_failed(
                    source_kind=source_kind,
                    source_ref=source_ref,
                    owner=principal,
                    error=str(exc),
                )
                counts["failed"] += 1
                results.append({
                    "source_ref": source_ref,
                    "status": "failed",
                    "error": str(exc),
                })
                continue
            counts["already_migrated" if result["status"] == "already_migrated" else "migrated"] += 1
            results.append(result)
        return {"status": "completed", "counts": counts, "items": results}

    def _migrate_one_report(
        self,
        item: dict[str, Any],
        *,
        actor: str,
        source_kind: str,
        source_ref: str,
        report_id: str,
    ) -> dict[str, Any]:
        # Branches and replicated/public projections are provenance of one
        # Report, not separate Research roots.  The durable Research identity
        # therefore follows owner + report_id; each source still receives its
        # own idempotent migration receipt below.
        migration_key = f"report:{actor}:{report_id}"
        research_id = "research:migrated:" + hashlib.sha256(
            migration_key.encode("utf-8")
        ).hexdigest()[:32]
        title = str(item.get("title") or report_id).strip() or report_id
        profile_ref = str(item.get("profile_ref") or item.get("profile_id") or "").strip()
        visibility = str(
            item.get("visibility")
            or ("superiors" if source_kind == "publication" else "private")
        )
        if visibility not in VISIBILITIES:
            visibility = "private"
        if source_kind == "publication" and visibility == "private":
            visibility = "superiors"
        now = time.time()
        with connect_sqlite(self.db_path) as conn:
            existing_research = conn.execute(
                "SELECT visibility FROM research_catalog_researches WHERE research_id=?",
                (research_id,),
            ).fetchone()
            if (
                not item.get("visibility") and source_kind != "publication"
                and existing_research is not None
                and str(existing_research["visibility"]) != "private"
            ):
                visibility = str(existing_research["visibility"])
            existing_migration = conn.execute(
                """SELECT * FROM research_catalog_migrations
                   WHERE source_kind=? AND source_ref=? AND owner_ref=?""",
                (source_kind, source_ref, actor),
            ).fetchone()
            if existing_migration is not None and existing_migration["status"] == "completed":
                return {
                    "status": "already_migrated",
                    "source_ref": source_ref,
                    "research_id": str(existing_migration["research_id"]),
                    "report_id": report_id,
                }
            conn.execute(
                """INSERT INTO research_catalog_researches
                   (research_id, owner_ref, title, description, status,
                    visibility, authorized_users_json, migration_source,
                    created_at, updated_at)
                   VALUES (?, ?, ?, '', 'active', ?, ?, ?, ?, ?)
                   ON CONFLICT(research_id) DO UPDATE SET
                     title=excluded.title, visibility=excluded.visibility,
                     authorized_users_json=excluded.authorized_users_json,
                     updated_at=excluded.updated_at""",
                (
                    research_id, actor, title, visibility,
                    _json(_authorized_users(item.get("authorized_users") or [], actor)),
                    migration_key, now, now,
                ),
            )
            conn.execute(
                """INSERT INTO research_catalog_migrations
                   (migration_ref, source_kind, source_ref, owner_ref,
                    research_id, status, error, created_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, 'running', '', ?, 0)
                   ON CONFLICT(source_kind, source_ref, owner_ref) DO UPDATE SET
                     research_id=excluded.research_id, status='running', error='',
                     completed_at=0""",
                (
                    "research-migration:v1:" + hashlib.sha256(
                        f"{source_kind}\x1f{source_ref}\x1f{actor}".encode()
                    ).hexdigest(),
                    source_kind, source_ref, actor, research_id, now,
                ),
            )
        # An old source may carry a workspace identifier from a different
        # store. Only a workspace created in this Research catalog is a valid
        # relationship; dangling legacy identifiers must not be persisted.
        workspace_id = ""
        if profile_ref:
            self.add_membership(
                research_id,
                actor=actor,
                principal_ref=str(item.get("profile_owner_ref") or actor),
                profile_ref=profile_ref,
                role="owner",
            )
            existing_workspaces = self.list_workspaces(
                research_id, viewer=actor,
            )
            workspace = next(
                (
                    value for value in existing_workspaces
                    if str(value.get("profile_ref") or "") == profile_ref
                ),
                None,
            )
            if workspace is None:
                workspace = self.create_workspace(
                    research_id,
                    actor=actor,
                    principal_ref=str(item.get("profile_owner_ref") or actor),
                    profile_ref=profile_ref,
                    title=f"{title} / {profile_ref}",
                )
            workspace_id = str(workspace["workspace_id"])
        self.register_report(
            research_id,
            actor=actor,
            report_id=report_id,
            title=title,
            profile_ref=profile_ref,
            workspace_id=workspace_id,
            build_source=str(item.get("build_source") or "client"),
            build_source_ref=str(item.get("build_source_ref") or ""),
            visibility=visibility,
            authorized_users=list(item.get("authorized_users") or []),
            source_ref=source_ref,
        )
        evidence_refs = item.get("evidence_refs") or []
        for evidence_ref in evidence_refs:
            self.link_evidence(
                research_id,
                actor=actor,
                evidence_ref=str(evidence_ref),
                evidence_owner_ref=str(item.get("evidence_owner_ref") or actor),
                report_id=report_id,
                profile_ref=profile_ref,
                purpose="migrated report reference",
            )
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                """UPDATE research_catalog_migrations
                   SET status='completed', completed_at=?, error=''
                   WHERE source_kind=? AND source_ref=? AND owner_ref=?""",
                (time.time(), source_kind, source_ref, actor),
            )
        return {
            "status": "migrated",
            "source_ref": source_ref,
            "research_id": research_id,
            "report_id": report_id,
        }

    def _mark_migration_failed(
        self, *, source_kind: str, source_ref: str, owner: str, error: str,
    ) -> None:
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                """UPDATE research_catalog_migrations
                   SET status='failed', error=?, completed_at=?
                   WHERE source_kind=? AND source_ref=? AND owner_ref=?""",
                (str(error)[:2000], time.time(), source_kind, source_ref, owner),
            )



def _legacy_report_branch_group_key(
    item: dict[str, Any], owner: str,
) -> tuple[str, str, str] | None:
    """Group old per-Branch records while migrating stable Report identities."""
    legacy_workspace_id = str(
        item.get("work_package_id") or item.get("record_id") or ""
    ).strip()
    if not legacy_workspace_id:
        return None
    profile_ref = str(
        item.get("profile_ref") or item.get("profile_id") or ""
    ).strip()
    return owner, profile_ref, legacy_workspace_id


def _legacy_report_workspace_key(
    item: dict[str, Any], owner: str,
) -> tuple[str, str, str] | None:
    """Normalize pre-ReportWorkspace package IDs during import."""
    return _legacy_report_branch_group_key(item, owner)


def _canonical_migration_report_ids(
    records: list[dict[str, Any]], owner: str,
) -> tuple[dict[tuple[str, str, str] | None, str], dict[str, str]]:
    """Collapse old per-Branch report IDs into one stable Report identity."""
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        key = _legacy_report_branch_group_key(item, owner)
        report_id = str(item.get("report_id") or "").strip()
        if key is not None and report_id:
            grouped.setdefault(key, set()).add(report_id)
    result: dict[tuple[str, str, str] | None, str] = {}
    aliases: dict[str, set[str]] = {}
    for key, report_ids in grouped.items():
        if len(report_ids) == 1:
            result[key] = next(iter(report_ids))
            continue
        stable_key = "\x1f".join(key)
        result[key] = "report-migrated-" + hashlib.sha256(
            stable_key.encode()
        ).hexdigest()[:24]
        for legacy_report_id in report_ids:
            aliases.setdefault(legacy_report_id, set()).add(result[key])
    return result, {
        legacy_report_id: next(iter(canonical_ids))
        for legacy_report_id, canonical_ids in aliases.items()
        if len(canonical_ids) == 1
    }
