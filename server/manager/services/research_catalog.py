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
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from typing import Any

from tools.data.sqlite.db import connect_sqlite
from .research_branches import BRANCH_SCHEMA, ResearchBranchesMixin
from .research_share_links import ResearchShareLinksMixin

VISIBILITIES = frozenset({"private", "superiors", "authorized", "public"})
RESEARCH_STATUSES = frozenset({"active", "archived"})
MEMBER_ROLES = frozenset({"owner", "editor", "contributor", "viewer"})
MEMBER_STATUSES = frozenset({"active", "invited", "revoked"})
RESEARCH_SCOPES = frozenset({"all", "mine", "subordinates", "shared"})


class KeycloakResearchSharingUnavailable(RuntimeError):
    """A Keycloak-only sharing API was called before the guarded cutover."""


class KeycloakResearchCreationUnavailable(RuntimeError):
    """The current Manager cannot create a Keycloak-owned Research."""


class ResearchCatalog(ResearchBranchesMixin, ResearchShareLinksMixin):
    """Persist Research relationships in the Manager-owned SQLite database."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        account_provider: Callable[[], list[dict[str, Any]]] | None = None,
        research_authorizer=None,
        profile_authorizer=None,
        profile_grant_manager=None,
        profile_identity_resolver=None,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._account_provider = account_provider
        if research_authorizer is not None and profile_authorizer is None:
            raise ValueError("Keycloak Research access requires Profile membership authorization")
        # Callers may select this only after migration and parity validation.
        # Once selected, Research and Report decisions never fall back to ACL
        # columns, same-name ownership, or a local hierarchy projection.
        self._research_authorizer = research_authorizer
        # A runtime may supply this only after the Profile migration proof has
        # passed. Until then legacy Profile semantics remain the authority.
        self._profile_authorizer = profile_authorizer
        self._profile_grant_manager = profile_grant_manager
        self._profile_identity_resolver = profile_identity_resolver
        self._synchronizer = None
        self._schedule_refresh = None
        self.ensure_schema()
        if self._profile_authorizer is not None:
            self._ensure_profile_policy_journal()

    def _ensure_profile_policy_journal(self) -> None:
        """Record unfinished cross-system writes, never permission grants."""
        with connect_sqlite(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS research_profile_policy_pending (
                research_id TEXT NOT NULL, principal_ref TEXT NOT NULL, profile_ref TEXT NOT NULL,
                actor_ref TEXT NOT NULL, identity_id TEXT NOT NULL, subject TEXT NOT NULL,
                operation TEXT NOT NULL, desired_role TEXT NOT NULL, desired_status TEXT NOT NULL,
                expected_exists INTEGER NOT NULL, expected_role TEXT NOT NULL, expected_status TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(research_id, principal_ref, profile_ref)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS research_profile_policy_versions (
                research_id TEXT NOT NULL, principal_ref TEXT NOT NULL, profile_ref TEXT NOT NULL,
                revision INTEGER NOT NULL,
                PRIMARY KEY(research_id, principal_ref, profile_ref)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS research_report_policy_pending (
                report_id TEXT PRIMARY KEY, research_id TEXT NOT NULL, actor_ref TEXT NOT NULL,
                owner_subject TEXT NOT NULL, creation_intent TEXT NOT NULL, created_at REAL NOT NULL
            )""")
            # Link metadata and recovery intents are not permission decisions.
            # The link's actual user grant remains exclusively in Keycloak.
            from server.manager.services.research_share_links import ensure_link_journal
            ensure_link_journal(conn)

    def set_synchronizer(self, synchronizer, schedule_refresh=None) -> None:
        if synchronizer.local.path.resolve() != self.db_path:
            raise ValueError("research catalog and outbox must share one database")
        self._synchronizer = synchronizer
        # The old Research graph has no authenticated destination or live
        # Keycloak public-access decision. Never publish it automatically;
        # retain existing outbox records for reviewed migration instead.
        # Explicit report publication uses the Keycloak/CouchDB path.
        self._synchronizer.research_legacy_sharing = False
        self._schedule_refresh = schedule_refresh

    @contextmanager
    def _write(self, research_id: str, *, after_commit: Callable[[], None] | None = None):
        owner = ""
        from server.manager.storage.account_domain.research_sync import research_sync_lock
        lock = (research_sync_lock(self.db_path, research_id)
                if self._synchronizer is not None and getattr(self._synchronizer, 'research_legacy_sharing', False)
                else nullcontext())
        with lock, connect_sqlite(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            if self._synchronizer is not None:
                from server.manager.storage.account_domain.research_sync import publish_research
                operation = publish_research(self._synchronizer, conn, research_id)
                if operation:
                    row = conn.execute("SELECT owner_ref FROM research_catalog_researches WHERE research_id=?", (research_id,)).fetchone()
                    owner = str(row["owner_ref"]) if row else ""
            if after_commit is not None:
                # Mark the actual database commit before either connection
                # cleanup or the post-commit sync scheduler can fail.
                conn.commit()
                after_commit()
        if owner and self._schedule_refresh is not None:
            self._schedule_refresh(owner)

    def set_account_provider(
        self, provider: Callable[[], list[dict[str, Any]]] | None,
    ) -> None:
        """Attach the shared account hierarchy after runtime initialization."""
        self._account_provider = provider

    def ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect_sqlite(self.db_path) as conn:
            membership_columns = conn.execute(
                "PRAGMA table_info(research_catalog_memberships)"
            ).fetchall()
            if membership_columns and not any(
                col["name"] == "principal_ref" and col["pk"] for col in membership_columns
            ):
                raise RuntimeError(
                    "research catalog requires explicit principal-key migration; "
                    "run scripts/research/migrate_research_principal_keys.py dry-run first"
                )
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
                CREATE TABLE IF NOT EXISTS research_catalog_replication (
                    research_id TEXT PRIMARY KEY,
                    remote_revision INTEGER NOT NULL
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
                    PRIMARY KEY(research_id, principal_ref, profile_ref),
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
                    UNIQUE(research_id, principal_ref, profile_ref),
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
                CREATE TABLE IF NOT EXISTS research_catalog_share_links (
                    link_id TEXT PRIMARY KEY,
                    target_kind TEXT NOT NULL,
                    research_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    owner_ref TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    mode TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    redeemed_by TEXT NOT NULL,
                    redeemed_at REAL NOT NULL,
                    revoked_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_research_catalog_owner
                    ON research_catalog_researches(owner_ref, updated_at);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_members_principal
                    ON research_catalog_memberships(principal_ref, status);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_workspace_research
                    ON research_catalog_workspaces(research_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_report_research
                    ON research_catalog_reports(research_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_owned_report_sync
                    ON research_catalog_reports(research_id, owner_ref, status, report_id);
                CREATE INDEX IF NOT EXISTS idx_research_catalog_evidence
                    ON research_catalog_report_evidence_links(evidence_ref, status);
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_research_catalog_migration_identity
                    ON research_catalog_researches(owner_ref, migration_source)
                    WHERE migration_source <> '';
                CREATE INDEX IF NOT EXISTS idx_research_share_links_owner
                    ON research_catalog_share_links(owner_ref, created_at);
                """
            )
            evidence_columns = {
                str(row["name"])
                for row in conn.execute(
                    "PRAGMA table_info(research_catalog_report_evidence_links)"
                ).fetchall()
            }
            if "graph_ref" in evidence_columns:
                raise RuntimeError(
                    "Report-Evidence schema contains retired columns; run the "
                    "backed-up schema cutover before this Manager can start"
                )
            conn.executescript(BRANCH_SCHEMA)
    # ------------------------------------------------------------------
    # Research, membership, workspace, and report records

    @contextmanager
    def _report_registration_policy(self, *, research_id: str, report_id: str,
                                    actor: str, owner: str):
        """Make a new report's Keycloak resource recoverable before publishing it.

        The journal is an operation intent, never a permission. No report row
        is exposed while creation is incomplete. Replays must use the original
        verified subject and opaque intent; existing resources are not adopted
        or deleted based on a caller-supplied report ID.
        """
        if self._profile_authorizer is None:
            yield None
            return
        manager = self._profile_grant_manager
        if manager is None:
            raise RuntimeError("Keycloak report registration is not configured")
        from tools.cli.release.research_reporting.generation import report_workspace_lock
        with report_workspace_lock(self.db_path.parent / ".research-report-policy"):
            caller = manager.report_registration_identity(actor=actor, research_id=research_id)
            if actor != owner or caller.username != owner:
                raise PermissionError("report owner requires a verified Keycloak identity")
            with connect_sqlite(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT research_id FROM research_catalog_reports WHERE report_id=?", (report_id,),
                ).fetchone()
                pending = conn.execute(
                    "SELECT * FROM research_report_policy_pending WHERE report_id=?", (report_id,),
                ).fetchone()
                if current is not None:
                    if str(current["research_id"]) != research_id:
                        raise ValueError("report is already linked to another research")
                    if pending is not None:
                        raise RuntimeError("report registration needs recovery")
                    intent = None
                else:
                    if pending is not None:
                        if (str(pending["research_id"]) != research_id or str(pending["actor_ref"]) != actor
                                or str(pending["owner_subject"]) != caller.subject):
                            raise RuntimeError("another report registration is pending")
                        intent = str(pending["creation_intent"])
                    else:
                        intent = secrets.token_hex(32)
                        conn.execute("""INSERT INTO research_report_policy_pending
                            (report_id,research_id,actor_ref,owner_subject,creation_intent,created_at)
                            VALUES (?,?,?,?,?,?)""",
                            (report_id, research_id, actor, caller.subject, intent, time.time()))
            if intent is None:
                manager.require_report_resource(actor=actor, research_id=research_id, report_id=report_id)
            else:
                manager.ensure_new_report_resource(actor=actor, research_id=research_id,
                                                   report_id=report_id, creation_intent=intent)
            # A slow Keycloak registration must not preserve a stale share
            # decision if the caller was revoked while the request ran.
            manager.report_registration_identity(actor=actor, research_id=research_id)
            yield intent

    @contextmanager
    def _new_research_policy(self, *, owner: str, research_id: str, profiles: list[str]):
        if self._profile_authorizer is None:
            yield
            return
        manager = self._profile_grant_manager
        if manager is None:
            raise RuntimeError("Keycloak Research creation is not configured")
        from server.identity.keycloak_research import profile_resource_ref

        caller = manager.create_research_resource(actor=owner, research_id=research_id)
        created = [("research", research_id)]
        committed = False
        def mark_committed() -> None:
            nonlocal committed
            committed = True
        try:
            for profile in profiles:
                ref = profile_resource_ref(research_id, caller.identity_id, profile)
                # The Research ID was checked absent and is random. Record the
                # child before the remote call, which can fail after creation.
                created.append(("research_profile", ref))
                manager.set_profile_membership(
                    actor=owner, research_id=research_id, identity_id=caller.identity_id,
                    subject=caller.subject, profile_ref=profile, role="owner", status="active",
                )
            yield mark_committed
        except BaseException as exc:
            if committed:
                # A scheduler or connection-close failure after SQLite commit
                # must never revoke the resources of an already visible row.
                raise
            failed = False
            for kind, ref in reversed(created):
                try:
                    manager.delete_resource(resource_type=kind, resource_ref=ref, owner_subject=caller.subject)
                except Exception:
                    failed = True
            if failed:
                raise RuntimeError(f"Research creation failed; Keycloak resource cleanup needs review: {research_id}") from exc
            raise

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
        if self._research_authorizer is not None and (clean_visibility != "private" or authorized_users):
            raise ValueError("Research authorization must be configured in Keycloak after creation")
        research_id = "research:v1:" + secrets.token_urlsafe(18)
        now = time.time()
        initial_workspace = None
        profiles = ["self"]
        if profile_ref and _profile(profile_ref) != "self":
            profiles.append(_profile(profile_ref))
        with self._new_research_policy(owner=owner, research_id=research_id, profiles=profiles) as mark_committed, \
                self._write(research_id, after_commit=mark_committed) as conn:
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
            initial_workspaces = []
            for profile in profiles:
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
                initial_workspaces.append(initial_workspace)
            row = conn.execute(
                "SELECT * FROM research_catalog_researches WHERE research_id=?",
                (research_id,),
            ).fetchone()
        value = self._research_value(row, viewer=owner)
        if initial_workspaces:
            value["workspaces"] = [
                self._workspace_value(item) for item in initial_workspaces
            ]
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
                          (SELECT membership.role
                             FROM research_catalog_memberships AS membership
                            WHERE membership.research_id=research.research_id
                              AND membership.principal_ref=?
                              AND membership.status='active'
                            ORDER BY CASE membership.role
                              WHEN 'owner' THEN 0 WHEN 'editor' THEN 1
                              WHEN 'contributor' THEN 2 ELSE 3 END
                            LIMIT 1) AS viewer_member_role,
                          (SELECT membership.status
                             FROM research_catalog_memberships AS membership
                            WHERE membership.research_id=research.research_id
                              AND membership.principal_ref=?
                              AND membership.status='active'
                            LIMIT 1) AS viewer_member_status
                     FROM research_catalog_researches AS research
                    ORDER BY research.updated_at DESC, research.research_id""",
                (viewer_ref, viewer_ref),
            ).fetchall()
            profile_pairs = self._profile_pairs(conn, viewer_ref)
        profile_access = self._profile_membership_access(viewer_ref, profile_pairs)
        research_access = (self._research_authorizer.research_access_many(
            viewer=viewer_ref, researches=[(str(row["research_id"]), str(row["status"])) for row in rows])
            if self._research_authorizer is not None else {})
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
                profile_access=profile_access.get(str(row["research_id"]), {}),
                keycloak_access=research_access.get(str(row["research_id"])),
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

    def owned_sync_page(self, *, viewer: str, after_time: float, after_ref: str, limit: int) -> dict[str, Any]:
        """Return a bounded page of currently authorized owned Research refs.

        The cursor describes scanned rows, including denied rows, so a denied
        entry cannot stall the scan. Every new scan reevaluates authorization.
        """
        import math
        viewer_ref = str(viewer or '').strip()
        if (not viewer_ref or self._research_authorizer is None or type(limit) is not int
                or not 1 <= limit <= 100 or type(after_time) not in (int, float)
                or not math.isfinite(after_time) or after_time < 0
                or not isinstance(after_ref, str) or len(after_ref) > 256):
            raise ValueError('invalid owned Research synchronization page')
        self.ensure_schema()
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute('''SELECT research.*,
                (SELECT membership.role FROM research_catalog_memberships AS membership
                 WHERE membership.research_id=research.research_id AND membership.principal_ref=?
                   AND membership.status='active' ORDER BY CASE membership.role
                   WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 WHEN 'contributor' THEN 2 ELSE 3 END LIMIT 1) AS viewer_member_role,
                (SELECT membership.status FROM research_catalog_memberships AS membership
                 WHERE membership.research_id=research.research_id AND membership.principal_ref=?
                   AND membership.status='active' LIMIT 1) AS viewer_member_status
                FROM research_catalog_researches AS research
                WHERE research.owner_ref=? AND research.status='active'
                  AND (research.updated_at>? OR (research.updated_at=? AND research.research_id>?))
                ORDER BY research.updated_at, research.research_id LIMIT ?''',
                (viewer_ref, viewer_ref, viewer_ref, after_time, after_time, after_ref, limit + 1)).fetchall()
            scanned = rows[:limit]
            ids = {str(row['research_id']) for row in scanned}
            pairs = self._profile_pairs(conn, viewer_ref, research_ids=ids)
        profile_access = self._profile_membership_access(viewer_ref, pairs, bounded=True)
        decisions = self._research_authorizer.research_access_many(viewer=viewer_ref,
            researches=[(str(row['research_id']), str(row['status'])) for row in scanned]) if scanned else {}
        items = []
        for row in scanned:
            ref = str(row['research_id'])
            membership = ({'role': row['viewer_member_role'], 'status': row['viewer_member_status']}
                          if row['viewer_member_status'] else None)
            access = self._research_access_values(research_id=ref, owner=str(row['owner_ref']),
                status=str(row['status']), visibility=str(row['visibility']),
                authorized_users_json=row['authorized_users_json'], viewer=viewer_ref, membership=membership,
                profile_access=profile_access.get(ref, {}), keycloak_access=decisions.get(ref))
            if access['can_view']:
                items.append({'research_id': ref, 'updated_at': float(row['updated_at']),
                              'title': str(row['title']), 'description': str(row['description'])})
        cursor = ({'updated_at': float(scanned[-1]['updated_at']), 'research_id': str(scanned[-1]['research_id'])}
                  if len(rows) > limit else None)
        return {'researches': items, 'next_cursor': cursor}

    def owned_report_sync_page(self, *, viewer: str, research_id: str, after_ref: str, limit: int) -> dict[str, Any]:
        """Scan one owner's reports in bounded key order with fresh report authorization."""
        viewer_ref = str(viewer or '').strip()
        if (not viewer_ref or self._research_authorizer is None or type(limit) is not int
                or not 1 <= limit <= 100 or not isinstance(after_ref, str) or len(after_ref) > 256):
            raise ValueError('invalid owned Report synchronization page')
        research = self._viewable_research(research_id, viewer=viewer_ref)
        if str(research['owner_ref']) != viewer_ref:
            raise PermissionError('owned Research is required')
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute('''SELECT report_id, research_id FROM research_catalog_reports
                WHERE research_id=? AND owner_ref=? AND status='active' AND report_id>?
                ORDER BY report_id LIMIT ?''', (research_id, viewer_ref, after_ref, limit + 1)).fetchall()
        scanned = rows[:limit]
        decisions = self._research_authorizer.report_access_many(viewer=viewer_ref,
            reports=[(str(row['report_id']), None) for row in scanned]) if scanned else {}
        reports = [{'research_id': research_id, 'report_id': str(row['report_id'])} for row in scanned
                   if decisions.get(str(row['report_id']), {}).get('can_view') is True]
        return {'reports': reports, 'next_cursor': str(scanned[-1]['report_id']) if len(rows) > limit else None}

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
                   WHERE research_id=? AND status='active'
                   ORDER BY created_at, profile_ref""",
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
                   WHERE research_id=? AND status='active'
                   ORDER BY updated_at DESC, workspace_id""",
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
        values = [self._report_value(item, viewer=viewer) for item in rows]
        for value in values:
            value["branches"] = self._report_branches(value)
        return values

    def _publication_report(self, record: dict):
        """Find the active report for this exact registered publication."""
        report_id = str(record.get("report_id") or "")
        if not report_id:
            return None
        try:
            row = self._report_row(report_id)
        except KeyError:
            return None
        same_owner = str(row["owner_ref"]) == str(record.get("owner_ref") or "")
        registered = False
        if not same_owner:
            with connect_sqlite(self.db_path, readonly=True) as conn:
                registered = conn.execute(
                    """SELECT 1 FROM research_catalog_branches WHERE report_id=?
                       AND principal_ref=? AND publication_id=? AND status='active'""",
                    (report_id, str(record.get("owner_ref") or ""),
                     str(record.get("publication_id") or "")),
                ).fetchone() is not None
                if not registered:
                    # Fork reservations retain a precise source snapshot even if
                    # its writer advances before the download can be retried.
                    registered = conn.execute(
                        """SELECT 1 FROM research_catalog_branches fork
                           JOIN research_catalog_branches source
                             ON source.report_id=fork.report_id AND source.branch_id=fork.source_branch_id
                           WHERE fork.report_id=? AND source.principal_ref=?
                             AND fork.source_publication_id=?""",
                        (report_id, str(record.get("owner_ref") or ""),
                         str(record.get("publication_id") or "")),
                    ).fetchone() is not None
        return row if str(row["status"]) == "active" and (same_owner or registered) else None

    def can_read_publication(self, record: dict, viewer: str | None) -> bool:
        """Reuse current research download rights for its immutable projection.

        Publication metadata is authenticated at ingestion; match both its report
        and owner. Do not copy an authorization list that becomes stale on revoke.
        """
        row = self._publication_report(record)
        return bool(row is not None and self._report_access(row, viewer)["can_download"])

    def can_read_authoring_publication(self, record: dict, viewer: str | None) -> bool:
        """Editable source is restricted to active collaborators, not public readers."""
        if not viewer or not self.can_read_publication(record, viewer):
            return False
        row = self._report_row(str(record["report_id"]))
        if self._profile_authorizer is not None:
            with connect_sqlite(self.db_path, readonly=True) as conn:
                profiles = self._profile_pairs(conn, viewer, research_id=str(row["research_id"]))
            allowed = self._profile_authorizer.may_write_any_profile(
                research_id=str(row["research_id"]), viewer=viewer,
                profile_refs=[profile for _research, profile in profiles],
            )
            with connect_sqlite(self.db_path, readonly=True) as conn:
                unchanged = self._profile_pairs(conn, viewer, research_id=str(row["research_id"])) == profiles
            return bool(allowed and unchanged)
        if str(row["owner_ref"]) == viewer:
            return True
        with connect_sqlite(self.db_path, readonly=True) as conn:
            return conn.execute(
                """SELECT 1 FROM research_catalog_memberships WHERE research_id=?
                   AND principal_ref=? AND status='active' AND role IN ('owner','editor','contributor')""",
                (str(row["research_id"]), viewer),
            ).fetchone() is not None

    def authorize_server_report_read(
        self, *, owner: str, server_ref: str, viewer: str,
    ) -> dict[str, Any]:
        """Authorize raw authoring bytes against the registered source, not a name.

        Report-only visibility is insufficient for downloading private source
        files. Re-evaluate research membership on every request, including revoke.
        """
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute(
                """SELECT * FROM research_catalog_reports
                   WHERE owner_ref=? AND status='active'
                     AND build_source='server_agent'
                     AND source_ref IN (?, ?)""",
                (owner, server_ref, f"server:{server_ref}"),
            ).fetchall()
        for row in rows:
            access = self._report_access(row, viewer)
            if access["can_download"]:
                return access
        raise PermissionError("research report download is not authorized")

    def _report_branches(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        """Project migrated source records as lazy Report branch choices.

        The catalog stores only source references here. Report bytes remain in
        the client, server Agent, or publication store and are fetched only
        after the reader selects a branch.
        """
        research_id = str(report.get("research_id") or "").strip()
        report_id = str(report.get("report_id") or "").strip()
        selected_source = str(report.get("source_ref") or "").strip()
        if not research_id or not report_id:
            return []
        registered = self._registered_branch_choices(report_id)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            research = conn.execute(
                "SELECT migration_source FROM research_catalog_researches "
                "WHERE research_id=?",
                (research_id,),
            ).fetchone()
            rows = conn.execute(
                """SELECT source_kind, source_ref
                     FROM research_catalog_migrations
                    WHERE research_id=? AND status='completed'
                      AND source_kind!='schema'
                    ORDER BY completed_at DESC, source_ref""",
                (research_id,),
            ).fetchall()
        migration_source = str(research["migration_source"] if research else "")
        if migration_source and not migration_source.endswith(f":{report_id}"):
            return registered
        # Native reports are registered directly and have no migration row.
        if selected_source and not any(str(row["source_ref"]) == selected_source for row in rows):
            rows = [{"source_kind": report.get("build_source", ""), "source_ref": selected_source}, *rows]
        branches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            source_kind = str(row["source_kind"] or "").strip()
            source_ref = str(row["source_ref"] or "").strip()
            if not source_ref:
                continue
            publication_id = source_ref
            profile_ref = ""
            branch_ref = source_ref.rsplit(":", 1)[-1]
            if source_kind == "client":
                parts = source_ref.split(":", 2)
                if len(parts) == 3:
                    profile_ref, record_id, branch_ref = parts
                    publication_id = f"local:{record_id}:{branch_ref}"
                else:
                    publication_id = f"local:{source_ref}"
            elif source_kind == "server_agent":
                parts = source_ref.removeprefix("server:").split(":", 2)
                if len(parts) == 3:
                    profile_ref, _record_id, branch_ref = parts
                publication_id = source_ref if source_ref.startswith("server:") \
                    else f"server:{source_ref}"
            if publication_id in seen:
                continue
            seen.add(publication_id)
            branches.append({
                "branch_ref": branch_ref,
                "title": branch_ref,
                "profile_ref": profile_ref,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "publication_id": publication_id,
                "selected": source_ref == selected_source,
            })
        registered_keys = {
            (item["principal_ref"], item["profile_ref"], item["branch_ref"])
            for item in registered
        }
        owner = str(report.get("owner_ref") or "")
        return [*registered, *[
            {**item, "principal_ref": owner}
            for item in branches
            if (owner, item["profile_ref"], item["branch_ref"]) not in registered_keys
        ]]

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
                      WHERE principal_ref=? AND status='active'
                      ORDER BY CASE role WHEN 'owner' THEN 2 WHEN 'editor' THEN 1 ELSE 0 END""",
                    (viewer_ref,),
                ).fetchall()
            } if viewer_ref else {}
            profile_pairs = self._profile_pairs(conn, viewer_ref)

        profile_access = self._profile_membership_access(viewer_ref, profile_pairs)
        research_access_by_id = (self._research_authorizer.research_access_many(
            viewer=viewer_ref, researches=list(dict.fromkeys(
                (str(row["research_id"]), str(row["research_status"])) for row in rows)))
            if self._research_authorizer is not None else {})
        report_access_by_id = (self._research_authorizer.report_access_many(
            viewer=viewer_ref, reports=[(str(row["report_id"]), None) for row in rows])
            if self._research_authorizer is not None else {})

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
                profile_access=profile_access.get(str(row["research_id"]), {}),
                keycloak_access=research_access_by_id.get(str(row["research_id"])),
            )
            report_access = self._report_access(
                row, viewer_ref, research_access=research_access,
                keycloak_access=report_access_by_id.get(str(row["report_id"])),
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
        if self._research_authorizer is not None and (visibility is not None or authorized_users is not None):
            raise ValueError("Research authorization must be managed in Keycloak")
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
            if status == "archived" and str(row["migration_source"]):
                raise PermissionError(
                    "research can only be deleted on its source server"
                )
            values["status"] = _status(status)
        if not values:
            return self._research_value(row, viewer=actor, access=access)
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._write(research_id) as conn:
            conn.execute(
                f"UPDATE research_catalog_researches SET {assignments} WHERE research_id=?",
                (*values.values(), research_id),
            )
            updated = conn.execute(
                "SELECT * FROM research_catalog_researches WHERE research_id=?",
                (research_id,),
            ).fetchone()
        return self._research_value(updated, viewer=actor)

    def remove_research(self, research_id: str, *, actor: str) -> dict[str, Any]:
        """Archive a Research only in the catalog that created it."""
        row = self._research_row(research_id)
        if not self._research_access(row, actor)["can_manage"]:
            raise PermissionError("research management is not authorized")
        if str(row["migration_source"]):
            raise PermissionError("research can only be deleted on its source server")
        with self._write(research_id) as conn:
            conn.execute(
                """UPDATE research_catalog_researches
                   SET status='archived', updated_at=? WHERE research_id=?""",
                (time.time(), research_id),
            )
            updated = conn.execute(
                "SELECT * FROM research_catalog_researches WHERE research_id=?",
                (research_id,),
            ).fetchone()
        return self._research_value(updated, viewer=actor)

    @staticmethod
    def _profile_policy_pending(conn, research_id: str, principal: str, profile: str):
        return conn.execute("""SELECT * FROM research_profile_policy_pending
            WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
            (research_id, principal, profile)).fetchone()

    @staticmethod
    def _profile_policy_version(conn, research_id: str, principal: str, profile: str) -> int:
        row = conn.execute("""SELECT revision FROM research_profile_policy_versions
            WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
            (research_id, principal, profile)).fetchone()
        return int(row["revision"]) if row else 0

    @staticmethod
    def _advance_profile_policy_version(conn, research_id: str, principal: str, profile: str) -> None:
        conn.execute("""INSERT INTO research_profile_policy_versions
            (research_id, principal_ref, profile_ref, revision) VALUES (?, ?, ?, 1)
            ON CONFLICT(research_id, principal_ref, profile_ref) DO UPDATE SET revision=revision+1""",
            (research_id, principal, profile))

    def _change_profile_membership(self, *, research_id: str, actor: str, principal: str,
                                   profile: str, role: str, status: str, operation: str) -> dict[str, Any]:
        # Membership changes are rare. One process-safe lock per catalog
        # serializes the remote policy mutation without holding SQLite's
        # write lock during network I/O. The pending row makes readers fail
        # closed; the OS releases the lock if a Manager process exits.
        from tools.cli.release.research_reporting.generation import report_workspace_lock

        with report_workspace_lock(self.db_path.parent / ".research-profile-policy"):
            return self._change_profile_membership_locked(
                research_id=research_id, actor=actor, principal=principal,
                profile=profile, role=role, status=status, operation=operation,
            )

    def _change_profile_membership_locked(self, *, research_id: str, actor: str, principal: str,
                                          profile: str, role: str, status: str, operation: str) -> dict[str, Any]:
        """Fail closed while one KC policy and its metadata projection converge.

        The durable row serializes updates for this exact Profile. Its only
        authorization effect is denial during recovery; Keycloak is the sole
        source of grants. Retrying the same request is idempotent, and a
        different concurrent request cannot replace an unfinished operation.
        """
        if self._profile_grant_manager is None or not callable(self._profile_identity_resolver):
            raise RuntimeError("Keycloak Profile membership updates are not configured")
        self._profile_grant_manager.require_membership_manager(actor=actor, research_id=research_id)
        identity = self._profile_identity_resolver(principal)
        stable = str(identity.get("identity_id") or "").strip() if isinstance(identity, dict) else ""
        subject = str(identity.get("subject") or "").strip() if isinstance(identity, dict) else ""
        if not stable or not subject:
            raise LookupError("Research Profile Keycloak identity is unavailable")
        desired = (actor, stable, subject, operation, role, status)
        with connect_sqlite(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = self._profile_policy_pending(conn, research_id, principal, profile)
            if pending is None:
                previous = conn.execute("""SELECT role, status FROM research_catalog_memberships
                    WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                    (research_id, principal, profile)).fetchone()
                if operation == "remove" and (previous is None or previous["role"] != role):
                    raise RuntimeError("Profile membership changed; retry removal")
                conn.execute("""INSERT INTO research_profile_policy_pending
                    (research_id, principal_ref, profile_ref, actor_ref, identity_id, subject,
                     operation, desired_role, desired_status, expected_exists, expected_role, expected_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (research_id, principal, profile, *desired, int(previous is not None),
                     str(previous["role"]) if previous is not None else "",
                     str(previous["status"]) if previous is not None else "", time.time()))
                self._advance_profile_policy_version(conn, research_id, principal, profile)
            elif tuple(pending[key] for key in (
                    "actor_ref", "identity_id", "subject", "operation", "desired_role", "desired_status")) != desired:
                raise RuntimeError("another Profile authorization update is pending")
        # No database write lock is held across Keycloak network calls. Any
        # failure leaves the pending row in place and the Profile denied.
        self._profile_grant_manager.set_profile_membership(
            actor=actor, research_id=research_id, identity_id=stable, subject=subject,
            profile_ref=profile, role=role, status=status,
        )
        now = time.time()
        with self._write(research_id) as conn:
            pending = self._profile_policy_pending(conn, research_id, principal, profile)
            if pending is None or tuple(pending[key] for key in (
                    "actor_ref", "identity_id", "subject", "operation", "desired_role", "desired_status")) != desired:
                raise RuntimeError("Profile authorization recovery record changed")
            previous = conn.execute("""SELECT role, status FROM research_catalog_memberships
                WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                (research_id, principal, profile)).fetchone()
            actual = (int(previous is not None), str(previous["role"]) if previous else "",
                      str(previous["status"]) if previous else "")
            expected = (pending["expected_exists"], pending["expected_role"], pending["expected_status"])
            if actual != expected:
                raise RuntimeError("Profile membership changed during authorization update")
            self._upsert_membership(conn, research_id=research_id, principal_ref=principal,
                                    profile_ref=profile, role=role, status=status,
                                    invited_by=actor, now=now)
            if operation == "remove":
                conn.execute("""UPDATE research_catalog_workspaces SET status='archived', updated_at=?
                    WHERE research_id=? AND principal_ref=? AND profile_ref=? AND status='active'""",
                    (now, research_id, principal, profile))
            conn.execute("""DELETE FROM research_profile_policy_pending
                WHERE research_id=? AND principal_ref=? AND profile_ref=?""", (research_id, principal, profile))
            self._advance_profile_policy_version(conn, research_id, principal, profile)
            updated = conn.execute("""SELECT * FROM research_catalog_memberships
                WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                (research_id, principal, profile)).fetchone()
        return self._membership_value(updated)

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
        if self._profile_authorizer is not None:
            return self._change_profile_membership(
                research_id=research_id, actor=_principal(actor), principal=principal,
                profile=profile, role=clean_role, status=clean_status, operation="set",
            )
        now = time.time()
        with self._write(research_id) as conn:
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
                   WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                (research_id, principal, profile),
            ).fetchone()
        return self._membership_value(value)

    def remove_membership(
        self, research_id: str, *, profile_ref: str, actor: str,
        principal_ref: str | None = None,
    ) -> dict[str, Any]:
        row = self._research_row(research_id)
        if not self._research_access(row, actor)["can_manage"]:
            raise PermissionError("research membership management is not authorized")
        profile = _profile(profile_ref)
        principal = _principal(principal_ref) if principal_ref else None
        if self._profile_authorizer is not None:
            with connect_sqlite(self.db_path, readonly=True) as conn:
                candidates = conn.execute(
                    "SELECT * FROM research_catalog_memberships WHERE research_id=? AND profile_ref=?",
                    (research_id, profile),
                ).fetchall()
            if principal is None:
                if len(candidates) > 1:
                    raise ValueError("principal_ref is required for an ambiguous Profile")
                principal = str(candidates[0]["principal_ref"]) if candidates else None
            value = next((item for item in candidates if item["principal_ref"] == principal), None)
            if value is None:
                raise KeyError("research member not found")
            if profile == "self" and principal == row["owner_ref"]:
                raise PermissionError("the Research owner's self Profile is a required member")
            return self._change_profile_membership(
                research_id=research_id, actor=_principal(actor), principal=principal,
                profile=profile, role=str(value["role"]), status="revoked", operation="remove",
            )
        now = time.time()
        with self._write(research_id) as conn:
            candidates = conn.execute(
                "SELECT * FROM research_catalog_memberships WHERE research_id=? AND profile_ref=?",
                (research_id, profile),
            ).fetchall()
            if principal is None:
                if len(candidates) > 1:
                    raise ValueError("principal_ref is required for an ambiguous Profile")
                principal = str(candidates[0]["principal_ref"]) if candidates else None
            value = next((item for item in candidates if item["principal_ref"] == principal), None)
            if value is None:
                raise KeyError("research member not found")
            if profile == "self" and principal == row["owner_ref"]:
                raise PermissionError("the Research owner's self Profile is a required member")
            conn.execute(
                """UPDATE research_catalog_memberships SET status='revoked', updated_at=?
                   WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                (now, research_id, principal, profile),
            )
            conn.execute(
                """UPDATE research_catalog_workspaces SET status='archived', updated_at=?
                   WHERE research_id=? AND principal_ref=? AND profile_ref=? AND status='active'""",
                (now, research_id, principal, profile),
            )
            updated = conn.execute(
                """SELECT * FROM research_catalog_memberships
                   WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                (research_id, principal, profile),
            ).fetchone()
        return self._membership_value(updated)

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
        principal = _principal(principal_ref)
        profile = _profile(profile_ref)
        profile_version = None
        if self._profile_authorizer is not None:
            with connect_sqlite(self.db_path, readonly=True) as conn:
                if self._profile_policy_pending(conn, research_id, principal, profile):
                    raise PermissionError("Profile authorization update is pending")
                profile_version = self._profile_policy_version(conn, research_id, principal, profile)
        access = self._research_access(row, actor)
        if not access["can_manage"]:
            if self._profile_authorizer is not None:
                can_write = principal == actor and self._profile_authorizer.may_write_profile(
                    research_id=research_id, viewer=actor, profile_ref=profile,
                )
            else:
                with connect_sqlite(self.db_path, readonly=True) as conn:
                    member = conn.execute(
                        """SELECT role FROM research_catalog_memberships
                           WHERE research_id=? AND principal_ref=? AND profile_ref=? AND status='active'""",
                        (research_id, principal, profile),
                    ).fetchone()
                can_write = member is not None and member["role"] in {"owner", "editor", "contributor"}
            if not access["can_view"] or principal != actor or not can_write:
                raise PermissionError("research workspace management is not authorized")
        clean_title = _text(
            title or profile, "title", maximum=256, allow_empty=False,
        )
        workspace_id = "research-workspace:v1:" + secrets.token_urlsafe(18)
        now = time.time()
        with self._write(research_id) as conn:
            if self._profile_authorizer is not None and self._profile_policy_pending(conn, research_id, principal, profile):
                raise PermissionError("Profile authorization update is pending")
            if (self._profile_authorizer is not None
                    and self._profile_policy_version(conn, research_id, principal, profile) != profile_version):
                raise PermissionError("Profile authorization changed; retry")
            membership = conn.execute(
                """SELECT status FROM research_catalog_memberships
                   WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                (research_id, principal, profile),
            ).fetchone()
            if (membership is None or (self._profile_authorizer is None
                                      and str(membership["status"]) != "active")):
                raise ValueError("profile must be an active research member")
            existing = conn.execute(
                """SELECT * FROM research_catalog_workspaces
                   WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                (research_id, principal, profile),
            ).fetchone()
            if existing is not None:
                if str(existing["status"]) != "active":
                    conn.execute(
                        """UPDATE research_catalog_workspaces
                           SET status='active', principal_ref=?, title=?, updated_at=?
                           WHERE workspace_id=?""",
                        (principal, clean_title, now, str(existing["workspace_id"])),
                    )
                    existing = conn.execute(
                        "SELECT * FROM research_catalog_workspaces WHERE workspace_id=?",
                        (str(existing["workspace_id"]),),
                    ).fetchone()
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
        if self._profile_authorizer is not None and (clean_visibility != "private" or users):
            raise RuntimeError("report sharing requires the Keycloak sharing migration")
        clean_profile = _optional_profile(profile_ref)
        clean_workspace = str(workspace_id or "").strip()
        checked_profile = clean_profile
        checked_version = None
        if self._profile_authorizer is not None:
            with connect_sqlite(self.db_path, readonly=True) as conn:
                if clean_workspace:
                    workspace_hint = conn.execute(
                        "SELECT profile_ref FROM research_catalog_workspaces WHERE workspace_id=?",
                        (clean_workspace,),
                    ).fetchone()
                    if workspace_hint is not None and not checked_profile:
                        checked_profile = _optional_profile(workspace_hint["profile_ref"])
                if checked_profile:
                    owner = str(row["owner_ref"])
                    if self._profile_policy_pending(conn, research_id, owner, checked_profile):
                        raise PermissionError("Profile authorization update is pending")
                    checked_version = self._profile_policy_version(conn, research_id, owner, checked_profile)
            if checked_profile and (str(actor) != str(row["owner_ref"])
                    or not self._profile_authorizer.may_write_profile(
                        research_id=research_id, viewer=actor, profile_ref=checked_profile)):
                raise PermissionError("report Profile write is not authorized")
        now = time.time()
        with self._report_registration_policy(research_id=research_id, report_id=report,
                                              actor=actor, owner=str(row["owner_ref"])) as report_intent, \
                self._write(research_id) as conn:
            if clean_workspace:
                workspace = conn.execute(
                    """SELECT workspace_id, research_id, principal_ref, profile_ref, status
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
                if str(workspace["principal_ref"]) != str(row["owner_ref"]):
                    raise ValueError("report workspace principal does not match report owner")
                workspace_profile = _optional_profile(workspace["profile_ref"])
                if clean_profile and clean_profile != workspace_profile:
                    raise ValueError("report profile does not match research workspace")
                clean_profile = workspace_profile
            if clean_profile:
                if self._profile_authorizer is not None:
                    owner = str(row["owner_ref"])
                    if (clean_profile != checked_profile
                            or self._profile_policy_pending(conn, research_id, owner, clean_profile)
                            or self._profile_policy_version(conn, research_id, owner, clean_profile) != checked_version):
                        raise PermissionError("Profile authorization changed; retry")
                else:
                    membership = conn.execute(
                        """SELECT status FROM research_catalog_memberships
                            WHERE research_id=? AND principal_ref=? AND profile_ref=?""",
                        (research_id, str(row["owner_ref"]), clean_profile),
                    ).fetchone()
                    if membership is None or str(membership["status"]) != "active":
                        raise ValueError("report profile must be an active research member")
            existing = conn.execute(
                "SELECT * FROM research_catalog_reports WHERE report_id=?",
                (report,),
            ).fetchone()
            if report_intent is not None and existing is not None:
                raise RuntimeError("report appeared during Keycloak registration")
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
            if report_intent is not None:
                deleted = conn.execute("""DELETE FROM research_report_policy_pending
                    WHERE report_id=? AND research_id=? AND actor_ref=? AND creation_intent=?""",
                    (report, research_id, actor, report_intent))
                if deleted.rowcount != 1:
                    raise RuntimeError("report registration intent changed; retry")
            value = conn.execute(
                "SELECT * FROM research_catalog_reports WHERE report_id=?",
                (report,),
            ).fetchone()
        return self._report_value(value, viewer=actor)

    def create_report_space(
        self,
        research_id: str,
        *,
        actor: str,
        title: str,
        profile_ref: str,
        visibility: str = "private",
        authorized_users: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Create one empty Report space owned by a Research workspace.

        A report space is the durable parent for later branch-authored report
        content.  It deliberately has no source reference until a Profile
        publishes the first branch generation.
        """
        profile = _profile(profile_ref)
        research = self._research_row(research_id)
        if not self._research_access(research, actor)["can_manage"]:
            raise PermissionError("research report management is not authorized")
        workspaces = self.list_workspaces(research_id, viewer=actor)
        workspace = next(
            (item for item in workspaces
             if item["profile_ref"] == profile
             and item["principal_ref"] == research["owner_ref"]),
            None,
        )
        if workspace is None:
            workspace = self.create_workspace(
                research_id,
                actor=actor,
                principal_ref=str(research["owner_ref"]),
                profile_ref=profile,
                title=f"{str(research['title'])} / {profile}",
            )
        return self.register_report(
            research_id,
            actor=actor,
            report_id="report:v1:" + secrets.token_urlsafe(18),
            title=title,
            profile_ref=profile,
            workspace_id=str(workspace["workspace_id"]),
            build_source="workspace",
            visibility=visibility,
            authorized_users=authorized_users,
        )

    def update_report(
        self,
        research_id: str,
        report_id: str,
        *,
        actor: str,
        visibility: str | None = None,
        authorized_users: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        research = self._research_row(research_id)
        if not self._research_access(research, actor)["can_manage"]:
            raise PermissionError("research report management is not authorized")
        row = self._report_row(report_id)
        if str(row["research_id"]) != research_id:
            raise ValueError("report does not belong to research")
        if self._profile_authorizer is not None and (visibility is not None or authorized_users is not None):
            raise RuntimeError("report sharing requires the Keycloak sharing migration")
        values: dict[str, Any] = {}
        if visibility is not None:
            values["visibility"] = _visibility(visibility)
        if authorized_users is not None:
            values["authorized_users_json"] = _json(
                _authorized_users(authorized_users, str(row["owner_ref"])),
            )
        if not values:
            return self._report_value(row, viewer=actor)
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._write(research_id) as conn:
            conn.execute(
                f"UPDATE research_catalog_reports SET {assignments} WHERE report_id=?",
                (*values.values(), report_id),
            )
            updated = conn.execute(
                "SELECT * FROM research_catalog_reports WHERE report_id=?",
                (report_id,),
            ).fetchone()
        return self._report_value(updated, viewer=actor)

    def remove_report(
        self, research_id: str, report_id: str, *, actor: str,
    ) -> dict[str, Any]:
        research = self._research_row(research_id)
        if not self._research_access(research, actor)["can_manage"]:
            raise PermissionError("research report management is not authorized")
        row = self._report_row(report_id)
        if str(row["research_id"]) != research_id:
            raise ValueError("report does not belong to research")
        if not self._report_is_local(row):
            raise PermissionError(
                "research report can only be deleted on its source server"
            )
        with self._write(research_id) as conn:
            conn.execute(
                """UPDATE research_catalog_reports
                   SET status='archived', updated_at=? WHERE report_id=?""",
                (time.time(), report_id),
            )
            updated = conn.execute(
                "SELECT * FROM research_catalog_reports WHERE report_id=?",
                (report_id,),
            ).fetchone()
        return self._report_value(updated, viewer=actor)

    def _keycloak_share_target(self, research_id: str, target_kind: str, report_id: str):
        if self._research_authorizer is None or self._profile_grant_manager is None:
            raise RuntimeError("Keycloak Research sharing is not enabled")
        research = self._research_row(research_id)
        if str(research["status"]) != "active":
            raise ValueError("archived Research cannot receive new grants")
        if target_kind == "research":
            if report_id:
                raise ValueError("research sharing cannot specify a report")
            return "research", research_id
        if target_kind != "report":
            raise ValueError("target_kind must be research or report")
        report = self._report_row(report_id)
        if str(report["research_id"]) != research_id or str(report["status"]) != "active":
            raise ValueError("active report does not belong to this Research")
        return "research_report", str(report["report_id"])

    def keycloak_sharing_capabilities(self) -> dict[str, Any]:
        """Describe the live authority; this is not an authorization grant."""
        manager = self._profile_grant_manager
        available = self._research_authorizer is not None and all(callable(getattr(manager, name, None))
            for name in ("require_resource_share", "identity_provider", "user_by_identity",
                         "require_link_issuer_share", "_reconcile_user_grant"))
        return {"schema": "tr-research-keycloak-sharing-v1",
                "authority": "keycloak" if self._research_authorizer is not None else "unavailable",
                "share_links": available,
                "explicit_grants": self._research_authorizer is not None
                    and callable(self._profile_identity_resolver)
                    and all(callable(getattr(manager, name, None)) for name in
                            ("require_resource_share", "list_user_grants", "set_user_grant")),
                "create_research": self._research_authorizer is not None and all(
                    callable(getattr(manager, name, None)) for name in
                    ("create_research_resource", "set_profile_membership", "delete_resource"))}

    def require_keycloak_research_creation(self) -> None:
        if not self.keycloak_sharing_capabilities()["create_research"]:
            raise KeycloakResearchCreationUnavailable("Keycloak Research creation is not enabled")

    def require_keycloak_sharing(self) -> None:
        if not self.keycloak_sharing_capabilities()["share_links"]:
            raise KeycloakResearchSharingUnavailable("Keycloak Research sharing is not enabled")

    def require_keycloak_grants(self) -> None:
        if not self.keycloak_sharing_capabilities()["explicit_grants"]:
            raise KeycloakResearchSharingUnavailable("Keycloak Research grants are not enabled")

    def keycloak_target_sharing_capabilities(self, research_id: str, *, actor: str,
                                            target_kind: str = "research", report_id: str = "") -> dict[str, Any]:
        capabilities = self.keycloak_sharing_capabilities()
        if not (capabilities["explicit_grants"] or capabilities["share_links"]):
            raise KeycloakResearchSharingUnavailable("Keycloak Research sharing is not enabled")
        research = self._research_row(research_id)
        access = self._research_access(research, actor)
        if not access.get("can_view"):
            raise PermissionError("research is not visible to current account")
        kind, target = self._keycloak_share_target(research_id, target_kind, report_id)
        try:
            self._profile_grant_manager.require_resource_share(actor=actor, resource_type=kind, resource_ref=target)
            can_share = True
        except PermissionError:
            can_share = False
        return {"schema": "tr-research-keycloak-target-sharing-v1", "authority": "keycloak",
                "target_kind": target_kind, "research_id": research_id, "report_id": report_id,
                "can_manage_grants": can_share and capabilities["explicit_grants"],
                "can_manage_links": can_share and capabilities["share_links"] and bool(access.get("can_manage"))}

    def list_explicit_grants(self, research_id: str, *, actor: str,
                             target_kind: str = "research", report_id: str = "") -> list[dict[str, Any]]:
        kind, target = self._keycloak_share_target(research_id, target_kind, report_id)
        return self._profile_grant_manager.list_user_grants(actor=actor, resource_type=kind, resource_ref=target)

    def set_explicit_grant(self, research_id: str, *, actor: str, principal_ref: str,
                           scopes, target_kind: str = "research", report_id: str = "") -> dict[str, Any]:
        """Create/revoke one Keycloak grant; local ACL fields are never written."""
        kind, target = self._keycloak_share_target(research_id, target_kind, report_id)
        if not callable(self._profile_identity_resolver):
            raise RuntimeError("Keycloak Research identity resolution is not configured")
        if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
            raise ValueError("grant scopes must be an array")
        normalized = sorted(set(scopes))
        if any(scope not in {"read", "use", "write"} for scope in normalized):
            raise ValueError("invalid Research grant scope")
        if any(scope in normalized for scope in ("use", "write")) and "read" not in normalized:
            raise ValueError("use and write grants also require read")
        manager = self._profile_grant_manager
        # Do not allow unauthorized callers to enumerate identities.
        manager.require_resource_share(actor=actor, resource_type=kind, resource_ref=target)
        principal = _principal(principal_ref)
        identity = self._profile_identity_resolver(principal)
        stable = str(identity.get("identity_id") or "").strip() if isinstance(identity, dict) else ""
        subject = str(identity.get("subject") or "").strip() if isinstance(identity, dict) else ""
        if not stable or not subject:
            raise LookupError("Research grant identity is unavailable")
        changed = manager.set_user_grant(actor=actor, resource_type=kind, resource_ref=target,
            source="explicit", identity_id=stable, subject=subject, scopes=normalized)
        return {"target_kind": target_kind, "research_id": research_id, "report_id": report_id,
                "identity_id": stable, "principal_ref": principal, "scopes": normalized, "changed": bool(changed)}

    def create_share_link(
        self,
        *,
        target_kind: str,
        research_id: str,
        report_id: str = "",
        actor: str,
        mode: str = "permanent",
        expires_at: float = 0,
    ) -> dict[str, Any]:
        self.require_keycloak_sharing()
        return self._create_keycloak_share_link(target_kind=target_kind,
            research_id=research_id, report_id=report_id, actor=actor,
            mode=mode, expires_at=expires_at)

    def list_keycloak_share_links(self, research_id: str, *, actor: str,
                                  target_kind: str = "research", report_id: str = "") -> list[dict[str, Any]]:
        """List only the exact resource for which the caller has share scope."""
        self.require_keycloak_sharing()
        kind, target = self._keycloak_share_target(research_id, target_kind, report_id)
        research = self._research_row(research_id)
        if not self._research_access(research, actor)["can_manage"]:
            raise PermissionError("research sharing is not authorized")
        self._profile_grant_manager.require_resource_share(actor=actor, resource_type=kind, resource_ref=target)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute("""SELECT * FROM research_catalog_share_links
                WHERE research_id=? AND target_kind=? AND report_id=? ORDER BY created_at DESC""",
                (research_id, target_kind, report_id)).fetchall()
        return [self._share_link_value(row) for row in rows]

    def revoke_share_link(
        self, research_id: str, link_id: str, *, actor: str,
    ) -> dict[str, Any]:
        self.require_keycloak_sharing()
        research = self._research_row(research_id)
        if not self._research_access(research, actor)["can_manage"]:
            raise PermissionError("research sharing is not authorized")
        with self._write(research_id) as conn:
            row = conn.execute(
                """SELECT * FROM research_catalog_share_links
                   WHERE research_id=? AND link_id=?""",
                (research_id, link_id),
            ).fetchone()
            if row is None:
                raise KeyError("share link not found")
            if self._research_authorizer is not None:
                kind, target, _scopes = self._link_target(row)
                self._share_manager().require_resource_share(actor=actor, resource_type=kind, resource_ref=target)
            conn.execute(
                "UPDATE research_catalog_share_links SET revoked_at=? WHERE link_id=?",
                (time.time(), link_id),
            )
            updated = conn.execute(
                "SELECT * FROM research_catalog_share_links WHERE link_id=?",
                (link_id,),
            ).fetchone()
        return self._share_link_value(updated)

    def redeem_share_link(self, token: str, *, actor: str) -> dict[str, Any]:
        self.require_keycloak_sharing()
        return self._redeem_keycloak_share_link(token, actor=actor)

    @staticmethod
    def _share_link_value(row) -> dict[str, Any]:
        return {
            "link_id": str(row["link_id"]),
            "target_kind": str(row["target_kind"]),
            "research_id": str(row["research_id"]),
            "report_id": str(row["report_id"]),
            "mode": str(row["mode"]),
            "expires_at": float(row["expires_at"]),
            "redeemed_by": str(row["redeemed_by"]),
            "redeemed_at": float(row["redeemed_at"]),
            "revoked_at": float(row["revoked_at"]),
            "created_at": float(row["created_at"]),
        }

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
            "branch_ref": str(branch_ref or "").strip(),
            "job_id": str(job_id or "").strip(),
            "profile_ref": str(profile_ref or "").strip(),
            "purpose": str(purpose or "").strip(),
        }
        link_ref = "evidence-link:v1:" + hashlib.sha256(
            _json(values).encode("utf-8")
        ).hexdigest()
        now = time.time()
        with self._write(research_id) as conn:
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
                    report_id, branch_ref, job_id, profile_ref,
                    purpose, status, created_at, revoked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 0)
                   ON CONFLICT(link_ref) DO UPDATE SET status='active', revoked_at=0""",
                (
                    link_ref, values["evidence_ref"], values["evidence_owner_ref"],
                    values["report_id"],
                    values["branch_ref"], values["job_id"],
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
        if (self._research_authorizer is None
                and any(str(item["evidence_owner_ref"]) == viewer_ref for item in links)):
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

    def research_statuses(self, research_ids) -> dict[str, str]:
        """Fetch bounded metadata candidates; this never grants access."""
        refs = sorted({_text(ref, "research_id", maximum=512) for ref in research_ids})
        if len(refs) > 1000:
            raise ValueError("too many Research references")
        result = {}
        with connect_sqlite(self.db_path, readonly=True) as conn:
            for offset in range(0, len(refs), 256):
                batch = refs[offset:offset + 256]
                placeholders = ",".join("?" for _ in batch)
                for row in conn.execute(f"SELECT research_id,status FROM research_catalog_researches "
                                        f"WHERE research_id IN ({placeholders})", batch):
                    result[str(row["research_id"])] = str(row["status"])
        return result

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

    def _profile_pairs(self, conn, viewer: str, *, research_id: str = "", research_ids: set[str] | None = None) -> dict[tuple[str, str], int]:
        if self._profile_authorizer is None or not viewer:
            return {}
        if research_ids is not None and (not research_ids or len(research_ids) > 100 or research_id):
            if not research_ids:
                return {}
            raise ValueError('invalid bounded Research membership scope')
        sql = """SELECT m.research_id, m.profile_ref, COALESCE(v.revision, 0) AS policy_version
                 FROM research_catalog_memberships m
                 LEFT JOIN research_profile_policy_versions v
                   ON v.research_id=m.research_id AND v.principal_ref=m.principal_ref AND v.profile_ref=m.profile_ref
                 WHERE m.principal_ref=? AND NOT EXISTS (
                   SELECT 1 FROM research_profile_policy_pending p
                    WHERE p.research_id=m.research_id AND p.principal_ref=m.principal_ref
                      AND p.profile_ref=m.profile_ref)"""
        params = [viewer]
        if research_id:
            sql += " AND m.research_id=?"
            params.append(research_id)
        if research_ids is not None:
            sql += f" AND m.research_id IN ({','.join('?' for _ in research_ids)})"
            params.extend(sorted(research_ids))
        # These are association candidates, not permission decisions. Keycloak
        # may allow or deny independently of their old role/status columns.
        return {(str(item["research_id"]), str(item["profile_ref"])): int(item["policy_version"])
                for item in conn.execute(sql, params)}

    def _profile_membership_access(self, viewer: str, pairs: dict[tuple[str, str], int], *, bounded: bool = False) -> dict[str, dict[str, bool]]:
        if self._profile_authorizer is None or not viewer or not pairs:
            return {}
        values = self._profile_authorizer.profile_membership_access_many(viewer=viewer, profiles=pairs)
        with connect_sqlite(self.db_path, readonly=True) as conn:
            current_pairs = self._profile_pairs(conn, viewer, research_ids={pair[0] for pair in pairs} if bounded else None)
        result: dict[str, dict[str, bool]] = {}
        for (research_id, profile_ref), access in values.items():
            pair = (research_id, profile_ref)
            if pair not in pairs or current_pairs.get(pair) != pairs[pair]:
                continue
            current = result.setdefault(research_id, {"can_view": False, "can_download": False})
            current["can_view"] = current["can_view"] or bool(access.get("can_view"))
            current["can_download"] = current["can_download"] or bool(access.get("can_download"))
        return result

    def _research_access(self, row, viewer: str | None) -> dict[str, Any]:
        viewer_ref = str(viewer or "").strip()
        membership = None
        if viewer_ref:
            with connect_sqlite(self.db_path, readonly=True) as conn:
                membership = conn.execute(
                    """SELECT role, status FROM research_catalog_memberships
                       WHERE research_id=? AND principal_ref=?
                         AND status='active'
                       ORDER BY CASE role WHEN 'owner' THEN 2 WHEN 'editor' THEN 1 ELSE 0 END DESC""",
                    (str(row["research_id"]), viewer_ref),
                ).fetchone()
                pairs = self._profile_pairs(conn, viewer_ref, research_id=str(row["research_id"]))
        else:
            pairs = {}
        profile_access = self._profile_membership_access(viewer_ref, pairs)
        return self._research_access_values(
            research_id=str(row["research_id"]),
            owner=str(row["owner_ref"]),
            status=str(row["status"]),
            visibility=str(row["visibility"]),
            authorized_users_json=row["authorized_users_json"],
            viewer=viewer_ref,
            membership=membership,
            profile_access=profile_access.get(str(row["research_id"]), {}),
        )

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
            direct = keycloak_access if keycloak_access is not None else self._research_authorizer.research_access(
                research_id=research_id, status=status, viewer=viewer)
            # A Profile membership itself may grant read/use to its Research.
            # Archived Research remains visible only to its Keycloak manager.
            if status == "active" and (profile_access or {}).get("can_view"):
                return _access(True, True,
                    bool(direct.get("can_download") or profile_access.get("can_download")),
                    bool(direct.get("can_manage")),
                    str(direct.get("access_basis") or "research") if direct.get("can_view") else "research",
                    research_id)
            return direct
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
            if research_access is None:
                try:
                    research = self._research_row(str(row["research_id"]))
                except KeyError:
                    research = None
                if research is not None:
                    research_access = self._research_access(research, viewer_ref)
            if keycloak_access is None:
                return self._research_authorizer.report_access(
                    report_id=str(row["report_id"]), viewer=viewer_ref, inherited=research_access)
            direct, parent = keycloak_access, research_access or {}
            return _access(bool(direct.get("can_view") or parent.get("can_view")),
                bool(direct.get("can_preview") or parent.get("can_preview")),
                bool(direct.get("can_download") or parent.get("can_download")),
                bool(direct.get("can_manage") or parent.get("can_manage")),
                str(parent.get("access_basis")) if parent.get("can_view") else str(direct.get("access_basis") or "none"),
                str(row["report_id"]))
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
                if resolved_access["can_manage"] and self._research_authorizer is None
                else []
            ),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "is_owned": str(row["owner_ref"]) == str(viewer or ""),
            "access": resolved_access,
            "can_delete": (
                resolved_access["can_manage"]
                and not str(row["migration_source"])
            ),
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
            "authorized_users": [],
            "status": str(row["status"]),
            "source_ref": str(row["source_ref"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "can_delete": self._report_is_local(row),
        }
        value["access"] = access or self._report_access(row, viewer)
        if value["access"]["can_manage"] and self._research_authorizer is None:
            value["authorized_users"] = _loads_list(row["authorized_users_json"])
        return value

    @staticmethod
    def _report_is_local(row) -> bool:
        """Only empty Report spaces created by this catalog are deletable here.

        Imported client/server/public projections retain their source store;
        this catalog must never turn a local UI action into remote deletion or
        hide the projection as a substitute for deletion at the source.
        """
        return (
            str(row["build_source"]) == "workspace"
            and not str(row["source_ref"])
        )

    @staticmethod
    def _evidence_link_value(row) -> dict[str, Any]:
        return {
            "link_ref": str(row["link_ref"]),
            "research_id": str(row["research_id"]),
            "evidence_ref": str(row["evidence_ref"]),
            "evidence_owner_ref": str(row["evidence_owner_ref"]),
            "report_id": str(row["report_id"]),
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
               ON CONFLICT(research_id, principal_ref, profile_ref) DO UPDATE SET
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
