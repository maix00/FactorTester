"""Explicit single-row reads for checkpoint-scoped research objects."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import orjson
import settings as Settings
from server.services.research_graph.protocol import loads
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.research_cycle.run_spec_objects import (
    load_run_spec_object,
)
from server.services.research_graph.report_checkpoint import (
    research_cycle_deltas,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
)
from server.services.research_run_projections import project_run
from server.services.research_report_presentations import (
    run_spec_presentation,
    trial_plan_presentation,
)
from tools.data.sqlite.db import connect_sqlite


def load_research_cycle_object(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    object_type: str,
    object_id: str,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Return one requested body from HEAD or an explicit checkpoint."""
    cycle_binding = {
        "claim": ("claims", "claim_id"),
        "obligation": ("obligations", "obligation_id"),
    }.get(object_type)
    if cycle_binding is None and object_type not in {
        "evidence", "trial_plan", "delta", "run", "run_spec", "task",
    }:
        raise ValueError("research cycle object_type is invalid")
    if object_type == "run":
        return _load_run_object(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
            object_id=object_id,
            trace_id=trace_id,
        )
    if object_type == "run_spec":
        return load_run_spec_object(
            instance_id=instance_id,
            branch_id=branch_id,
            owner=owner,
            object_id=object_id,
            trace_id=trace_id,
        )
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        if trace_id:
            row = conn.execute(
                """
                SELECT t.evidence_json
                FROM research_graph_instances AS i
                JOIN research_graph_trace AS t
                  ON t.instance_id=i.instance_id
                WHERE i.instance_id=? AND t.branch_id=? AND i.owner=?
                  AND t.trace_id=?
                """,
                (instance_id, branch_id, owner, trace_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT t.evidence_json
                FROM research_graph_instances AS i
                JOIN research_graph_branches AS b
                  ON b.instance_id=i.instance_id
                JOIN research_graph_trace AS t
                  ON t.trace_id=b.latest_trace_id
                WHERE i.instance_id=? AND b.branch_id=? AND i.owner=?
                """,
                (instance_id, branch_id, owner),
            ).fetchone()
    if row is None:
        raise KeyError("research cycle object not found")
    evidence = loads(row["evidence_json"]) or {}
    if object_type == "task":
        if object_id not in _named_values(evidence, "task_ref"):
            raise KeyError("research cycle object not found")
        return {
            "schema_version": 1,
            "object_kind": "task",
            "task_ref": object_id,
        }
    if object_type == "trial_plan":
        plan = evidence.get("trial_plan")
        if not isinstance(plan, dict):
            raise KeyError("research cycle object not found")
        value = canonical_trial_plan(plan)
        identities = {
            str(value["trial_plan_id"]),
            "sha256:" + trial_plan_hash(value),
        }
        if object_id not in identities:
            raise KeyError("research cycle object not found")
        presentation = trial_plan_presentation(value)
        return {
            **deepcopy(value),
            "trial_plan_hash": trial_plan_hash(value),
            "alias_zh": presentation["alias_zh"],
            "summary_zh": presentation["summary_zh"],
            "complete_parameters_json": presentation[
                "complete_parameters_json"
            ],
        }
    if object_type == "evidence":
        value = next(
            (
                item for item in _evidence_envelopes(
                    evidence.get("server_evidence")
                )
                if str(item.get("envelope_hash") or "") == object_id
            ),
            None,
        )
        if value is None:
            raise KeyError("research cycle object not found")
        return validate_agent_evidence_envelope(value)
    if object_type == "delta":
        if not trace_id:
            raise KeyError("delta object requires a checkpoint trace")
        trace_prefix = f"{trace_id}:"
        if not object_id.startswith(trace_prefix):
            raise KeyError("research cycle object not found")
        remainder = object_id.removeprefix(trace_prefix)
        parts = remainder.split(":", 1)
        if len(parts) != 2 or parts[0] not in {"obligation", "claim"}:
            raise KeyError("research cycle object not found")
        object_kind, object_id_value = parts
        changes = research_cycle_deltas(evidence)
        candidates = (
            changes[0] if object_kind == "obligation" else changes[1]
        )
        change = next(
            (
                item for item in candidates
                if item.get(f"{object_kind}_id") == object_id_value
            ),
            None,
        )
        if change is None:
            raise KeyError("research cycle object not found")
        return {
            "schema_version": 1,
            "delta_ref": f"delta:{object_id}",
            "trace_ref": f"trace:{trace_id}",
            "object_kind": object_kind,
            "object_id": object_id_value,
            "from_state": change["from_state"],
            "to_state": change["to_state"],
        }
    collection, identifier = cycle_binding
    checkpoint = validate_research_cycle_checkpoint(
        evidence.get("research_cycle_checkpoint")
    )
    value = next(
        (
            item
            for item in checkpoint[collection]
            if item[identifier] == object_id
        ),
        None,
    )
    if value is None:
        raise KeyError("research cycle object not found")
    return deepcopy(value)


def _load_run_object(
    *,
    instance_id: str,
    branch_id: str,
    owner: str,
    object_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    """Lazy-load one immutable RunSpec named by the requested checkpoint."""
    trace_clause = "t.trace_id=?" if trace_id else "t.trace_id=b.latest_trace_id"
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            f"""
            SELECT t.evidence_json, r.*
            FROM research_graph_instances AS i
            JOIN research_graph_branches AS b
              ON b.instance_id=i.instance_id AND b.branch_id=?
            JOIN research_graph_trace AS t
              ON t.instance_id=i.instance_id AND t.branch_id=b.branch_id
            JOIN research_runs AS r
              ON r.run_id=? AND r.owner=i.owner
            WHERE i.instance_id=? AND i.owner=? AND {trace_clause}
            """,
            (
                (branch_id, object_id, instance_id, owner, trace_id)
                if trace_id
                else (branch_id, object_id, instance_id, owner)
            ),
        ).fetchone()
    if row is None:
        raise KeyError("research cycle object not found")
    evidence = loads(row["evidence_json"]) or {}
    if object_id not in _named_values(evidence, "run_id"):
        raise KeyError("research cycle object not found")
    run = project_run(row)
    presentation = run_spec_presentation(
        run["run_spec"],
        run_spec_hash=str(run["run_spec_hash"]),
        run_id=str(run["run_id"]),
        sample_identity={
            "sample_start": run.get("sample_start"),
            "sample_end": run.get("sample_end"),
            "sample_hash": run.get("sample_hash"),
        },
    )
    return {
        "schema_version": 1,
        "object_kind": "run",
        **run,
        "alias_zh": presentation["alias_zh"],
        "summary_zh": presentation["summary_zh"],
        "run_spec_json": orjson.dumps(
            run["run_spec"],
            option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
        ).decode(),
    }


def _evidence_envelopes(value: Any):
    if isinstance(value, dict):
        if (
            value.get("schema_version") == 2
            and isinstance(value.get("envelope_hash"), str)
            and isinstance(value.get("evidence_kind"), str)
        ):
            yield value
            return
        for child in value.values():
            yield from _evidence_envelopes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _evidence_envelopes(child)


def _named_values(value: Any, field: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        candidate = value.get(field)
        if isinstance(candidate, str) and candidate:
            result.add(candidate)
        for child in value.values():
            result.update(_named_values(child, field))
    elif isinstance(value, list):
        for child in value:
            result.update(_named_values(child, field))
    return result
