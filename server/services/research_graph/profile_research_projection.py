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
from typing import Any, Iterable

import orjson

import settings as Settings
from server.services.research_graph.protocol import loads
from tools.data.sqlite.db import connect_sqlite


DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50
DEFAULT_TIMELINE_LIMIT = 50
MAX_TIMELINE_LIMIT = 50
MAX_PROJECTION_BYTES = 64 * 1024
MAX_REF_BYTES = 256

LIST_FIRST_SQL = """
    SELECT i.instance_id, i.graph_id, i.graph_version, i.product_group,
           i.workspace_id, i.mode, i.created_at AS instance_created_at,
           COUNT(b.branch_id) AS branch_count,
           SUM(CASE WHEN b.status='running' THEN 1 ELSE 0 END)
               AS running_branch_count,
           MAX(b.updated_at) AS updated_at
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    WHERE i.owner=? AND i.workspace_id=?
    GROUP BY i.instance_id
    ORDER BY updated_at DESC, i.instance_id DESC
    LIMIT ?
"""

LIST_AFTER_SQL = """
    SELECT i.instance_id, i.graph_id, i.graph_version, i.product_group,
           i.workspace_id, i.mode, i.created_at AS instance_created_at,
           COUNT(b.branch_id) AS branch_count,
           SUM(CASE WHEN b.status='running' THEN 1 ELSE 0 END)
               AS running_branch_count,
           MAX(b.updated_at) AS updated_at
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    WHERE i.owner=? AND i.workspace_id=?
    GROUP BY i.instance_id
    HAVING (
        MAX(b.updated_at)<?
        OR (MAX(b.updated_at)=? AND i.instance_id<?)
    )
    ORDER BY updated_at DESC, i.instance_id DESC
    LIMIT ?
"""

WORK_PACKAGE_DETAIL_SQL = """
    SELECT i.instance_id, i.graph_id, i.graph_version, i.product_group,
           i.workspace_id, i.mode, i.created_at AS instance_created_at,
           b.branch_id, b.label, b.current_node, b.status,
           b.current_trial_plan_hash, b.latest_trace_id,
           b.created_at, b.updated_at,
           COUNT(*) OVER () AS total_branch_count
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    WHERE i.owner=? AND i.instance_id=?
    ORDER BY b.updated_at DESC, b.branch_id DESC
    LIMIT ?
"""

BRANCH_DETAIL_SQL = """
    SELECT i.instance_id, i.graph_id, i.graph_version, i.product_group,
           i.workspace_id, i.mode, i.created_at AS instance_created_at,
           b.branch_id, b.label, b.current_node, b.status,
           b.current_capability_resolution_hash,
           b.current_trial_plan_hash, b.trial_stage_projection_json,
           b.evidence_refs_json, b.omitted_evidence_count,
           b.latest_trace_id, b.created_at, b.updated_at,
           t.evidence_json AS latest_trace_evidence_json
    FROM research_graph_instances AS i
    JOIN research_graph_branches AS b
      ON b.instance_id=i.instance_id
    LEFT JOIN research_graph_trace AS t
      ON t.trace_id=b.latest_trace_id
    WHERE i.owner=? AND i.instance_id=? AND b.branch_id=?
"""

