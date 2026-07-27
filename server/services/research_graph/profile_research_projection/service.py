"""Profile-facing bounded research projection orchestration."""

from __future__ import annotations

from typing import Any

import orjson
import settings as Settings
from tools.data.sqlite.db import connect_sqlite

from server.services.research_graph.report_checkpoint import (
    report_checkpoint_projection,
)

from .branch import branch_projection
from .queries import (
    BRANCH_DETAIL_SQL,
    LIST_AFTER_SQL,
    LIST_FIRST_SQL,
    TIMELINE_AFTER_SQL,
    TIMELINE_FIRST_SQL,
    WORK_PACKAGE_BRANCH_DETAIL_SQL,
    WORK_PACKAGE_DETAIL_SQL,
    WORK_PACKAGE_TIMELINE_AFTER_SQL,
    WORK_PACKAGE_TIMELINE_FIRST_SQL,
    REPORT_CHECKPOINT_SQL,
)
from .refs import (
    _identifier,
    bounded_limit,
    bounded_projection,
    decode_cursor,
    encode_cursor,
    parse_research_ref,
    parse_workspace_ref,
    parse_work_package_ref,
    research_ref_for,
    work_package_ref_for,
    workspace_ref_for,
)
from server.services.research_graph.product_scope import (
    implementation_product_scope,
)
from .summary import _branch_summary, _work_package_summary
from .timeline import _bounded_transition_page
from .tree import _tree_projection

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50
DEFAULT_TIMELINE_LIMIT = 50
MAX_TIMELINE_LIMIT = 50


