"""Immutable research runs created from canonical configurations."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services.research_run_schema import (
    ensure_schema as ensure_research_run_schema,
)
from server.services.research_graph.trial_plan.binding import validate_branch_binding
from server.services.research_run_inputs import (
    derive_sample_identity_or_none,
    normalize_trial_binding,
    persisted_sample_identity,
)
from server.services.research_run_projections import (
    project_job_evidence,
    project_run,
)
from tools.data.sqlite.db import connect_sqlite


RUN_SPEC_VERSION = 2
_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


def _ensure_schema(conn) -> None:
    ensure_research_run_schema(conn)


def _connect() -> sqlite3.Connection:
    path = str(Path(Settings.CACHE_DB_PATH))
    conn = connect_sqlite(Settings.CACHE_DB_PATH)
    if path not in _SCHEMA_READY_PATHS:
        with _SCHEMA_LOCK:
            if path not in _SCHEMA_READY_PATHS:
                try:
                    _ensure_schema(conn)
                except Exception:
                    conn.close()
                    raise
                _SCHEMA_READY_PATHS.add(path)
    return conn


def ensure_schema() -> None:
    with _connect():
        pass


def create_run(
    *, owner: str, workspace_id: str, configuration_id: str,
    configuration_revision: int, run_spec: dict[str, Any],
    trial_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Historical internal callers created v1 specs before the body declared
    # its version. Preserve those records; HTTP preview/submit always declares
    # the current version explicitly.
    run_spec_version = int(run_spec.get("run_spec_version") or 1)
    if run_spec_version not in {1, RUN_SPEC_VERSION}:
        raise ValueError("unsupported run_spec_version")
    run_id = uuid.uuid4().hex
    raw = orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
    run_spec_hash = hash_run_spec(run_spec)
    sample_identity = derive_sample_identity_or_none(run_spec)
    binding = normalize_trial_binding(
        trial_binding,
        run_spec_hash=run_spec_hash,
        sample_identity=sample_identity,
    )
    persisted_sample = persisted_sample_identity(
        binding=binding,
        sample_identity=sample_identity,
    )
    created_at = time.time()
    with _connect() as conn:
        if binding is not None:
            if int(binding["trial_plan_schema_version"]) == 5:
                conn.execute("BEGIN IMMEDIATE")
            action_snapshot = validate_branch_binding(
                conn,
                owner=owner,
                workspace_id=workspace_id,
                instance_id=str(binding["instance_id"]),
                branch_id=str(binding["branch_id"]),
                trial_plan_hash=binding["trial_plan_hash"],
                trial_plan_schema_version=int(
                    binding["trial_plan_schema_version"]
                ),
                trial_plan_version=int(binding["trial_plan_version"]),
                trial_role=str(binding["trial_role"]),
                trial_stage=str(binding["trial_stage"]),
                sample_identity_hash=str(
                    binding["sample_identity_hash"]
                ),
                sample_start=str(binding["sample_start"]),
                sample_end=str(binding["sample_end"]),
                sample_universe_hash=str(
                    binding["sample_universe_hash"]
                ),
                run_spec_hash=run_spec_hash,
                evidence_action_id=str(
                    binding.get("evidence_action_id") or ""
                ),
                action_input_hash=str(binding.get("action_input_hash") or ""),
                expected_checkpoint_hash=str(
                    binding.get("expected_checkpoint_hash") or ""
                ),
                expected_latest_trace_id=str(
                    binding.get("expected_latest_trace_id") or ""
                ),
                trial_plan=binding.get("trial_plan"),
            )
            binding.update(action_snapshot)
        conn.execute(
            """
            INSERT INTO research_runs (
                run_id, owner, workspace_id, configuration_id,
                configuration_revision, kind, run_spec_version,
                run_spec_hash, run_spec_json, decision_contract_hash,
                methodology_hash, trial_plan_id, trial_plan_hash,
                trial_plan_schema_version, trial_plan_version,
                trial_role, trial_stage, trial_stage_id, comparison_id,
                graph_instance_id, graph_branch_id, sample_ref, sample_hash,
                sample_identity_hash, sample_start, sample_end,
                sample_universe_hash, sample_design_context_hash,
                sample_identity_assurance,
                evidence_action_id, evidence_action_binding_hash,
                evidence_action_binding_json,
                created_at
            ) VALUES (
                ?, ?, ?, ?, ?, 'factor_research',
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                run_id, owner, workspace_id, configuration_id,
                int(configuration_revision), run_spec_version,
                run_spec_hash, raw.decode(),
                str(
                    (binding or {}).get("decision_contract_hash") or ""
                ),
                str((binding or {}).get("methodology_hash") or ""),
                str((binding or {}).get("trial_plan_id") or ""),
                str((binding or {}).get("trial_plan_hash") or ""),
                int((binding or {}).get("trial_plan_schema_version") or 0),
                int((binding or {}).get("trial_plan_version") or 0),
                str((binding or {}).get("trial_role") or ""),
                str((binding or {}).get("trial_stage") or ""),
                str((binding or {}).get("action_stage_id") or ""),
                str((binding or {}).get("comparison_id") or ""),
                str((binding or {}).get("instance_id") or ""),
                str((binding or {}).get("branch_id") or ""),
                str((binding or {}).get("sample_ref") or ""),
                str((binding or {}).get("sample_hash") or ""),
                persisted_sample["sample_identity_hash"],
                persisted_sample["sample_start"],
                persisted_sample["sample_end"],
                persisted_sample["sample_universe_hash"],
                persisted_sample["sample_design_context_hash"],
                persisted_sample["sample_identity_assurance"],
                str((binding or {}).get("evidence_action_id") or ""),
                str(
                    (binding or {}).get("evidence_action_binding_hash") or ""
                ),
                str(
                    (binding or {}).get("evidence_action_binding_json") or "{}"
                ),
                created_at,
            ),
        )
    persisted_binding = dict(binding or {})
    return {
        "run_id": run_id,
        "owner": owner,
        "workspace_id": workspace_id,
        "configuration_id": configuration_id,
        "configuration_revision": int(configuration_revision),
        "kind": "factor_research",
        "run_spec_version": run_spec_version,
        "run_spec_hash": run_spec_hash,
        "run_spec": deepcopy(run_spec),
        "decision_contract_hash": str(
            persisted_binding.get("decision_contract_hash") or ""
        ),
        "methodology_hash": str(
            persisted_binding.get("methodology_hash") or ""
        ),
        "trial_plan_id": str(
            persisted_binding.get("trial_plan_id") or ""
        ),
        "trial_plan_hash": str(
            persisted_binding.get("trial_plan_hash") or ""
        ),
        "trial_plan_schema_version": int(
            persisted_binding.get("trial_plan_schema_version") or 0
        ),
        "trial_plan_version": int(
            persisted_binding.get("trial_plan_version") or 0
        ),
        "trial_role": str(persisted_binding.get("trial_role") or ""),
        "trial_stage": str(persisted_binding.get("trial_stage") or ""),
        "trial_stage_id": str(
            persisted_binding.get("action_stage_id") or ""
        ),
        "comparison_id": str(
            persisted_binding.get("comparison_id") or ""
        ),
        "graph_instance_id": str(
            persisted_binding.get("instance_id") or ""
        ),
        "graph_branch_id": str(
            persisted_binding.get("branch_id") or ""
        ),
        "sample_ref": str(persisted_binding.get("sample_ref") or ""),
        "sample_hash": str(persisted_binding.get("sample_hash") or ""),
        "evidence_action_id": str(
            persisted_binding.get("evidence_action_id") or ""
        ),
        "evidence_action_binding_hash": str(
            persisted_binding.get("evidence_action_binding_hash") or ""
        ),
        "evidence_action_binding": (
            orjson.loads(
                str(
                    persisted_binding.get("evidence_action_binding_json")
                    or "{}"
                )
            )
            or None
        ),
        **persisted_sample,
        "created_at": created_at,
    }


def hash_run_spec(run_spec: dict[str, Any]) -> str:
    """Return the canonical immutable identity used by ResearchRun."""
    return hashlib.sha256(
        orjson.dumps(run_spec, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def load_run(*, run_id: str, owner: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM research_runs WHERE run_id=? AND owner=?", (run_id, owner)
        ).fetchone()
    if row is None:
        return None
    return project_run(row)


def load_job_trial_binding(
    *,
    job_id: str,
    owner: str,
) -> dict[str, Any] | None:
    """Project a JobAttempt's immutable binding from its owning ResearchRun."""
    projection = load_job_evidence_projection(job_id=job_id, owner=owner)
    return (
        dict(projection["trial_binding"])
        if projection is not None
        else None
    )


def load_job_evidence_projection(
    *,
    job_id: str,
    owner: str,
) -> dict[str, Any] | None:
    """Load one JobAttempt's trial binding and immutable evidence identity."""
    with _connect() as conn:
        return project_job_evidence(conn, job_id=job_id, owner=owner)