TIMELINE_FIRST_SQL = """
    SELECT t.trace_id, t.edge_id, t.from_node, t.to_node, t.actor,
           t.created_at, t.evidence_json
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
           t.created_at, t.evidence_json
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
                identifier=str(visible[-1]["instance_id"]),
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
        instance_id = parse_work_package_ref(research_ref)
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            rows = conn.execute(
                WORK_PACKAGE_DETAIL_SQL,
                (owner, instance_id, MAX_LIST_LIMIT + 1),
            ).fetchall()
        if not rows:
            raise KeyError("profile research not found")
        visible = rows[:MAX_LIST_LIMIT]
        first = visible[0]
        work_package_ref = work_package_ref_for(instance_id)
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
            "created_at": float(first["instance_created_at"]),
            "updated_at": max(float(row["updated_at"]) for row in rows),
            "branch_count": int(first["total_branch_count"]),
            "omitted_branch_count": max(
                int(first["total_branch_count"]) - len(visible), 0
            ),
            "branches": [_branch_summary(row) for row in visible],
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
                f"{work_package_ref_for(instance_id)}/branches/"
                f"{branch_id}/timeline"
            ),
            "refresh": refresh,
        }
        return bounded_projection(value)

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
    instance_id = str(row["instance_id"])
    work_package_ref = work_package_ref_for(instance_id)
    branch_count = int(row["branch_count"])
    running_count = int(row["running_branch_count"])
    return {
        "research_ref": work_package_ref,
        "work_package_ref": work_package_ref,
        "workspace_ref": workspace_ref_for(str(row["workspace_id"])),
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
    branch_id = str(row["branch_id"])
    branch_ref = research_ref_for(instance_id, branch_id)
    work_package_ref = work_package_ref_for(instance_id)
    trial_plan_hash = str(row["current_trial_plan_hash"] or "")
    return {
        "research_ref": work_package_ref,
        "work_package_ref": work_package_ref,
        "branch_ref": branch_ref,
        "workspace_ref": workspace_ref_for(str(row["workspace_id"])),
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
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "detail_href": (
            f"/api/profile-research/{work_package_ref}/branches/{branch_id}"
        ),
        "report_lookup_ref": branch_ref,
    }


def _transition_step(
    row: sqlite3.Row,
    research_ref: str,
) -> dict[str, Any]:
    evidence = _json_object(row["evidence_json"])
    trial_plan_refs = _trial_plan_refs(evidence)
    obligation_changes, claim_changes = _research_cycle_deltas(evidence)
    obligation_refs = _unique([
        *(
            f"obligation:{item['obligation_id']}"
            for item in obligation_changes
        ),
        *_named_refs(evidence, "obligation_id", prefix="obligation:"),
    ])
    claim_refs = _unique([
        *(f"claim:{item['claim_id']}" for item in claim_changes),
        *_named_refs(evidence, "claim_id", prefix="claim:"),
    ])
    job_refs = _named_refs(evidence, "job_id", prefix="job:")
    return {
        "step_ref": f"trace:{str(row['trace_id'])}",
        "research_ref": research_ref,
        "edge_ref": f"graph-edge:{str(row['edge_id'])}",
        "from_node": str(row["from_node"]),
        "to_node": str(row["to_node"]),
        "actor_ref": f"actor:{str(row['actor'])}",
        "created_at": float(row["created_at"]),
        "evidence_refs": _safe_refs(evidence.get("evidence_refs") or []),
        "trial_plan_refs": trial_plan_refs,
        "obligation_refs": obligation_refs,
        "claim_refs": claim_refs,
        "job_refs": job_refs,
        "run_refs": _named_refs(evidence, "run_id", prefix="run:"),
        "obligation_changes": obligation_changes,
        "claim_changes": claim_changes,
        "object_hrefs": [
            (
                "/api/research-graph-instances/"
                f"{parse_research_ref(research_ref)[0]}/branches/"
                f"{parse_research_ref(research_ref)[1]}/cycle-objects/"
                f"{ref.split(':', 1)[0]}/{ref.split(':', 1)[1]}"
            )
            for ref in [*obligation_refs, *claim_refs]
        ],
        "job_stream_hrefs": [
            f"/api/jobs/{ref.removeprefix('job:')}/stream"
            for ref in job_refs
        ],
    }


def _cycle_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "protocol_status": "uninitialized",
            "projection_ref": None,
            "claims": [],
            "obligations": [],
            "closure": None,
        }
    claims = []
    for item in value.get("claims") or []:
        if not isinstance(item, dict):
            continue
        claim_id = _safe_identifier(item.get("claim_id"))
        if not claim_id:
            continue
        claims.append({
            "claim_ref": f"claim:{claim_id}",
            "claim_type": _bounded_text(item.get("claim_type"), 80),
            "evidence_state": _bounded_text(
                item.get("evidence_state"),
                48,
            ),
        })
    obligations = []
    for item in value.get("obligations") or []:
        if not isinstance(item, dict):
            continue
        obligation_id = _safe_identifier(item.get("obligation_id"))
        if not obligation_id:
            continue
        obligations.append({
            "obligation_ref": f"obligation:{obligation_id}",
            "status": _bounded_text(item.get("status"), 48),
            "materiality": _bounded_text(item.get("materiality"), 80),
            "question_summary": _bounded_text(
                item.get("epistemic_question"),
                240,
            ),
        })
    projection_hash = _safe_hash(value.get("projection_hash"))
    closure = value.get("closure")
    closure_projection = None
    if isinstance(closure, dict):
        closure_projection = {
            "proposal_ref": (
                f"proposal:{_safe_identifier(closure.get('proposal_id'))}"
                if _safe_identifier(closure.get("proposal_id"))
                else None
            ),
            "disposition": _bounded_text(
                closure.get("disposition"),
                80,
            ),
        }
    return {
        "protocol_status": "current",
        "projection_ref": (
            f"research-cycle:sha256:{projection_hash}"
            if projection_hash
            else None
        ),
        "claims": claims,
        "obligations": obligations,
        "closure": closure_projection,
    }


def _research_cycle_deltas(
    evidence: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    cycle = evidence.get("research_cycle")
    events = cycle.get("events") if isinstance(cycle, dict) else []
    obligation_changes: list[dict[str, str]] = []
    claim_changes: list[dict[str, str]] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        proposal = event.get("proposal")
        if not isinstance(proposal, dict):
            continue
        for item in proposal.get("obligation_delta") or []:
            if not isinstance(item, dict):
                continue
            identifier = _safe_identifier(item.get("obligation_id"))
            if identifier:
                obligation_changes.append({
                    "obligation_id": identifier,
                    "from_state": _bounded_text(
                        item.get("from_state"),
                        48,
                    ),
                    "to_state": _bounded_text(item.get("to_state"), 48),
                })
        for item in proposal.get("claim_evidence_delta") or []:
            if not isinstance(item, dict):
                continue
            identifier = _safe_identifier(item.get("claim_id"))
            if identifier:
                claim_changes.append({
                    "claim_id": identifier,
                    "from_state": _bounded_text(
                        item.get("from_state"),
                        48,
                    ),
                    "to_state": _bounded_text(item.get("to_state"), 48),
                })
    return obligation_changes[:50], claim_changes[:50]


def _trial_plan_refs(evidence: dict[str, Any]) -> list[str]:
    values: list[str] = []
    plan = evidence.get("trial_plan")
    if isinstance(plan, dict):
        plan_id = _safe_identifier(plan.get("trial_plan_id"))
        if plan_id:
            values.append(f"trial-plan:{plan_id}")
    for hash_value in _named_texts(evidence, "trial_plan_hash"):
        normalized = _safe_hash(hash_value)
        if normalized:
            values.append(f"trial-plan:sha256:{normalized}")
    return _unique(values)[:20]


def _named_refs(
    value: Any,
    key: str,
    *,
    prefix: str,
) -> list[str]:
    return _unique(
        f"{prefix}{item}"
        for item in _named_texts(value, key)
        if _safe_identifier(item)
    )[:20]


def _named_texts(value: Any, key: str) -> list[str]:
    found: list[str] = []

    def visit(item: Any) -> None:
        if len(found) >= 50:
            return
        if isinstance(item, dict):
            for child_key, child in item.items():
                if child_key == key and isinstance(child, str):
                    safe = _safe_identifier(child)
                    if safe:
                        found.append(safe)
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


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


def _safe_refs(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return _unique(
        str(value)
        for value in values
        if (
            isinstance(value, str)
            and value
            and len(value.encode()) <= MAX_REF_BYTES
        )
    )[:20]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _identifier(value: Any, *, field: str) -> str:
    normalized = _safe_identifier(value)
    if not normalized:
        raise ValueError(f"{field} is invalid")
    return normalized


def _safe_identifier(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if (
        not normalized
        or len(normalized.encode()) > 160
        or any(character not in (
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789-_."
        ) for character in normalized)
    ):
        return ""
    return normalized


def _safe_hash(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef"
        for character in normalized
    ):
        return ""
    return normalized


def _bounded_text(value: Any, max_bytes: int) -> str:
    text = str(value or "")
    raw = text.encode()
    if len(raw) <= max_bytes:
        return text
    return raw[: max_bytes - 3].decode(errors="ignore") + "..."


def _json_object(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    parsed = loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, dict) else {}
