"""Bounded, read-only research projections for local Agent Profiles.

Profiles remain client-owned.  The server authorizes the authenticated owner
against an explicit workspace reference and returns stable refs instead of
exposing its SQLite schema to the UI.
"""

from __future__ import annotations

import base64
import hashlib
import math
import sqlite3
from typing import Any

import orjson

import settings as Settings
from server.services.research_graph.protocol import loads
from server.services.research_graph.report_checkpoint import (
    cycle_projection as _cycle_projection,
    named_refs as _named_refs,
    report_checkpoint_projection,
    safe_hash as _safe_hash,
    safe_identifier as _safe_identifier,
    safe_refs as _safe_refs,
    transition_step_projection,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)
from tools.data.sqlite.db import connect_sqlite


DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50
DEFAULT_TIMELINE_LIMIT = 50
MAX_TIMELINE_LIMIT = 50
MAX_PROJECTION_BYTES = 64 * 1024
# The version tree is a navigation aid, not a second history store.  Keep a
# small root/head window for every visible branch so a large work package
# cannot turn one projection into an unbounded trace dump.
TREE_FIRST_WINDOW = 1
TREE_LAST_WINDOW = 1
MAX_TREE_NODES = 120

LIST_FIRST_SQL = """
    WITH candidates AS (
        SELECT i.instance_id,
               COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
                   AS work_package_id,
               i.created_by_profile_ref, i.current_owner_profile_ref,
               i.graph_id, i.graph_version, i.product_group,
               i.workspace_id, i.mode,
               (
                   SELECT MIN(root.created_at)
                   FROM research_graph_instances AS root
                   WHERE root.owner=i.owner AND COALESCE(
                       NULLIF(root.work_package_id, ''), root.instance_id
                   )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               ) AS instance_created_at,
               COUNT(b.branch_id) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS branch_count,
               SUM(CASE WHEN b.status='running' THEN 1 ELSE 0 END) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS running_branch_count,
               MAX(b.updated_at) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS updated_at,
               ROW_NUMBER() OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
                   ORDER BY b.updated_at DESC, i.graph_version DESC,
                            b.branch_id DESC
               ) AS head_rank
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        WHERE i.owner=? AND i.workspace_id=?
          AND b.is_current_incarnation=1
    )
    SELECT * FROM candidates WHERE head_rank=1
    ORDER BY updated_at DESC, work_package_id DESC
    LIMIT ?
"""

LIST_AFTER_SQL = """
    WITH candidates AS (
        SELECT i.instance_id,
               COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
                   AS work_package_id,
               i.created_by_profile_ref, i.current_owner_profile_ref,
               i.graph_id, i.graph_version, i.product_group,
               i.workspace_id, i.mode,
               (
                   SELECT MIN(root.created_at)
                   FROM research_graph_instances AS root
                   WHERE root.owner=i.owner AND COALESCE(
                       NULLIF(root.work_package_id, ''), root.instance_id
                   )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               ) AS instance_created_at,
               COUNT(b.branch_id) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS branch_count,
               SUM(CASE WHEN b.status='running' THEN 1 ELSE 0 END) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS running_branch_count,
               MAX(b.updated_at) OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
               ) AS updated_at,
               ROW_NUMBER() OVER (
                   PARTITION BY COALESCE(
                       NULLIF(i.work_package_id, ''), i.instance_id
                   )
                   ORDER BY b.updated_at DESC, i.graph_version DESC,
                            b.branch_id DESC
               ) AS head_rank
        FROM research_graph_instances AS i
        JOIN research_graph_branches AS b
          ON b.instance_id=i.instance_id
        WHERE i.owner=? AND i.workspace_id=?
          AND b.is_current_incarnation=1
    )
    SELECT * FROM candidates
    WHERE head_rank=1 AND (
        updated_at<? OR (updated_at=? AND work_package_id<?)
    )
    ORDER BY updated_at DESC, work_package_id DESC
    LIMIT ?
"""

