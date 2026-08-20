"""Checkpoint-bound reads of immutable RunSpec objects."""

from __future__ import annotations

from typing import Any

import orjson
import settings as Settings

from server.services.research_graph.protocol import loads
from server.services.research_run_projections import project_run
from server.services.research_report_presentations import (
    run_spec_presentation,
)
from tools.data.sqlite.db import connect_sqlite


def load_run_spec_object(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    object_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    normalized_hash = object_id.removeprefix("sha256:")
    if (
        object_id == normalized_hash
        or len(normalized_hash) != 64
        or any(char not in "0123456789abcdef" for char in normalized_hash)
    ):
        raise ValueError("RunSpec object requires sha256:<hash>")
    trace_clause = "t.trace_id=?" if trace_id else "t.trace_id=b.latest_trace_id"
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT t.evidence_json, r.*
            FROM research_graph_instances AS i
            JOIN research_graph_branches AS b
              ON b.instance_id=i.instance_id AND b.branch_id=?
            JOIN research_graph_trace AS t
              ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
            JOIN research_runs AS r
              ON r.run_spec_hash=? AND r.owner=i.owner
            WHERE i.instance_id=? AND i.owner=? AND {trace_clause}
            ORDER BY r.created_at, r.run_id
            """,
            (
                (branch_id, normalized_hash, instance_id, owner, trace_id)
                if trace_id
                else (branch_id, normalized_hash, instance_id, owner)
            ),
        ).fetchall()
    for row in rows:
        evidence = loads(row["evidence_json"]) or {}
        bound_hashes = _named_values(evidence, "run_spec_hash")
        bound_run_ids = _named_values(evidence, "run_id")
        if (
            normalized_hash not in bound_hashes
            and str(row["run_id"]) not in bound_run_ids
        ):
            continue
        run = project_run(row)
        presentation = run_spec_presentation(
            run["run_spec"],
            run_spec_hash=normalized_hash,
            run_id=str(run["run_id"]),
            sample_identity={
                "sample_start": run.get("sample_start"),
                "sample_end": run.get("sample_end"),
                "sample_hash": run.get("sample_hash"),
            },
        )
        return {
            "schema_version": 1,
            "object_kind": "run_spec",
            "run_spec_hash": normalized_hash,
            "run_spec_version": int(run["run_spec_version"]),
            "configuration_id": str(run["configuration_id"]),
            "configuration_revision": int(run["configuration_revision"]),
            "alias_zh": presentation["alias_zh"],
            "summary_zh": presentation["summary_zh"],
            "complete_parameters_json": orjson.dumps(
                run["run_spec"],
                option=orjson.OPT_INDENT_2,
            ).decode(),
        }
    raise KeyError("research cycle object not found")


def _named_values(value: Any, field: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        candidate = value.get(field)
        if isinstance(candidate, str) and candidate:
            result.add(candidate.removeprefix("sha256:"))
        for child in value.values():
            result.update(_named_values(child, field))
    elif isinstance(value, list):
        for child in value:
            result.update(_named_values(child, field))
    return result
