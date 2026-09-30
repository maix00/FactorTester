"""Immutable research runs created from canonical configurations."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any

import orjson

import settings as Settings
from server.services import direct_trial_plan_registry
from server.services.research_run_schema import (
    ensure_schema as ensure_research_run_schema,
)
from server.services.research_run_identity import RUN_SPEC_VERSION, hash_run_spec
from server.services.research_graph.trial_plan.binding import (
    validate_branch_binding,
)
from server.services.research_sample_exposure import (
    PROTECTED_SAMPLE_ROLES,
    validate_protected_sample_exposure,
)
from server.services.research_run_inputs import (
    derive_sample_identity_or_none,
    normalize_trial_binding,
    persisted_sample_identity,
)
from server.services.research_run_report_binding import (
    normalize_report_binding,
)
from server.services.research_report_presentations import (
    run_spec_presentation,
)
from server.services.research_run_projections import (
    project_job_evidence,
    project_run,
)
from tools.data.sqlite.db import connect_sqlite


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
    report_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_spec_version = int(run_spec.get("run_spec_version") or 0)
    if run_spec_version != RUN_SPEC_VERSION:
        raise ValueError("unsupported run_spec_version")
    run_id = uuid.uuid4().hex
    # Persist the schema's insertion order for human inspection.  The hash
    # function canonicalizes a temporary encoding independently and must not
    # rewrite the displayed/downloaded RunSpec.
    raw = orjson.dumps(run_spec)
    run_spec_hash = hash_run_spec(run_spec)
    sample_identity = derive_sample_identity_or_none(run_spec)
    binding = normalize_trial_binding(
        trial_binding,
        run_spec_hash=run_spec_hash,
        sample_identity=sample_identity,
    )
    if (
        binding is not None
        and binding.get("binding_origin") == "agent_direct"
        and direct_trial_plan_registry.load(
            owner=owner,
            trial_plan_hash=str(binding["trial_plan_hash"]),
        ) is None
    ):
        raise ValueError("direct TrialPlan is not registered for this user")
    persisted_sample = persisted_sample_identity(
        binding=binding,
        sample_identity=sample_identity,
    )
    created_at = time.time()
    with _connect() as conn:
        if binding is not None:
            is_protected_sample = (
                str(binding.get("trial_stage") or "")
                in PROTECTED_SAMPLE_ROLES
            )
            if int(binding["trial_plan_schema_version"]) == 5 or is_protected_sample:
                conn.execute("BEGIN IMMEDIATE")
            if is_protected_sample:
                validate_protected_sample_exposure(
                    conn,
                    owner=owner,
                    trial_plan_hash=str(binding["trial_plan_hash"]),
                    trial_plan_schema_version=int(
                        binding["trial_plan_schema_version"]
                    ),
                    trial_stage=str(binding["trial_stage"]),
                    sample_identity_hash=str(
                        persisted_sample["sample_identity_hash"]
                    ),
                    sample_start=str(persisted_sample["sample_start"]),
                    sample_end=str(persisted_sample["sample_end"]),
                    sample_universe_members_json=str(
                        persisted_sample["sample_universe_members_json"]
                    ),
                )
            if binding.get("binding_origin") == "research_graph":
                action_snapshot = validate_branch_binding(
                    conn,
                    owner=owner,
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
                    action_input_hash=str(
                        binding.get("action_input_hash") or ""
                    ),
                    expected_checkpoint_hash=str(
                        binding.get("expected_checkpoint_hash") or ""
                    ),
                    expected_latest_trace_id=str(
                        binding.get("expected_latest_trace_id") or ""
                    ),
                    trial_plan=binding.get("trial_plan"),
                )
                binding.update(action_snapshot)
        persisted_report_binding = normalize_report_binding(
            report_binding,
            trial_binding=binding,
            branch_snapshot=binding or {},
        )
        conn.execute(
            """
            INSERT INTO research_runs (
                run_id, owner, workspace_id, configuration_id,
                configuration_revision, kind, run_spec_version,
                run_spec_hash, run_spec_json, decision_contract_hash,
                methodology_hash, trial_plan_id, trial_plan_hash,
                trial_plan_schema_version, trial_plan_version,
                trial_role, trial_stage, trial_stage_id, comparison_id,
                graph_instance_id, graph_branch_id, graph_execution_node,
                sample_ref, sample_hash,
                sample_identity_hash, sample_start, sample_end,
                sample_universe_hash, sample_universe_members_json,
                sample_design_context_hash,
                sample_identity_assurance,
                evidence_action_id, evidence_action_binding_hash,
                evidence_action_binding_json,
                report_binding_json,
                created_at
            ) VALUES (
                ?, ?, ?, ?, ?, 'factor_research',
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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
                str((binding or {}).get("execution_node") or ""),
                str((binding or {}).get("sample_ref") or ""),
                str((binding or {}).get("sample_hash") or ""),
                persisted_sample["sample_identity_hash"],
                persisted_sample["sample_start"],
                persisted_sample["sample_end"],
                persisted_sample["sample_universe_hash"],
                persisted_sample["sample_universe_members_json"],
                persisted_sample["sample_design_context_hash"],
                persisted_sample["sample_identity_assurance"],
                str((binding or {}).get("evidence_action_id") or ""),
                str(
                    (binding or {}).get("evidence_action_binding_hash") or ""
                ),
                str(
                    (binding or {}).get("evidence_action_binding_json") or "{}"
                ),
                orjson.dumps(
                    persisted_report_binding or {},
                    option=orjson.OPT_SORT_KEYS,
                ).decode(),
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
        "graph_execution_node": str(
            persisted_binding.get("execution_node") or ""
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
        "report_binding": deepcopy(persisted_report_binding),
        **persisted_sample,
        "created_at": created_at,
    }


def load_run(*, run_id: str, owner: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM research_runs WHERE run_id=? AND owner=?", (run_id, owner)
        ).fetchone()
    if row is None:
        return None
    return project_run(row)


def load_run_spec(
    *, run_spec_hash: str, owner: str,
) -> dict[str, Any] | None:
    """Return one owner-scoped immutable RunSpec by its content hash."""
    digest = str(run_spec_hash).removeprefix("sha256:")
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("RunSpec hash must be 64 lowercase hexadecimal characters")
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM research_runs
            WHERE run_spec_hash=? AND owner=?
            ORDER BY created_at, run_id
            LIMIT 1
            """,
            (digest, owner),
        ).fetchone()
    if row is None:
        return None
    run = project_run(row)
    if hash_run_spec(run["run_spec"]) != digest:
        raise ValueError("stored RunSpec content does not match its hash")
    presentation = run_spec_presentation(
        run["run_spec"],
        run_spec_hash=digest,
        run_id=str(run["run_id"]),
        sample_identity={
            "sample_start": run.get("sample_start"),
            "sample_end": run.get("sample_end"),
            "sample_hash": run.get("sample_hash"),
        },
    )
    return {
        "run_spec_hash": digest,
        "run_spec_version": int(run["run_spec_version"]),
        "run_spec": deepcopy(run["run_spec"]),
        "configuration_id": str(run["configuration_id"]),
        "configuration_revision": int(run["configuration_revision"]),
        "alias_zh": str(presentation["alias_zh"]),
        "summary_zh": str(presentation["summary_zh"]),
        "complete_parameters_json": str(
            presentation["complete_parameters_json"]
        ),
    }


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