WORK_PACKAGE_DETAIL_SQL = f"""
    SELECT i.instance_id,
           COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               AS work_package_id,
           i.created_by_profile_ref,
           i.current_owner_profile_ref, i.graph_id, i.graph_version,
           i.product_group,
           i.workspace_id, i.mode,
           (
               SELECT MIN(root.created_at)
               FROM research_graph_instances AS root
               WHERE root.owner=i.owner AND COALESCE(
                   NULLIF(root.work_package_id, ''), root.instance_id
               )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
           ) AS instance_created_at,
           b.branch_id, b.hypothesis_branch_id,
           b.label, b.current_node, b.status,
           b.current_trial_plan_hash, b.latest_trace_id,
           b.created_at, b.updated_at,
           lineage.edge_id AS lineage_edge_id,
           lineage.evidence_json AS lineage_evidence_json,
           CASE WHEN b.branch_id=(
               SELECT candidate.branch_id
               FROM research_graph_branches AS candidate
               JOIN research_graph_instances AS candidate_instance
                 ON candidate_instance.instance_id=candidate.instance_id
               WHERE COALESCE(
                   NULLIF(candidate_instance.work_package_id, ''),
                   candidate_instance.instance_id
               )=COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               ORDER BY candidate.updated_at DESC,
                        candidate_instance.graph_version DESC,
                        candidate.branch_id DESC
               LIMIT 1
           ) THEN (
               SELECT json_object(
                   'nodes', COALESCE(json_group_array(json_object(
                       'trace_id', selected.trace_id,
                       'instance_id', selected.instance_id,
                       'branch_id', selected.branch_id,
                       'hypothesis_branch_id', selected.hypothesis_branch_id,
                       'edge_id', selected.edge_id,
                       'from_node', selected.from_node,
                       'to_node', selected.to_node,
                       'created_at', selected.created_at,
                       'branch_status', selected.branch_status,
                       'latest_trace_id', selected.latest_trace_id,
                       'first_rank', selected.first_rank,
                       'last_rank', selected.last_rank
                   )), json('[]')),
                   'omitted_node_count', MAX(selected.total_trace_count)
                       - COUNT(selected.trace_id)
               )
               FROM (
                   SELECT ranked.*
                   FROM (
                       SELECT t.trace_id, t.instance_id, t.branch_id,
                              COALESCE(
                                  NULLIF(branch.hypothesis_branch_id, ''),
                                  branch.branch_id
                              ) AS hypothesis_branch_id,
                              t.edge_id,
                              t.from_node, t.to_node, t.created_at,
                              COALESCE((
                                  SELECT current.status
                                  FROM research_graph_branches AS current
                                  WHERE COALESCE(
                                      NULLIF(current.hypothesis_branch_id, ''),
                                      current.branch_id
                                  )=COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  ) AND current.is_current_incarnation=1
                                  LIMIT 1
                              ), branch.status) AS branch_status,
                              COALESCE((
                                  SELECT current.latest_trace_id
                                  FROM research_graph_branches AS current
                                  WHERE COALESCE(
                                      NULLIF(current.hypothesis_branch_id, ''),
                                      current.branch_id
                                  )=COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  ) AND current.is_current_incarnation=1
                                  LIMIT 1
                              ), branch.latest_trace_id) AS latest_trace_id,
                              branch.latest_trace_id AS incarnation_latest_trace_id,
                              ROW_NUMBER() OVER (
                                  PARTITION BY COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  )
                                  ORDER BY t.created_at ASC, t.trace_id ASC
                              ) AS first_rank,
                              ROW_NUMBER() OVER (
                                  PARTITION BY COALESCE(
                                      NULLIF(branch.hypothesis_branch_id, ''),
                                      branch.branch_id
                                  )
                                  ORDER BY t.created_at DESC, t.trace_id DESC
                              ) AS last_rank,
                              COUNT(*) OVER () AS total_trace_count
                       FROM research_graph_trace AS t
                       JOIN research_graph_branches AS branch
                         ON branch.instance_id=t.instance_id
                        AND branch.branch_id=t.branch_id
                       JOIN research_graph_instances AS trace_instance
                         ON trace_instance.instance_id=t.instance_id
                       WHERE COALESCE(
                           NULLIF(trace_instance.work_package_id, ''),
                           trace_instance.instance_id
                       )=COALESCE(
                           NULLIF(i.work_package_id, ''), i.instance_id
                       )
                         AND t.branch_id IN (
                             SELECT visible.branch_id
                             FROM research_graph_branches AS visible
                             JOIN research_graph_instances AS visible_instance
                               ON visible_instance.instance_id=visible.instance_id
                             WHERE COALESCE(
                                 NULLIF(visible_instance.work_package_id, ''),
                                 visible_instance.instance_id
                             )=COALESCE(
                                 NULLIF(i.work_package_id, ''), i.instance_id
                             )
                             ORDER BY visible.updated_at DESC,
                                      visible.branch_id DESC
                             LIMIT 50
                         )
                   ) AS ranked
                   WHERE ranked.total_trace_count<={MAX_TREE_NODES}
                      OR ranked.first_rank<={TREE_FIRST_WINDOW}
                      OR ranked.last_rank<={TREE_LAST_WINDOW}
                      OR ranked.trace_id=ranked.incarnation_latest_trace_id
                      OR ranked.edge_id IN (
                          '__branch_fork__', '__graph_continuation__'
                      )
                   ORDER BY ranked.created_at ASC, ranked.trace_id ASC
                   LIMIT {MAX_TREE_NODES}
               ) AS selected
           ) ELSE NULL END AS tree_json,
           COUNT(*) OVER () AS total_branch_count
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    LEFT JOIN research_graph_trace AS lineage
      ON lineage.trace_id=(
          SELECT candidate.trace_id
          FROM research_graph_trace AS candidate
          WHERE candidate.instance_id=b.instance_id
            AND candidate.branch_id=b.branch_id
            AND candidate.created_at=b.created_at
            AND candidate.edge_id IN (
                '__branch_fork__', '__graph_continuation__'
            )
          ORDER BY candidate.trace_id
          LIMIT 1
      )
    WHERE i.owner=? AND COALESCE(
        NULLIF(i.work_package_id, ''), i.instance_id
    )=? AND b.is_current_incarnation=1
    ORDER BY b.updated_at DESC, i.graph_version DESC, b.branch_id DESC
    LIMIT ?
"""

