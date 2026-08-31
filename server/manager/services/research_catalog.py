"""Manager-owned Research catalog and shared access policy.

The catalog is deliberately small and metadata-only.  Report bytes, factor
workspaces, and Evidence source bytes remain in their existing stores; this
service records their durable Research relationships and resolves the one
access decision used by Manager projections and object transfer routes.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

from tools.data.sqlite.db import connect_sqlite

VISIBILITIES = frozenset({"private", "authorized", "public"})
RESEARCH_STATUSES = frozenset({"active", "archived"})
MEMBER_ROLES = frozenset({"owner", "editor", "contributor", "viewer"})
MEMBER_STATUSES = frozenset({"active", "invited", "revoked"})
RESEARCH_SCOPES = frozenset({"all", "mine", "subordinates", "shared"})


class ResearchCatalog:
    """Persist Research relationships in the Manager-owned SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect_sqlite(self.db_path) as conn:
            legacy = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='research_catalog_evidence_links'"
            ).fetchone()
            current = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='research_catalog_report_evidence_links'"
            ).fetchone()
            if legacy is not None and current is None:
                raise RuntimeError(
                    "research catalog requires the explicit Report-Evidence "
                    "schema migration"
                )
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_catalog_researches (
                    research_id TEXT PRIMARY KEY,
                    owner_ref TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    authorized_users_json TEXT NOT NULL,
                    migration_source TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_catalog_memberships (
                    research_id TEXT NOT NULL,
                    principal_ref TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    invited_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(research_id, profile_ref),
                    FOREIGN KEY(research_id)
                      REFERENCES research_catalog_researches(research_id)
                );
                CREATE TABLE IF NOT EXISTS research_catalog_workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    research_id TEXT NOT NULL,
                    principal_ref TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(research_id, profile_ref),
                    FOREIGN KEY(research_id)
                      REFERENCES research_catalog_researches(research_id)
                );
                CREATE TABLE IF NOT EXISTS research_catalog_reports (
                    report_id TEXT PRIMARY KEY,
                    research_id TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    title TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    build_source TEXT NOT NULL,
                    build_source_ref TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    authorized_users_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(research_id)
                      REFERENCES research_catalog_researches(research_id)
                );
                CREATE TABLE IF NOT EXISTS research_catalog_report_evidence_links (
                    link_ref TEXT PRIMARY KEY,
                    evidence_ref TEXT NOT NULL,
                    evidence_owner_ref TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    graph_ref TEXT NOT NULL,
                    branch_ref TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    profile_ref TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    revoked_at REAL NOT NULL,
                    FOREIGN KEY(report_id)
                      REFERENCES research_catalog_reports(report_id)
                );
                CREATE TABLE IF NOT EXISTS research_catalog_migrations (
                    migration_ref TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    research_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    completed_at REAL NOT NULL,
                    UNIQUE(source_kind, source_ref, owner_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_research_catalog_owner
                    ON research_catalog_researches(owner_ref, updated_at);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_members_principal
                    ON research_catalog_memberships(principal_ref, status);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_workspace_research
                    ON research_catalog_workspaces(research_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_report_research
                    ON research_catalog_reports(research_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_evidence
                    ON research_catalog_report_evidence_links(evidence_ref, status);
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_research_catalog_migration_identity
                    ON research_catalog_researches(owner_ref, migration_source)
                    WHERE migration_source <> '';
                """
            )

    # ------------------------------------------------------------------
    # Research, membership, workspace, and report records

    def create_research(
        self,
        *,
        owner_ref: str,
        title: str,
        description: str = "",
        visibility: str = "private",
        authorized_users: list[str] | tuple[str, ...] | None = None,
        profile_ref: str = "",
    ) -> dict[str, Any]:
        owner = _principal(owner_ref)
        clean_title = _text(title, "title", maximum=256)
        clean_description = _text(
            description, "description", maximum=10000, allow_empty=True,
        )
        clean_visibility = _visibility(visibility)
        users = _authorized_users(authorized_users, owner)
        research_id = "research:v1:" + secrets.token_urlsafe(18)
        now = time.time()
        initial_workspace = None
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                """INSERT INTO research_catalog_researches
                   (research_id, owner_ref, title, description, status,
                    visibility, authorized_users_json, migration_source,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, '', ?, ?)""",
                (
                    research_id, owner, clean_title, clean_description,
                    clean_visibility, _json(users), now, now,
                ),
            )
            if profile_ref:
                profile = _profile(profile_ref)
                self._upsert_membership(
                    conn,
                    research_id=research_id,
                    principal_ref=owner,
                    profile_ref=profile,
                    role="owner",
                    status="active",
                    invited_by=owner,
                    now=now,
                )
                workspace_id = "research-workspace:v1:" + secrets.token_urlsafe(18)
                conn.execute(
                    """INSERT INTO research_catalog_workspaces
                       (workspace_id, research_id, principal_ref, profile_ref,
                        title, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                    (
                        workspace_id, research_id, owner, profile,
                        f"{clean_title} / {profile}", now, now,
                    ),
                )
                initial_workspace = conn.execute(
                    """SELECT * FROM research_catalog_workspaces
                       WHERE workspace_id=?""",
                    (workspace_id,),
                ).fetchone()
            row = conn.execute(
                "SELECT * FROM research_catalog_researches WHERE research_id=?",
                (research_id,),
            ).fetchone()
        value = self._research_value(row, viewer=owner)
        if initial_workspace is not None:
            value["workspaces"] = [self._workspace_value(initial_workspace)]
        return value

    def list_researches(
        self,
        *,
        viewer: str | None,
        include_archived: bool = False,
        scope: str = "all",
        subordinate_refs: list[str] | tuple[str, ...] | set[str] = (),
    ) -> list[dict[str, Any]]:
        selected_scope = _choice(scope, RESEARCH_SCOPES, "research scope")
        subordinate_set = {
            str(item or "").strip() for item in subordinate_refs if str(item or "").strip()
        }
        viewer_ref = str(viewer or "").strip()
        self.ensure_schema()
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT research.*,
                          membership.role AS viewer_member_role,
                          membership.status AS viewer_member_status
                     FROM research_catalog_researches AS research
                     LEFT JOIN research_catalog_memberships AS membership
                       ON membership.research_id=research.research_id
                      AND membership.principal_ref=?
                      AND membership.status='active'
                    ORDER BY research.updated_at DESC, research.research_id""",
                (viewer_ref,),
            ).fetchall()
        result = []
        for row in rows:
            if not include_archived and row["status"] == "archived":
                continue
            membership = None
            if row["viewer_member_status"]:
                membership = {
                    "role": row["viewer_member_role"],
                    "status": row["viewer_member_status"],
                }
            access = self._research_access_values(
                research_id=str(row["research_id"]),
                owner=str(row["owner_ref"]),
                status=str(row["status"]),
                visibility=str(row["visibility"]),
                authorized_users_json=row["authorized_users_json"],
                viewer=viewer_ref,
                membership=membership,
            )
            if not access["can_view"]:
                continue
            owner = str(row["owner_ref"])
            if selected_scope == "mine" and owner != viewer_ref:
                continue
            if selected_scope == "subordinates" and owner not in subordinate_set:
                continue
            if selected_scope == "shared" and owner == viewer_ref:
                continue
            result.append(self._research_value(row, viewer=viewer, access=access))
        return result

    def get_research(
        self, research_id: str, *, viewer: str | None,
    ) -> dict[str, Any]:
        # The CLI ``show`` command keeps its complete projection, while Web
        # detail pages call the child readers below one tab at a time.
        value = self._viewable_research(research_id, viewer=viewer)
        value.update(
            members=self.list_members(research_id, viewer=viewer),
            workspaces=self.list_workspaces(research_id, viewer=viewer),
            reports=self.list_reports(research_id, viewer=viewer),
            evidence_links=self.list_evidence_links(research_id, viewer=viewer),
        )
        return value

    def get_research_summary(
        self, research_id: str, *, viewer: str | None,
    ) -> dict[str, Any]:
        """Read only the Research row for a lazy detail-page header.

        The Web detail page must not download every report, workspace, member,
        or Evidence link merely to render its first tab.  The complete
        projection remains available through ``get_research`` for the CLI and
        callers that explicitly request the full object.
        """
        return self._viewable_research(research_id, viewer=viewer)

    def list_members(
        self, research_id: str, *, viewer: str | None,
    ) -> list[dict[str, Any]]:
        self._viewable_research(research_id, viewer=viewer)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT * FROM research_catalog_memberships
                   WHERE research_id=? ORDER BY created_at, profile_ref""",
                (research_id,),
            ).fetchall()
        return [self._membership_value(item) for item in rows]

    def list_workspaces(
        self, research_id: str, *, viewer: str | None,
    ) -> list[dict[str, Any]]:
        self._viewable_research(research_id, viewer=viewer)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT * FROM research_catalog_workspaces
                   WHERE research_id=? ORDER BY updated_at DESC, workspace_id""",
                (research_id,),
            ).fetchall()
        return [self._workspace_value(item) for item in rows]

    def list_reports(
        self, research_id: str, *, viewer: str | None,
    ) -> list[dict[str, Any]]:
        self._viewable_research(research_id, viewer=viewer)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT * FROM research_catalog_reports
                   WHERE research_id=? AND status='active'
                   ORDER BY updated_at DESC, report_id""",
                (research_id,),
            ).fetchall()
        return [self._report_value(item, viewer=viewer) for item in rows]

    def list_reports_for_scope(
        self,
        *,
        viewer: str | None,
        scope: str = "all",
        subordinate_refs: list[str] | tuple[str, ...] | set[str] = (),
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """List visible Reports through the canonical Research projection.

        This is a metadata-only reader for the root Research > Reports view.
        It deliberately joins the Research row in one query and preloads the
        viewer's memberships, so changing report scopes does not turn into an
        N+1 request/query chain.  Report bytes and chapter/object retrieval
        remain owned by their existing object adapters.
        """
        selected_scope = _choice(scope, RESEARCH_SCOPES, "research scope")
        viewer_ref = str(viewer or "").strip()
        subordinate_set = {
            str(item or "").strip()
            for item in subordinate_refs
            if str(item or "").strip()
        }
        self.ensure_schema()
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT report.*,
                          research.title AS research_title,
                          research.description AS research_description,
                          research.owner_ref AS research_owner_ref,
                          research.status AS research_status,
                          research.visibility AS research_visibility,
                          research.authorized_users_json AS research_authorized_users_json
                   FROM research_catalog_reports AS report
                   JOIN research_catalog_researches AS research
                     ON research.research_id=report.research_id
                  WHERE report.status='active'
                  ORDER BY report.updated_at DESC, report.report_id""",
            ).fetchall()
            memberships = {
                str(item["research_id"]): item
                for item in conn.execute(
                    """SELECT research_id, role, status
                       FROM research_catalog_memberships
                      WHERE principal_ref=? AND status='active'""",
                    (viewer_ref,),
                ).fetchall()
            } if viewer_ref else {}

        result: list[dict[str, Any]] = []
        for row in rows:
            research_owner = str(row["research_owner_ref"])
            if not include_archived and str(row["research_status"]) == "archived":
                continue
            if selected_scope == "mine" and research_owner != viewer_ref:
                continue
            if selected_scope == "subordinates" and research_owner not in subordinate_set:
                continue
            if selected_scope == "shared" and research_owner == viewer_ref:
                continue

            research_access = self._research_access_values(
                research_id=str(row["research_id"]),
                owner=research_owner,
                status=str(row["research_status"]),
                visibility=str(row["research_visibility"]),
                authorized_users_json=row["research_authorized_users_json"],
                viewer=viewer_ref,
                membership=memberships.get(str(row["research_id"])),
            )
            report_access = self._report_access(
                row, viewer_ref, research_access=research_access,
            )
            if not research_access["can_view"] and not report_access["can_view"]:
                continue
            value = self._report_value(
                row,
                viewer=viewer_ref,
                access=_stronger_access(research_access, report_access),
            )
            value["research"] = {
                "research_id": str(row["research_id"]),
                "title": str(row["research_title"]),
                "owner_ref": research_owner,
                "status": str(row["research_status"]),
                "visibility": str(row["research_visibility"]),
            }
            result.append(value)
        return result

    def list_evidence_links(
        self, research_id: str, *, viewer: str | None,
    ) -> list[dict[str, Any]]:
        self._viewable_research(research_id, viewer=viewer)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT link.*, report.research_id
                     FROM research_catalog_report_evidence_links link
                     JOIN research_catalog_reports report
                       ON report.report_id=link.report_id
                    WHERE report.research_id=? AND link.status='active'
                    ORDER BY link.created_at DESC, link.link_ref""",
                (research_id,),
            ).fetchall()
        return [self._evidence_link_value(item) for item in rows]

    def research_manifest(
        self, research_id: str, *, viewer: str | None,
    ) -> dict[str, Any]:
        """Return the bounded relationship manifest; never include object bytes."""
        research = self._viewable_research(research_id, viewer=viewer)
        reports = self.list_reports(research_id, viewer=viewer)
        links = self.list_evidence_links(research_id, viewer=viewer)
        return {
            "schema_version": 1,
            "research": research,
            "reports": reports,
            "evidence_links": [{
                **link,
                "access": self.resolve_evidence_access(
                    evidence_ref=link["evidence_ref"], viewer=viewer,
                ),
            } for link in links],
            "workspaces": self.list_workspaces(research_id, viewer=viewer),
            "generated_at": time.time(),
        }

    def update_research(
        self,
        research_id: str,
        *,
        actor: str,
        title: str | None = None,
        description: str | None = None,
        visibility: str | None = None,
        authorized_users: list[str] | tuple[str, ...] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        row = self._research_row(research_id)
        access = self._research_access(row, actor)
        if not access["can_manage"]:
            raise PermissionError("research management is not authorized")
        values: dict[str, Any] = {}
        if title is not None:
            values["title"] = _text(title, "title", maximum=256)
        if description is not None:
            values["description"] = _text(
                description, "description", maximum=10000, allow_empty=True,
            )
        if visibility is not None:
            values["visibility"] = _visibility(visibility)
        if authorized_users is not None:
            values["authorized_users_json"] = _json(
                _authorized_users(authorized_users, str(row["owner_ref"])),
            )
        if status is not None:
            values["status"] = _status(status)
        if not values:
            return self._research_value(row, viewer=actor, access=access)
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{key}=?" for key in values)
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                f"UPDATE research_catalog_researches SET {assignments} WHERE research_id=?",
                (*values.values(), research_id),
            )
            updated = conn.execute(
                "SELECT * FROM research_catalog_researches WHERE research_id=?",
                (research_id,),
            ).fetchone()
        return self._research_value(updated, viewer=actor)

    def add_membership(
        self,
        research_id: str,
        *,
        actor: str,
        principal_ref: str,
        profile_ref: str,
        role: str = "contributor",
        status: str = "active",
    ) -> dict[str, Any]:
        row = self._research_row(research_id)
        if not self._research_access(row, actor)["can_manage"]:
            raise PermissionError("research membership management is not authorized")
        principal = _principal(principal_ref)
        profile = _profile(profile_ref)
        clean_role = _choice(role, MEMBER_ROLES, "member role")
        clean_status = _choice(status, MEMBER_STATUSES, "member status")
        now = time.time()
        with connect_sqlite(self.db_path) as conn:
            self._upsert_membership(
                conn,
                research_id=research_id,
                principal_ref=principal,
                profile_ref=profile,
                role=clean_role,
                status=clean_status,
                invited_by=_principal(actor),
                now=now,
            )
            value = conn.execute(
                """SELECT * FROM research_catalog_memberships
                   WHERE research_id=? AND profile_ref=?""",
                (research_id, profile),
            ).fetchone()
        return self._membership_value(value)

    def create_workspace(
        self,
        research_id: str,
        *,
        actor: str,
        principal_ref: str,
        profile_ref: str,
        title: str = "",
    ) -> dict[str, Any]:
        row = self._research_row(research_id)
        if not self._research_access(row, actor)["can_manage"]:
            raise PermissionError("research workspace management is not authorized")
        principal = _principal(principal_ref)
        profile = _profile(profile_ref)
        clean_title = _text(
            title or profile, "title", maximum=256, allow_empty=False,
        )
        workspace_id = "research-workspace:v1:" + secrets.token_urlsafe(18)
        now = time.time()
        with connect_sqlite(self.db_path) as conn:
            membership = conn.execute(
                """SELECT status FROM research_catalog_memberships
                   WHERE research_id=? AND profile_ref=?""",
                (research_id, profile),
            ).fetchone()
            if membership is None or str(membership["status"]) != "active":
                raise ValueError("profile must be an active research member")
            existing = conn.execute(
                """SELECT * FROM research_catalog_workspaces
                   WHERE research_id=? AND profile_ref=?""",
                (research_id, profile),
            ).fetchone()
            if existing is not None:
                return self._workspace_value(existing)
            conn.execute(
                """INSERT INTO research_catalog_workspaces
                   (workspace_id, research_id, principal_ref, profile_ref,
                    title, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                (workspace_id, research_id, principal, profile, clean_title, now, now),
            )
            value = conn.execute(
                "SELECT * FROM research_catalog_workspaces WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
        return self._workspace_value(value)

    def register_report(
        self,
        research_id: str,
        *,
        actor: str,
        report_id: str,
        title: str = "",
        profile_ref: str = "",
        workspace_id: str = "",
        build_source: str = "client",
        build_source_ref: str = "",
        visibility: str = "private",
        authorized_users: list[str] | tuple[str, ...] | None = None,
        source_ref: str = "",
    ) -> dict[str, Any]:
        row = self._research_row(research_id)
        if not self._research_access(row, actor)["can_manage"]:
            raise PermissionError("research report management is not authorized")
        report = _text(report_id, "report_id", maximum=256)
        clean_title = _text(
            title or report, "title", maximum=256, allow_empty=False,
        )
        source = _text(
            build_source or "client", "build_source", maximum=64, allow_empty=False,
        )
        clean_visibility = _visibility(visibility)
        users = _authorized_users(authorized_users, str(row["owner_ref"]))
        clean_profile = _optional_profile(profile_ref)
        clean_workspace = str(workspace_id or "").strip()
        now = time.time()
        with connect_sqlite(self.db_path) as conn:
            if clean_workspace:
                workspace = conn.execute(
                    """SELECT workspace_id, research_id, profile_ref, status
                         FROM research_catalog_workspaces
                        WHERE workspace_id=?""",
                    (clean_workspace,),
                ).fetchone()
                if workspace is None:
                    raise ValueError("research workspace not found")
                if str(workspace["research_id"]) != research_id:
                    raise ValueError("research workspace does not belong to research")
                if str(workspace["status"]) != "active":
                    raise ValueError("research workspace is not active")
                workspace_profile = _optional_profile(workspace["profile_ref"])
                if clean_profile and clean_profile != workspace_profile:
                    raise ValueError("report profile does not match research workspace")
                clean_profile = workspace_profile
            if clean_profile:
                membership = conn.execute(
                    """SELECT status FROM research_catalog_memberships
                        WHERE research_id=? AND profile_ref=?""",
                    (research_id, clean_profile),
                ).fetchone()
                if membership is None or str(membership["status"]) != "active":
                    raise ValueError("report profile must be an active research member")
            existing = conn.execute(
                "SELECT * FROM research_catalog_reports WHERE report_id=?",
                (report,),
            ).fetchone()
            if existing is not None and str(existing["research_id"]) != research_id:
                raise ValueError("report is already linked to another research")
            conn.execute(
                """INSERT INTO research_catalog_reports
                   (report_id, research_id, owner_ref, title, profile_ref,
                    workspace_id, build_source, build_source_ref, visibility,
                    authorized_users_json, status, source_ref, created_at,
                    updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                   ON CONFLICT(report_id) DO UPDATE SET
                     title=excluded.title, profile_ref=excluded.profile_ref,
                     workspace_id=excluded.workspace_id,
                     build_source=excluded.build_source,
                     build_source_ref=excluded.build_source_ref,
                     visibility=excluded.visibility,
                     authorized_users_json=excluded.authorized_users_json,
                     status='active', source_ref=excluded.source_ref,
                     updated_at=excluded.updated_at""",
                (
                    report, research_id, str(row["owner_ref"]), clean_title,
                    clean_profile, clean_workspace,
                    source, str(build_source_ref or "").strip(),
                    clean_visibility, _json(users), str(source_ref or ""),
                    now, now,
                ),
            )
            value = conn.execute(
                "SELECT * FROM research_catalog_reports WHERE report_id=?",
                (report,),
            ).fetchone()
        return self._report_value(value, viewer=actor)

    # ------------------------------------------------------------------
    # Evidence links and access

    def link_evidence(
        self,
        research_id: str,
        *,
        actor: str,
        evidence_ref: str,
        evidence_owner_ref: str = "",
        report_id: str = "",
        graph_ref: str = "",
        branch_ref: str = "",
        job_id: str = "",
        profile_ref: str = "",
        purpose: str = "",
    ) -> dict[str, Any]:
        row = self._research_row(research_id)
        if not self._research_access(row, actor)["can_manage"]:
            raise PermissionError("research Evidence management is not authorized")
        evidence = _text(evidence_ref, "evidence_ref", maximum=512)
        report = _text(report_id, "report_id", maximum=256)
        report_row = self._report_row(report)
        if str(report_row["research_id"]) != research_id:
            raise ValueError("report does not belong to research")
        if str(report_row["status"]) != "active":
            raise ValueError("report is not active")
        owner = _principal(evidence_owner_ref or actor)
        values = {
            "evidence_ref": evidence,
            "evidence_owner_ref": owner,
            "report_id": report,
            "graph_ref": str(graph_ref or "").strip(),
            "branch_ref": str(branch_ref or "").strip(),
            "job_id": str(job_id or "").strip(),
            "profile_ref": str(profile_ref or "").strip(),
            "purpose": str(purpose or "").strip(),
        }
        link_ref = "evidence-link:v1:" + hashlib.sha256(
            _json(values).encode("utf-8")
        ).hexdigest()
        now = time.time()
        with connect_sqlite(self.db_path) as conn:
            existing_owner = conn.execute(
                """SELECT DISTINCT evidence_owner_ref
                   FROM research_catalog_report_evidence_links
                   WHERE evidence_ref=? AND status='active'""",
                (evidence,),
            ).fetchall()
            if any(str(item["evidence_owner_ref"]) != owner for item in existing_owner):
                raise ValueError("evidence owner does not match existing links")
            conn.execute(
                """INSERT INTO research_catalog_report_evidence_links
                   (link_ref, evidence_ref, evidence_owner_ref,
                    report_id, graph_ref, branch_ref, job_id, profile_ref,
                    purpose, status, created_at, revoked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 0)
                   ON CONFLICT(link_ref) DO UPDATE SET status='active', revoked_at=0""",
                (
                    link_ref, values["evidence_ref"], values["evidence_owner_ref"],
                    values["report_id"],
                    values["graph_ref"], values["branch_ref"], values["job_id"],
                    values["profile_ref"], values["purpose"], now,
                ),
            )
            value = conn.execute(
                """SELECT link.*, report.research_id
                     FROM research_catalog_report_evidence_links link
                     JOIN research_catalog_reports report
                       ON report.report_id=link.report_id
                    WHERE link.link_ref=?""",
                (link_ref,),
            ).fetchone()
        return self._evidence_link_value(value)

    def resolve_evidence_access(
        self,
        *,
        evidence_ref: str,
        viewer: str | None,
    ) -> dict[str, Any]:
        """Resolve rights from Evidence ownership and its Report bindings.

        Evidence remains independent from Research.  A containing Research can
        broaden access only transitively through a Report that cites it.
        """
        target = _text(evidence_ref, "evidence_ref", maximum=512)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            links = conn.execute(
                """SELECT link.*, report.research_id
                     FROM research_catalog_report_evidence_links link
                     JOIN research_catalog_reports report
                       ON report.report_id=link.report_id
                    WHERE link.evidence_ref=? AND link.status='active'
                      AND report.status='active'""",
                (target,),
            ).fetchall()
        if not links:
            return _access(False, False, False, False, "none", target)
        viewer_ref = str(viewer or "").strip()
        if any(str(item["evidence_owner_ref"]) == viewer_ref for item in links):
            return _access(True, True, True, True, "owner", target)

        for link in links:
            try:
                research = self._research_row(str(link["research_id"]))
            except KeyError:
                continue
            research_access = self._research_access(research, viewer)
            if research_access["can_download"]:
                return _access(
                    True, True, True, False, "research", target,
                )

        for link in links:
            if not str(link["report_id"]):
                continue
            try:
                report = self._report_row(str(link["report_id"]))
            except KeyError:
                continue
            if self._report_access(report, viewer)["can_view"]:
                return _access(
                    True, True, False, False, "report", target,
                )
        return _access(False, False, False, False, "none", target)

    def evidence_owner_ref(self, evidence_ref: str) -> str:
        """Return the owner needed to read the existing Evidence registry."""
        target = _text(evidence_ref, "evidence_ref", maximum=512)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            row = conn.execute(
                """SELECT evidence_owner_ref
                   FROM research_catalog_report_evidence_links
                   WHERE evidence_ref=? AND status='active'
                   ORDER BY created_at DESC, link_ref LIMIT 1""",
                (target,),
            ).fetchone()
        if row is None:
            raise KeyError("evidence is not linked by a report")
        return str(row["evidence_owner_ref"])

    # ------------------------------------------------------------------
    # Explicit report migration

    def migrate_reports(
        self, records: list[dict[str, Any]], *, actor: str,
    ) -> dict[str, Any]:
        """Idempotently import report metadata supplied by existing stores.

        The method accepts projections from client/server/public report stores
        rather than importing those stores itself.  This keeps the migration
        explicit and makes it possible to run once against each source without
        making request-time reads mutate the catalog.
        """
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
                _migration_work_package_key(item, principal),
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
        visibility = str(item.get("visibility") or "private")
        if visibility not in VISIBILITIES:
            visibility = "private"
        now = time.time()
        with connect_sqlite(self.db_path) as conn:
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

    # ------------------------------------------------------------------
    # Internal readers and serializers

    def _viewable_research(
        self, research_id: str, *, viewer: str | None,
    ) -> dict[str, Any]:
        row = self._research_row(research_id)
        access = self._research_access(row, viewer)
        if not access["can_view"]:
            raise PermissionError("research is not visible to this user")
        return self._research_value(row, viewer=viewer, access=access)

    def _research_row(self, research_id: str):
        target = _text(research_id, "research_id", maximum=256)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM research_catalog_researches WHERE research_id=?",
                (target,),
            ).fetchone()
        if row is None:
            raise KeyError("research not found")
        return row

    def _report_row(self, report_id: str):
        target = _text(report_id, "report_id", maximum=256)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM research_catalog_reports WHERE report_id=?",
                (target,),
            ).fetchone()
        if row is None:
            raise KeyError("report not found")
        return row

    def _research_access(self, row, viewer: str | None) -> dict[str, Any]:
        viewer_ref = str(viewer or "").strip()
        membership = None
        if viewer_ref:
            with connect_sqlite(self.db_path, readonly=True) as conn:
                membership = conn.execute(
                    """SELECT role, status FROM research_catalog_memberships
                       WHERE research_id=? AND principal_ref=?
                         AND status='active'""",
                    (str(row["research_id"]), viewer_ref),
                ).fetchone()
        return self._research_access_values(
            research_id=str(row["research_id"]),
            owner=str(row["owner_ref"]),
            status=str(row["status"]),
            visibility=str(row["visibility"]),
            authorized_users_json=row["authorized_users_json"],
            viewer=viewer_ref,
            membership=membership,
        )

    @staticmethod
    def _research_access_values(
        *,
        research_id: str,
        owner: str,
        status: str,
        visibility: str,
        authorized_users_json: Any,
        viewer: str,
        membership=None,
    ) -> dict[str, Any]:
        if viewer and viewer == owner:
            return _access(True, True, True, True, "owner", research_id)
        if status == "archived":
            return _access(False, False, False, False, "none", research_id)
        if visibility == "public":
            return _access(True, True, True, False, "research", research_id)
        if viewer and viewer in _loads_list(authorized_users_json):
            return _access(True, True, True, False, "research", research_id)
        if membership is not None and str(membership["status"]) == "active":
            return _access(
                True, True, True,
                str(membership["role"]) in {"owner", "editor"},
                "research", research_id,
            )
        return _access(False, False, False, False, "none", research_id)

    def _report_access(
        self, row, viewer: str | None, *, research_access=None,
    ) -> dict[str, Any]:
        viewer_ref = str(viewer or "").strip()
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
        if viewer_ref and viewer_ref in _loads_list(row["authorized_users_json"]):
            return _access(True, True, False, False, "report", str(row["report_id"]))
        return _access(False, False, False, False, "none", str(row["report_id"]))

    def _research_value(
        self, row, *, viewer: str | None, access: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_access = access or self._research_access(row, viewer)
        return {
            "research_id": str(row["research_id"]),
            "owner_ref": str(row["owner_ref"]),
            "title": str(row["title"]),
            "description": str(row["description"]),
            "status": str(row["status"]),
            "visibility": str(row["visibility"]),
            "authorized_users": (
                _loads_list(row["authorized_users_json"])
                if resolved_access["can_manage"]
                else []
            ),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "is_owned": str(row["owner_ref"]) == str(viewer or ""),
            "access": resolved_access,
        }

    @staticmethod
    def _membership_value(row) -> dict[str, Any]:
        return {
            "research_id": str(row["research_id"]),
            "principal_ref": str(row["principal_ref"]),
            "profile_ref": str(row["profile_ref"]),
            "role": str(row["role"]),
            "status": str(row["status"]),
            "invited_by": str(row["invited_by"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    @staticmethod
    def _workspace_value(row) -> dict[str, Any]:
        return {
            "workspace_id": str(row["workspace_id"]),
            "research_id": str(row["research_id"]),
            "principal_ref": str(row["principal_ref"]),
            "profile_ref": str(row["profile_ref"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _report_value(
        self,
        row,
        *,
        viewer: str | None,
        access: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = {
            "report_id": str(row["report_id"]),
            "research_id": str(row["research_id"]),
            "owner_ref": str(row["owner_ref"]),
            "title": str(row["title"]),
            "profile_ref": str(row["profile_ref"]),
            "workspace_id": str(row["workspace_id"]),
            "build_source": str(row["build_source"]),
            "build_source_ref": str(row["build_source_ref"]),
            "visibility": str(row["visibility"]),
            "status": str(row["status"]),
            "source_ref": str(row["source_ref"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }
        value["access"] = access or self._report_access(row, viewer)
        return value

    @staticmethod
    def _evidence_link_value(row) -> dict[str, Any]:
        return {
            "link_ref": str(row["link_ref"]),
            "research_id": str(row["research_id"]),
            "evidence_ref": str(row["evidence_ref"]),
            "evidence_owner_ref": str(row["evidence_owner_ref"]),
            "report_id": str(row["report_id"]),
            "graph_ref": str(row["graph_ref"]),
            "branch_ref": str(row["branch_ref"]),
            "job_id": str(row["job_id"]),
            "profile_ref": str(row["profile_ref"]),
            "purpose": str(row["purpose"]),
            "status": str(row["status"]),
            "created_at": float(row["created_at"]),
            "revoked_at": float(row["revoked_at"]),
        }

    @staticmethod
    def _upsert_membership(
        conn,
        *,
        research_id: str,
        principal_ref: str,
        profile_ref: str,
        role: str,
        status: str,
        invited_by: str,
        now: float,
    ) -> None:
        conn.execute(
            """INSERT INTO research_catalog_memberships
               (research_id, principal_ref, profile_ref, role, status,
                invited_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(research_id, profile_ref) DO UPDATE SET
                 principal_ref=excluded.principal_ref, role=excluded.role,
                 status=excluded.status, invited_by=excluded.invited_by,
                 updated_at=excluded.updated_at""",
            (
                research_id, principal_ref, profile_ref, role, status,
                invited_by, now, now,
            ),
        )


def _access(
    can_view: bool,
    can_preview: bool,
    can_download: bool,
    can_manage: bool,
    access_basis: str,
    object_ref: str,
) -> dict[str, Any]:
    return {
        "can_view": bool(can_view),
        "can_preview": bool(can_preview),
        "can_download": bool(can_download),
        "can_manage": bool(can_manage),
        "access_basis": str(access_basis),
        "object_ref": str(object_ref),
    }


def _stronger_access(*values: dict[str, Any] | None) -> dict[str, Any]:
    """Return the strongest already-resolved access decision.

    Research and Report permissions are evaluated independently.  A caller
    listing a report must receive the effective decision rather than whichever
    branch happened to run first; in particular, Research membership can grant
    download while a public Report alone grants preview only.
    """
    weights = {"none": 0, "report": 1, "research": 2, "owner": 3}
    candidates = [value for value in values if isinstance(value, dict)]
    if not candidates:
        return _access(False, False, False, False, "none", "")
    return max(
        candidates,
        key=lambda value: (
            weights.get(str(value.get("access_basis") or "none"), 0),
            int(bool(value.get("can_download"))),
            int(bool(value.get("can_manage"))),
        ),
    )


def _migration_work_package_key(
    item: dict[str, Any], owner: str,
) -> tuple[str, str, str] | None:
    """Identify legacy Branches that belong to the same Work Package."""
    package_id = str(
        item.get("work_package_id") or item.get("record_id") or ""
    ).strip()
    if not package_id:
        return None
    profile_ref = str(
        item.get("profile_ref") or item.get("profile_id") or ""
    ).strip()
    return owner, profile_ref, package_id


def _canonical_migration_report_ids(
    records: list[dict[str, Any]], owner: str,
) -> tuple[dict[tuple[str, str, str] | None, str], dict[str, str]]:
    """Collapse old per-Branch report IDs without splitting the Work Package."""
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        key = _migration_work_package_key(item, owner)
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


def _principal(value: Any) -> str:
    return _text(value, "principal_ref", maximum=256)


def _profile(value: Any) -> str:
    return _text(value, "profile_ref", maximum=256)


def _optional_profile(value: Any) -> str:
    raw = str(value or "").strip()
    return _profile(raw) if raw else ""


def _text(
    value: Any,
    field: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    result = str(value or "").strip()
    if not result and not allow_empty:
        raise ValueError(f"{field} is required")
    if len(result) > maximum or "\x00" in result:
        raise ValueError(f"{field} is invalid")
    return result


def _visibility(value: Any) -> str:
    return _choice(value, VISIBILITIES, "visibility")


def _status(value: Any) -> str:
    return _choice(value, RESEARCH_STATUSES, "research status")


def _choice(value: Any, choices: frozenset[str], field: str) -> str:
    result = str(value or "").strip()
    if result not in choices:
        raise ValueError(f"{field} is invalid")
    return result


def _authorized_users(value: Any, owner: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        raise TypeError("authorized_users must be an array")
    result = sorted({
        _principal(item)
        for item in value
        if str(item or "").strip() and str(item).strip() != owner
    })
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


__all__ = [
    "MEMBER_ROLES",
    "MEMBER_STATUSES",
    "RESEARCH_STATUSES",
    "VISIBILITIES",
    "ResearchCatalog",
]
