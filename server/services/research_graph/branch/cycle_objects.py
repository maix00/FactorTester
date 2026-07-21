"""Explicit single-row reads for checkpoint-scoped research objects."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import settings as Settings
from server.services.research_graph.protocol import loads
from server.services.research_graph.research_cycle.replay import (
    validate_research_cycle_checkpoint,
)
from server.services.research_graph.research_cycle.evidence import (
    validate_agent_evidence_envelope,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    trial_plan_hash,
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
    if cycle_binding is None and object_type not in {"evidence", "trial_plan"}:
        raise ValueError("research cycle object_type is invalid")
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
        return deepcopy(value)
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