BRANCH_DETAIL_SQL = """
    SELECT i.instance_id,
           COALESCE(NULLIF(i.work_package_id, ''), i.instance_id)
               AS work_package_id,
           i.created_by_profile_ref,
           i.current_owner_profile_ref, i.graph_id, i.graph_version,
           i.product_group,
           i.workspace_id, i.mode, i.created_at AS instance_created_at,
           b.branch_id, b.label, b.current_node, b.status,
           b.current_capability_resolution_hash,
           b.current_trial_plan_hash, b.trial_stage_projection_json,
           b.evidence_refs_json, b.omitted_evidence_count,
           b.latest_trace_id, b.created_at, b.updated_at,
           t.edge_id AS latest_trace_edge_id,
           t.from_node AS latest_trace_from_node,
           t.created_at AS latest_trace_created_at,
           t.acting_profile_ref AS latest_trace_acting_profile_ref,
           t.evidence_json AS latest_trace_evidence_json,
           lineage.edge_id AS lineage_edge_id,
           lineage.evidence_json AS lineage_evidence_json
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    LEFT JOIN research_graph_trace AS t
      ON t.trace_id=b.latest_trace_id
    LEFT JOIN research_graph_trace AS lineage
      ON lineage.trace_id=(
          SELECT candidate.trace_id
          FROM research_graph_trace AS candidate
          WHERE candidate.instance_id=b.instance_id
            AND candidate.branch_id=b.branch_id
            AND candidate.created_at=b.created_at
            AND candidate.edge_id IN (
                '__branch_fork__', '__graph_continuation__'
            )
          ORDER BY candidate.trace_id
          LIMIT 1
      )
    WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?
"""

WORK_PACKAGE_BRANCH_DETAIL_SQL = BRANCH_DETAIL_SQL.replace(
    "WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?",
    """WHERE i.owner=? AND COALESCE(
        NULLIF(i.work_package_id, ''), i.instance_id
    )=? AND b.branch_id=? AND b.is_current_incarnation=1""",
)

TIMELINE_FIRST_SQL = """
    SELECT t.trace_id, t.edge_id, t.from_node, t.to_node, t.actor,
           t.acting_profile_ref,
           t.created_at, t.evidence_json, b.status AS branch_status,
           b.latest_trace_id
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id AND b.branch_id=?
    LEFT JOIN research_graph_trace AS t
      ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
    WHERE i.owner=? AND i.instance_id=?
    ORDER BY t.created_at DESC, t.trace_id DESC
    LIMIT ?
"""

TIMELINE_AFTER_SQL = """
    SELECT t.trace_id, t.edge_id, t.from_node, t.to_node, t.actor,
           t.created_at, t.evidence_json, b.status AS branch_status,
           b.latest_trace_id
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id AND b.branch_id=?
    LEFT JOIN research_graph_trace AS t
      ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
      AND (
        t.created_at<?
        OR (t.created_at=? AND t.trace_id<?)
      )
    WHERE i.owner=? AND i.instance_id=?
    ORDER BY t.created_at DESC, t.trace_id DESC
    LIMIT ?
"""

WORK_PACKAGE_TIMELINE_FIRST_SQL = """
    SELECT t.trace_id, t.instance_id AS trace_instance_id,
           t.branch_id AS trace_branch_id,
           t.edge_id, t.from_node, t.to_node, t.actor,
           t.acting_profile_ref, t.created_at, t.evidence_json,
           current.status AS branch_status,
           current.latest_trace_id,
           current.instance_id AS current_instance_id
    FROM research_graph_instances AS current_instance
    JOIN research_graph_branches AS current
      ON current.instance_id=current_instance.instance_id
     AND current.branch_id=? AND current.is_current_incarnation=1
    JOIN research_graph_branches AS history
      ON COALESCE(NULLIF(history.hypothesis_branch_id, ''), history.branch_id)
       = COALESCE(NULLIF(current.hypothesis_branch_id, ''), current.branch_id)
    JOIN research_graph_instances AS history_instance
      ON history_instance.instance_id=history.instance_id
    LEFT JOIN research_graph_trace AS t
      ON t.instance_id=history.instance_id AND t.branch_id=history.branch_id
    WHERE current_instance.owner=?
      AND COALESCE(
          NULLIF(current_instance.work_package_id, ''),
          current_instance.instance_id
      )=?
      AND history_instance.owner=current_instance.owner
      AND COALESCE(
          NULLIF(history_instance.work_package_id, ''),
          history_instance.instance_id
      )=COALESCE(
          NULLIF(current_instance.work_package_id, ''),
          current_instance.instance_id
      )
    ORDER BY t.created_at DESC, t.trace_id DESC
    LIMIT ?
"""