class ProfileResearchProjection:
    """Serve the bounded Profile research navigation read model.

    This is not the report store and should not be called a report projection:
    it owns Work Package/branch topology, lineage, lifecycle, timeline cursors,
    and stable report lookup refs. Report bodies and assets remain in the local
    Profile report document/journal and are loaded through their own verifier.
    """

    def list_research(
        self,
        *,
        owner: str,
        workspace_ref: str,
        lifecycle: str = "active",
        limit: int = DEFAULT_LIST_LIMIT,
        after: str = "",
    ) -> dict[str, Any]:
        workspace_id = parse_workspace_ref(workspace_ref)
        if lifecycle not in {"active", "archived", "deleted"}:
            raise ValueError("lifecycle must be active, archived, or deleted")
        page_limit = bounded_limit(
            limit,
            default=DEFAULT_LIST_LIMIT,
            maximum=MAX_LIST_LIMIT,
        )
        cursor = decode_cursor(after, kind="research") if after else None
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            if cursor is None:
                rows = conn.execute(
                    LIST_FIRST_SQL,
                    (owner, workspace_id, lifecycle, page_limit + 1),
                ).fetchall()
            else:
                rows = conn.execute(
                    LIST_AFTER_SQL,
                    (
                        owner,
                        workspace_id,
                        lifecycle,
                        cursor["at"],
                        cursor["at"],
                        cursor["id"],
                        page_limit + 1,
                    ),
                ).fetchall()
        has_more = len(rows) > page_limit
        visible = rows[:page_limit]
        items = [_work_package_summary(row) for row in visible]
        next_cursor = (
            encode_cursor(
                kind="research",
                at=float(visible[-1]["updated_at"]),
                identifier=str(visible[-1]["work_package_id"]),
            )
            if has_more and visible
            else None
        )
        return bounded_projection({
            "schema_version": 2,
            "workspace_ref": workspace_ref_for(workspace_id),
            "lifecycle": lifecycle,
            "items": items,
            "next_cursor": next_cursor,
        })
    def get_research(
        self,
        *,
        owner: str,
        research_ref: str,
    ) -> dict[str, Any]:
        if str(research_ref).startswith("graph-branch:"):
            return self.get_branch(
                owner=owner,
                branch_ref=research_ref,
            )
        work_package_id = parse_work_package_ref(research_ref)
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            rows = conn.execute(
                WORK_PACKAGE_DETAIL_SQL,
                (owner, work_package_id, MAX_LIST_LIMIT + 1),
            ).fetchall()
        if not rows:
            raise KeyError("profile research not found")
        visible = rows[:MAX_LIST_LIMIT]
        first = visible[0]
        work_package_ref = work_package_ref_for(work_package_id)
        return bounded_projection({
            "schema_version": 2,
            "research_ref": work_package_ref,
            "work_package_ref": work_package_ref,
            "workspace_ref": workspace_ref_for(str(first["workspace_id"])),
            "graph_ref": (
                f"{str(first['graph_id'])}@v{int(first['graph_version'])}"
            ),
            "product_group": str(first["product_group"]),
            "product_scope": implementation_product_scope(
                str(first["product_group"])
            ),
            "mode": str(first["mode"]),
            "lifecycle": str(first["lifecycle"]),
            "lifecycle_revision": int(first["lifecycle_revision"]),
            "created_at": min(
                float(row["instance_created_at"]) for row in rows
            ),
            "updated_at": max(float(row["updated_at"]) for row in rows),
            "branch_count": int(first["total_branch_count"]),
            "omitted_branch_count": max(
                int(first["total_branch_count"]) - len(visible), 0
            ),
            "branches": [_branch_summary(row) for row in visible],
            "tree": _tree_projection(
                next(
                    (
                        row["tree_json"] for row in visible
                        if row["tree_json"]
                    ),
                    None,
                ),
                visible,
            ),
            "report_lookup_ref": work_package_ref,
        })

    def get_branch(
        self,
        *,
        owner: str,
        branch_ref: str,
    ) -> dict[str, Any]:
        instance_id, branch_id = parse_research_ref(branch_ref)
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            row = conn.execute(
                BRANCH_DETAIL_SQL,
                (owner, instance_id, branch_id),
            ).fetchone()
        if row is None:
            raise KeyError("profile research branch not found")
        return branch_projection(row)

    def get_work_package_branch(
        self,
        *,
        owner: str,
        work_package_ref: str,
        branch_id: str,
    ) -> dict[str, Any]:
        work_package_id = parse_work_package_ref(work_package_ref)
        branch_id = _identifier(branch_id, field="branch_id")
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            row = conn.execute(
                WORK_PACKAGE_BRANCH_DETAIL_SQL,
                (owner, work_package_id, branch_id),
            ).fetchone()
        if row is None:
            raise KeyError("profile research branch not found")
        return branch_projection(row)

    def list_timeline(
        self,
        *,
        owner: str,
        research_ref: str,
        limit: int = DEFAULT_TIMELINE_LIMIT,
        after: str = "",
    ) -> dict[str, Any]:
        instance_id, branch_id = parse_research_ref(research_ref)
        page_limit = bounded_limit(
            limit,
            default=DEFAULT_TIMELINE_LIMIT,
            maximum=MAX_TIMELINE_LIMIT,
        )
        cursor = decode_cursor(after, kind="timeline") if after else None
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            if cursor is None:
                rows = conn.execute(
                    TIMELINE_FIRST_SQL,
                    (branch_id, owner, instance_id, page_limit + 1),
                ).fetchall()
            else:
                rows = conn.execute(
                    TIMELINE_AFTER_SQL,
                    (
                        branch_id,
                        cursor["at"],
                        cursor["at"],
                        cursor["id"],
                        owner,
                        instance_id,
                        page_limit + 1,
                    ),
                ).fetchall()
        if not rows:
            raise KeyError("profile research not found")
        rows = [row for row in rows if row["trace_id"] is not None]
        return _bounded_transition_page(
            rows=rows,
            research_ref=research_ref,
            page_limit=page_limit,
            identity={
                "schema_version": 1,
                "research_ref": research_ref_for(instance_id, branch_id),
            },
        )

    def list_work_package_timeline(
        self,
        *,
        owner: str,
        work_package_ref: str,
        branch_id: str,
        limit: int = DEFAULT_TIMELINE_LIMIT,
        after: str = "",
    ) -> dict[str, Any]:
        work_package_id = parse_work_package_ref(work_package_ref)
        branch_id = _identifier(branch_id, field="branch_id")
        page_limit = bounded_limit(
            limit,
            default=DEFAULT_TIMELINE_LIMIT,
            maximum=MAX_TIMELINE_LIMIT,
        )
        cursor = decode_cursor(after, kind="timeline") if after else None
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            if cursor is None:
                rows = conn.execute(
                    WORK_PACKAGE_TIMELINE_FIRST_SQL,
                    (branch_id, owner, work_package_id, page_limit + 1),
                ).fetchall()
            else:
                rows = conn.execute(
                    WORK_PACKAGE_TIMELINE_AFTER_SQL,
                    (
                        branch_id,
                        cursor["at"],
                        cursor["at"],
                        cursor["id"],
                        owner,
                        work_package_id,
                        page_limit + 1,
                    ),
                ).fetchall()
        if not rows:
            raise KeyError("profile research not found")
        current_instance_id = str(rows[0]["current_instance_id"])
        rows = [row for row in rows if row["trace_id"] is not None]
        current_ref = research_ref_for(current_instance_id, branch_id)
        return _bounded_transition_page(
            rows=rows,
            research_ref=current_ref,
            page_limit=page_limit,
            identity={
                "schema_version": 2,
                "work_package_ref": work_package_ref_for(work_package_id),
                "research_ref": current_ref,
            },
        )

    def get_report_checkpoint(
        self,
        *,
        owner: str,
        work_package_ref: str,
        branch_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        """Read one immutable historical Carrier without touching current heads."""
        work_package_id = parse_work_package_ref(work_package_ref)
        branch_id = _identifier(branch_id, field="branch_id")
        trace_id = _identifier(trace_id, field="trace_id")
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            row = conn.execute(
                REPORT_CHECKPOINT_SQL,
                (branch_id, trace_id, owner, work_package_id),
            ).fetchone()
        if row is None:
            raise KeyError("historical report checkpoint not found")
        evidence = orjson.loads(row["evidence_json"] or "{}")
        checkpoint = evidence.get("research_cycle_checkpoint")
        if not isinstance(checkpoint, dict):
            raise ValueError(
                "historical trace has no complete Research Cycle checkpoint"
            )
        carrier = report_checkpoint_projection(
            instance_id=str(row["trace_instance_id"]),
            work_package_id=str(row["work_package_id"]),
            branch_id=str(row["trace_branch_id"]),
            workspace_id=str(row["workspace_id"]),
            graph_id=str(row["graph_id"]),
            graph_version=int(row["graph_version"]),
            title=str(row["label"]),
            product_group=str(row["product_group"]),
            current_node=str(row["to_node"]),
            # A trace does not persist a branch-status snapshot. Never project
            # the later physical-branch status as if it were historical fact.
            status="historical",
            trace_id=str(row["trace_id"]),
            edge_id=str(row["edge_id"]),
            from_node=str(row["from_node"]),
            created_at=float(row["trace_created_at"]),
            checkpoint=checkpoint,
            trace_evidence=evidence,
            evidence_refs=evidence.get("evidence_refs") or [],
        )
        if carrier is None:
            raise ValueError("historical trace cannot produce a report Carrier")
        return bounded_projection(carrier)