WORK_PACKAGE_TIMELINE_AFTER_SQL = WORK_PACKAGE_TIMELINE_FIRST_SQL.replace(
    "WHERE current_instance.owner=?",
    """WHERE t.trace_id IS NOT NULL AND (
        t.created_at<? OR (t.created_at=? AND t.trace_id<?)
    ) AND current_instance.owner=?""",
)

_TERMINAL_JOB_STATUSES = frozenset({
    "cancelled",
    "failed",
    "paused",
    "succeeded",
})
_LIVE_JOB_STATUSES = frozenset({
    "planning",
    "queued",
    "running",
    "submitted",
})


class ProfileResearchProjection:
    """Project profile-facing research with one bounded read per operation."""

    def list_research(
        self,
        *,
        owner: str,
        workspace_ref: str,
        limit: int = DEFAULT_LIST_LIMIT,
        after: str = "",
    ) -> dict[str, Any]:
        workspace_id = parse_workspace_ref(workspace_ref)
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
                    (owner, workspace_id, page_limit + 1),
                ).fetchall()
            else:
                rows = conn.execute(
                    LIST_AFTER_SQL,
                    (
                        owner,
                        workspace_id,
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
            "mode": str(first["mode"]),
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
        return self._branch_projection(row)

    def _branch_projection(self, row: sqlite3.Row) -> dict[str, Any]:
        instance_id = str(row["instance_id"])
        work_package_id = str(row["work_package_id"] or instance_id)
        branch_id = str(row["branch_id"])
        evidence = _json_object(row["latest_trace_evidence_json"])
        cycle = _cycle_projection(evidence.get("research_cycle_checkpoint"))
        job_refs = _named_refs(evidence, "job_id", prefix="job:")
        run_refs = _named_refs(evidence, "run_id", prefix="run:")
        job_status = _first_named_text(evidence, "status", parent_key="facts")
        terminal = bool(cycle["closure"]) or str(row["status"]) == "paused"
        if job_status in _LIVE_JOB_STATUSES and job_refs:
            refresh = {
                "mode": "job_sse",
                "href": f"/api/jobs/{job_refs[0].removeprefix('job:')}/stream",
                "terminal": False,
            }
        elif terminal or job_status in _TERMINAL_JOB_STATUSES:
            refresh = {"mode": "stopped", "terminal": True}
        else:
            refresh = {
                "mode": "conditional_etag",
                "minimum_interval_seconds": 5,
                "only_while_visible": True,
                "terminal": False,
            }
        value = {
            "schema_version": 2,
            **_branch_summary(row),
            "capability_resolution_ref": (
                "branch-resolution:"
                f"{instance_id}:{branch_id}:"
                f"{str(row['current_capability_resolution_hash'])}"
            ),
            "trial_stage": _json_object(
                row["trial_stage_projection_json"]
            ),
            "evidence_refs": _safe_refs(
                loads(row["evidence_refs_json"]) or []
            ),
            "omitted_evidence_count": int(
                row["omitted_evidence_count"]
            ),
            "research_cycle": cycle,
            "job_refs": job_refs,
            "run_refs": run_refs,
            "timeline_href": (
                f"/api/profile-research/"
                f"{work_package_ref_for(work_package_id)}/branches/"
                f"{branch_id}/timeline"
            ),
            "refresh": refresh,
            "report_checkpoint": (
                report_checkpoint_projection(
                    instance_id=str(row["instance_id"]),
                    work_package_id=work_package_id,
                    branch_id=str(row["branch_id"]),
                    workspace_id=str(row["workspace_id"]),
                    graph_id=str(row["graph_id"]),
                    graph_version=int(row["graph_version"]),
                    title=str(row["label"]),
                    product_group=str(row["product_group"]),
                    current_node=str(row["current_node"]),
                    status=str(row["status"]),
                    trace_id=str(row["latest_trace_id"]),
                    edge_id=str(row["latest_trace_edge_id"]),
                    from_node=str(row["latest_trace_from_node"]),
                    created_at=float(row["latest_trace_created_at"]),
                    checkpoint=evidence.get("research_cycle_checkpoint"),
                    trace_evidence=evidence,
                    evidence_refs=loads(row["evidence_refs_json"]) or [],
                    omitted_evidence_count=int(
                        row["omitted_evidence_count"]
                    ),
                )
                if row["latest_trace_id"]
                else None
            ),
        }
        return bounded_projection(value)

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
        return self._branch_projection(row)

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
        has_more = len(rows) > page_limit
        visible = rows[:page_limit]
        items = [_transition_step(row, research_ref) for row in visible]
        next_cursor = (
            encode_cursor(
                kind="timeline",
                at=float(visible[-1]["created_at"]),
                identifier=str(visible[-1]["trace_id"]),
            )
            if has_more and visible
            else None
        )
        return bounded_projection({
            "schema_version": 1,
            "research_ref": research_ref_for(instance_id, branch_id),
            "items": items,
            "next_cursor": next_cursor,
        })

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
        rows = [row for row in rows if row["trace_id"] is not None]
        has_more = len(rows) > page_limit
        visible = rows[:page_limit]
        current_instance_id = str(rows[0]["current_instance_id"])
        current_ref = research_ref_for(current_instance_id, branch_id)
        items = [_transition_step(row, current_ref) for row in visible]
        next_cursor = (
            encode_cursor(
                kind="timeline",
                at=float(visible[-1]["created_at"]),
                identifier=str(visible[-1]["trace_id"]),
            )
            if has_more and visible
            else None
        )
        return bounded_projection({
            "schema_version": 2,
            "work_package_ref": work_package_ref_for(work_package_id),
            "research_ref": current_ref,
            "items": items,
            "next_cursor": next_cursor,
        })


def ensure_profile_research_indexes(conn: sqlite3.Connection) -> None:
    """Create query-only indexes during the existing cold schema path."""
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_instances_owner_workspace
        ON research_graph_instances(owner, workspace_id, instance_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_branches_instance_updated
        ON research_graph_branches(
            instance_id, updated_at DESC, branch_id DESC
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_graph_trace_branch_timeline
        ON research_graph_trace(
            instance_id, branch_id, created_at DESC, trace_id DESC
        )
        """
    )


def bounded_limit(value: Any, *, default: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed < 1 or parsed > maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return parsed


def workspace_ref_for(workspace_id: str) -> str:
    return f"workspace:{_identifier(workspace_id, field='workspace_id')}"


def parse_workspace_ref(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("workspace:"):
        raise ValueError("workspace_ref must use workspace:<id>")
    return _identifier(
        value.removeprefix("workspace:"),
        field="workspace_ref",
    )


def work_package_ref_for(instance_id: str) -> str:
    return f"work-package:{_identifier(instance_id, field='instance_id')}"


def parse_work_package_ref(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("research_ref must be a string")
    parts = value.split(":")
    if len(parts) != 2 or parts[0] != "work-package":
        raise ValueError("research_ref must use work-package:<instance>")
    return _identifier(parts[1], field="instance_id")


def research_ref_for(instance_id: str, branch_id: str) -> str:
    return (
        "graph-branch:"
        f"{_identifier(instance_id, field='instance_id')}:"
        f"{_identifier(branch_id, field='branch_id')}"
    )


def parse_research_ref(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("research_ref must be a string")
    parts = value.split(":")
    if len(parts) != 3 or parts[0] != "graph-branch":
        raise ValueError(
            "research_ref must use graph-branch:<instance>:<branch>"
        )
    return (
        _identifier(parts[1], field="instance_id"),
        _identifier(parts[2], field="branch_id"),
    )


def encode_cursor(*, kind: str, at: float, identifier: str) -> str:
    payload = orjson.dumps({
        "v": 1,
        "kind": kind,
        "at": float(at),
        "id": _identifier(identifier, field="cursor id"),
    })
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str, *, kind: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("invalid cursor")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = orjson.loads(
            base64.urlsafe_b64decode((value + padding).encode())
        )
        if (
            not isinstance(decoded, dict)
            or decoded.get("v") != 1
            or decoded.get("kind") != kind
        ):
            raise ValueError
        at = float(decoded["at"])
        if not math.isfinite(at):
            raise ValueError
        identifier = _identifier(decoded["id"], field="cursor id")
    except (KeyError, TypeError, ValueError, orjson.JSONDecodeError) as exc:
        raise ValueError("invalid cursor") from exc
    return {"at": at, "id": identifier}


def projection_etag(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def bounded_projection(value: dict[str, Any]) -> dict[str, Any]:
    size = len(orjson.dumps(value))
    if size > MAX_PROJECTION_BYTES:
        raise ValueError(
            f"profile research projection exceeds {MAX_PROJECTION_BYTES} bytes"
        )
    return value


def _work_package_summary(row: sqlite3.Row) -> dict[str, Any]:
    work_package_id = str(row["work_package_id"] or row["instance_id"])
    work_package_ref = work_package_ref_for(work_package_id)
    branch_count = int(row["branch_count"])
    running_count = int(row["running_branch_count"])
    return {
        "research_ref": work_package_ref,
        "work_package_ref": work_package_ref,
        "workspace_ref": workspace_ref_for(str(row["workspace_id"])),
        "created_by_profile_ref": _profile_ref(row, "created_by_profile_ref"),
        "current_owner_profile_ref": _profile_ref(
            row, "current_owner_profile_ref"
        ),
        "graph_ref": (
            f"{str(row['graph_id'])}@v{int(row['graph_version'])}"
        ),
        "product_group": str(row["product_group"]),
        "mode": str(row["mode"]),
        "branch_count": branch_count,
        "running_branch_count": running_count,
        "status": "running" if running_count else "stopped",
        "created_at": float(row["instance_created_at"]),
        "updated_at": float(row["updated_at"]),
        "detail_href": f"/api/profile-research/{work_package_ref}",
        "report_lookup_ref": work_package_ref,
    }


def _branch_summary(row: sqlite3.Row) -> dict[str, Any]:
    instance_id = str(row["instance_id"])
    work_package_id = str(row["work_package_id"] or instance_id)
    branch_id = str(row["branch_id"])
    branch_ref = research_ref_for(instance_id, branch_id)
    work_package_ref = work_package_ref_for(work_package_id)
    trial_plan_hash = str(row["current_trial_plan_hash"] or "")
    return {
        "research_ref": work_package_ref,
        "work_package_ref": work_package_ref,
        "branch_ref": branch_ref,
        "workspace_ref": workspace_ref_for(str(row["workspace_id"])),
        "created_by_profile_ref": _profile_ref(row, "created_by_profile_ref"),
        "current_owner_profile_ref": _profile_ref(
            row, "current_owner_profile_ref"
        ),
        "graph_ref": (
            f"{str(row['graph_id'])}@v{int(row['graph_version'])}"
        ),
        "product_group": str(row["product_group"]),
        "mode": str(row["mode"]),
        "label": str(row["label"]),
        "current_node": str(row["current_node"]),
        "status": str(row["status"]),
        "trial_plan_ref": (
            f"trial-plan:sha256:{trial_plan_hash}"
            if trial_plan_hash
            else None
        ),
        "latest_trace_ref": (
            f"trace:{str(row['latest_trace_id'])}"
            if row["latest_trace_id"]
            else None
        ),
        "latest_acting_profile_ref": _profile_ref(
            row, "latest_trace_acting_profile_ref"
        ),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "detail_href": (
            f"/api/profile-research/{work_package_ref}/branches/{branch_id}"
        ),
        "report_lookup_ref": branch_ref,
        "lineage": _branch_lineage(row),
    }


def _branch_lineage(row: sqlite3.Row) -> dict[str, Any]:
    """Project only lineage written atomically by branch creation paths."""
    try:
        edge_id = str(row["lineage_edge_id"] or "")
        evidence = _json_object(row["lineage_evidence_json"])
    except (IndexError, KeyError):
        # Any projection path lacking creation evidence fails closed.
        return {"relation": "unknown"}
    if not edge_id:
        if (
            str(row["label"]) == "primary"
            and float(row["created_at"])
            == float(row["instance_created_at"])
        ):
            return {"relation": "root"}
        return {"relation": "unknown"}
    if edge_id == "__branch_fork__":
        descriptor = evidence.get("branch_fork")
        if not isinstance(descriptor, dict):
            return {"relation": "unknown"}
        source_branch_id = _safe_identifier(
            descriptor.get("source_branch_id")
        )
        source_trace_ref = _safe_trace_ref(
            descriptor.get("source_trace_ref")
        )
        if not source_branch_id:
            return {"relation": "unknown"}
        value = {
            "relation": "fork",
            "source_branch_ref": research_ref_for(
                str(row["instance_id"]), source_branch_id
            ),
        }
        if source_trace_ref:
            value["source_trace_ref"] = source_trace_ref
        return value
    if edge_id == "__graph_continuation__":
        descriptor = evidence.get("graph_continuation")
        if not isinstance(descriptor, dict):
            return {"relation": "unknown"}
        source_instance_id = _safe_identifier(
            descriptor.get("source_instance_id")
        )
        source_branch_id = _safe_identifier(
            descriptor.get("source_branch_id")
        )
        source_trace_id = _safe_identifier(
            descriptor.get("source_trace_id")
        )
        checkpoint_hash = _safe_hash(
            descriptor.get("source_checkpoint_hash")
        )
        if not all((
            source_instance_id,
            source_branch_id,
            source_trace_id,
            checkpoint_hash,
        )):
            return {"relation": "unknown"}
        return {
            "relation": "continuation",
            "source_branch_ref": research_ref_for(
                source_instance_id, source_branch_id
            ),
            "source_trace_ref": f"trace:{source_trace_id}",
            "source_checkpoint_hash": checkpoint_hash,
        }
    return {"relation": "unknown"}


def _tree_projection(
    value: Any,
    branch_rows: list[sqlite3.Row],
) -> dict[str, Any]:
    """Decode the bounded tree carrier and add only authoritative edges.

    Trace rows are the only checkpoint nodes.  The projection never invents a
    merge: ordinary edges connect adjacent loaded checkpoints on one branch;
    fork/continuation edges are emitted only when their creation evidence was
    valid enough for ``_branch_lineage``.
    """
    if value in (None, ""):
        return {"schema_version": 1, "nodes": [], "edges": [],
                "omitted_node_count": 0}
    payload = _json_object(value)
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    branch_by_hypothesis = {
        str(row["hypothesis_branch_id"] or row["branch_id"]): row
        for row in branch_rows
    }
    nodes: list[dict[str, Any]] = []
    by_branch: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        trace_id = _safe_identifier(raw.get("trace_id"))
        branch_id = _safe_identifier(raw.get("branch_id"))
        hypothesis_branch_id = _safe_identifier(
            raw.get("hypothesis_branch_id")
        ) or branch_id
        edge_id = _safe_identifier(raw.get("edge_id"))
        if not (trace_id and branch_id and hypothesis_branch_id and edge_id):
            continue
        if hypothesis_branch_id not in branch_by_hypothesis:
            # The SQL limits nodes to visible branches.  Keep this guard in
            # case an older cache returns a malformed carrier.
            continue
        try:
            created_at = float(raw.get("created_at"))
            first_rank = int(raw.get("first_rank"))
            last_rank = int(raw.get("last_rank"))
        except (TypeError, ValueError):
            continue
        head = branch_by_hypothesis[hypothesis_branch_id]
        branch_ref = research_ref_for(
            str(head["instance_id"]), str(head["branch_id"])
        )
        trace_ref = f"trace:{trace_id}"
        node = {
            "checkpoint_ref": trace_ref,
            "branch_ref": branch_ref,
            "edge_ref": edge_id,
            "from_node": str(raw.get("from_node") or ""),
            "to_node": str(raw.get("to_node") or ""),
            "created_at": created_at,
            "status": (
                str(raw.get("branch_status"))
                if trace_id == str(raw.get("latest_trace_id") or "")
                else "historical"
            ),
            "is_head": trace_id == str(raw.get("latest_trace_id") or ""),
            "is_root": first_rank == 1,
            # Keep ranks private to the projection builder. The public carrier
            # uses checkpoint_ref as the node identity.
            "_sequence_rank": first_rank,
            "_history_rank": last_rank,
            "_instance_id": str(raw.get("instance_id") or ""),
            "_physical_branch_id": branch_id,
        }
        nodes.append(node)
        by_branch.setdefault(hypothesis_branch_id, []).append(node)

    nodes.sort(
        key=lambda item: (item["created_at"], item["checkpoint_ref"])
    )
    edges: list[dict[str, Any]] = []
    for hypothesis_branch_id, branch_nodes in by_branch.items():
        branch_nodes.sort(
            key=lambda item: (
                item["_sequence_rank"], item["checkpoint_ref"]
            )
        )
        for previous, current in zip(branch_nodes, branch_nodes[1:]):
            if current["_sequence_rank"] != previous["_sequence_rank"] + 1:
                # Root/head window intentionally may contain a gap.  A
                # connector over an omitted checkpoint would be misleading.
                continue
            if current["edge_ref"] in {
                "__branch_fork__", "__graph_continuation__",
            }:
                # The authoritative lineage edge below is the connection for
                # this checkpoint; emitting a transition as well duplicates it.
                continue
            edges.append({
                "edge_ref": current["edge_ref"],
                "relation": "transition",
                "source_node_ref": previous["checkpoint_ref"],
                "target_node_ref": current["checkpoint_ref"],
                "source_branch_ref": previous["branch_ref"],
                "target_branch_ref": current["branch_ref"],
            })
        row = branch_by_hypothesis[hypothesis_branch_id]
        lineage = _branch_lineage(row)
        target = next((item for item in branch_nodes if (
            item["_instance_id"] == str(row["instance_id"])
            and item["_physical_branch_id"] == str(row["branch_id"])
            and item["edge_ref"] in {
                "__branch_fork__", "__graph_continuation__",
            }
        )), None)
        if target and lineage.get("relation") in {"fork", "continuation"}:
            source_branch_ref = lineage.get("source_branch_ref")
            source_trace_ref = lineage.get("source_trace_ref")
            if isinstance(source_branch_ref, str):
                edges.append({
                    "edge_ref": (
                        "lineage:"
                        f"{hypothesis_branch_id}:{target['checkpoint_ref']}"
                    ),
                    "relation": str(lineage["relation"]),
                    "source_node_ref": source_trace_ref or "",
                    "target_node_ref": target["checkpoint_ref"],
                    "source_branch_ref": source_branch_ref,
                    "target_branch_ref": target["branch_ref"],
                })
    public_nodes = [
        {key: value for key, value in node.items() if not key.startswith("_")}
        for node in nodes
    ]
    return {
        "schema_version": 1,
        "nodes": public_nodes,
        "edges": edges,
        "omitted_node_count": max(
            int(payload.get("omitted_node_count") or 0), 0
        ),
    }


def _safe_trace_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("trace:"):
        return ""
    identifier = _safe_identifier(value.removeprefix("trace:"))
    return f"trace:{identifier}" if identifier else ""


def _transition_step(
    row: sqlite3.Row,
    research_ref: str,
) -> dict[str, Any]:
    fallback_instance_id, fallback_branch_id = parse_research_ref(research_ref)
    try:
        trace_instance_id = str(row["trace_instance_id"] or fallback_instance_id)
        trace_branch_id = str(row["trace_branch_id"] or fallback_branch_id)
    except (IndexError, KeyError):
        trace_instance_id = fallback_instance_id
        trace_branch_id = fallback_branch_id
    evidence = _json_object(row["evidence_json"])
    step = transition_step_projection(
        trace_id=str(row["trace_id"]),
        edge_id=str(row["edge_id"]),
        from_node=str(row["from_node"]),
        to_node=str(row["to_node"]),
        created_at=float(row["created_at"]),
        evidence=evidence,
    )
    step["status"] = (
        str(row["branch_status"])
        if str(row["trace_id"]) == str(row["latest_trace_id"])
        else "historical"
    )
    object_refs = [
        *step["obligation_refs"], *step["claim_refs"], *step["delta_refs"]
    ]
    plan = evidence.get("trial_plan")
    if isinstance(plan, dict):
        try:
            canonical_plan = canonical_trial_plan(plan)
        except ValueError:
            canonical_plan = None
        if canonical_plan is not None:
            resolvable_plan_refs = {
                "trial-plan:" + canonical_plan["trial_plan_id"],
                "trial-plan:sha256:" + trial_plan_hash(canonical_plan),
            }
            object_refs.extend(
                ref for ref in step["trial_plan_refs"]
                if ref in resolvable_plan_refs
            )
    available_evidence = {
        "evidence:" + str(item.get("envelope_hash"))
        for item in _checkpoint_evidence_envelopes(
            evidence.get("server_evidence")
        )
    }
    object_refs.extend(
        ref for ref in step["evidence_refs"]
        if ref in available_evidence
    )
    return {
        **step,
        "research_ref": research_ref,
        "acting_profile_ref": _profile_ref(row, "acting_profile_ref"),
        "actor_ref": f"actor:{str(row['actor'])}",
        "object_hrefs": [
            (
                "/api/research-graph-instances/"
                f"{trace_instance_id}/branches/"
                f"{trace_branch_id}/cycle-objects/"
                f"{_cycle_object_type(ref)}/{ref.split(':', 1)[1]}"
                f"?trace_id={str(row['trace_id'])}"
            )
            for ref in object_refs
        ],
        "job_stream_hrefs": [
            f"/api/jobs/{ref.removeprefix('job:')}/stream"
            for ref in step["job_refs"]
        ],
    }


def _checkpoint_evidence_envelopes(value: Any):
    if isinstance(value, dict):
        if (
            value.get("schema_version") == 2
            and isinstance(value.get("envelope_hash"), str)
            and isinstance(value.get("evidence_kind"), str)
        ):
            yield value
            return
        for child in value.values():
            yield from _checkpoint_evidence_envelopes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _checkpoint_evidence_envelopes(child)


def _cycle_object_type(reference: str) -> str:
    kind = reference.split(":", 1)[0]
    if kind == "trial-plan":
        return "trial_plan"
    return kind


def _first_named_text(
    value: Any,
    key: str,
    *,
    parent_key: str,
) -> str:
    if isinstance(value, dict):
        parent = value.get(parent_key)
        if isinstance(parent, dict) and isinstance(parent.get(key), str):
            return str(parent[key])
        for child in value.values():
            found = _first_named_text(
                child,
                key,
                parent_key=parent_key,
            )
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_named_text(
                child,
                key,
                parent_key=parent_key,
            )
            if found:
                return found
    return ""


def _identifier(value: Any, *, field: str) -> str:
    normalized = _safe_identifier(value)
    if not normalized:
        raise ValueError(f"{field} is invalid")
    return normalized


def _json_object(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    parsed = loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, dict) else {}


def _profile_ref(row: sqlite3.Row, key: str) -> str | None:
    """Expose only the opaque Profile reference, never local Profile data."""
    try:
        value = row[key]
    except (IndexError, KeyError):
        return None
    value = str(value or "")
    return value or None
