"""Serializable durable research-job records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .assurance import TerminalAssuranceSummary
from .states import JobStatus
from .subjects import job_subjects


@dataclass(frozen=True)
class SchedulingEntitlement:
    priority_class: str = "standard"
    weight: float = 1.0
    max_queue_delay_seconds: float = 300.0
    bypass_data_affinity: bool = False
    reserved_capacity_class: str = ""
    max_concurrency: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority_class": self.priority_class,
            "weight": self.weight,
            "max_queue_delay_seconds": self.max_queue_delay_seconds,
            "bypass_data_affinity": self.bypass_data_affinity,
            "reserved_capacity_class": self.reserved_capacity_class,
            "max_concurrency": self.max_concurrency,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "SchedulingEntitlement":
        value = value or {}
        return cls(
            priority_class=str(value.get("priority_class") or "standard"),
            weight=float(value.get("weight") or 1.0),
            max_queue_delay_seconds=float(value.get("max_queue_delay_seconds") or 300.0),
            bypass_data_affinity=bool(value.get("bypass_data_affinity")),
            reserved_capacity_class=str(value.get("reserved_capacity_class") or ""),
            max_concurrency=max(1, int(value.get("max_concurrency") or 1)),
        )


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    run_id: str
    owner: str
    workspace_id: str
    kind: str
    status: JobStatus
    job_role: str = "primary"
    parent_job_id: str = ""
    supplemental_kind: str = ""
    supplemental_identity: str = ""
    source_artifact_hash: str = ""
    retry_of: str = ""
    attempt: int = 1
    step_mode: bool = False
    retention_mode: str = "summary"
    deployment_id: str = ""
    service_port: int = 0
    source_revision: str = ""
    runner_path: str = ""
    job_spec: dict[str, Any] = field(default_factory=dict)
    job_spec_hash: str = ""
    run_spec_hash: str = ""
    worker_pid: int | None = None
    worker_exitcode: int | None = None
    cancel_requested_at: float | None = None
    cancel_reason: str = ""
    entitlement: SchedulingEntitlement = field(default_factory=SchedulingEntitlement)
    execution_plan: dict[str, Any] | None = None
    execution_plan_hash: str = ""
    plan_notices: list[dict[str, Any]] = field(default_factory=list)
    result_summary: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    terminal_assurance: TerminalAssuranceSummary | None = None
    created_at: float = 0.0
    planned_at: float | None = None
    approved_at: float | None = None
    queued_at: float | None = None
    started_at: float | None = None
    finished_at: float | None = None
    updated_at: float = 0.0

    def summary(self, *, pinned: bool = False) -> dict[str, Any]:
        task_name = ""
        acting_profile_ref = ""
        acting_profile_name = ""
        if isinstance(self.job_spec, dict):
            task_name = str(
                self.job_spec.get("task_name")
                or self.job_spec.get("name")
                or ""
            ).strip()
            acting_profile_ref = str(
                self.job_spec.get("acting_profile_ref") or ""
            ).strip()
            acting_profile_name = str(
                self.job_spec.get("acting_profile_name") or ""
            ).strip()
        run_spec = self.job_spec.get("run_spec") if isinstance(self.job_spec, dict) else None
        factor_source_policy = (
            dict(run_spec.get("factor_source_policy") or {})
            if isinstance(run_spec, dict)
            and isinstance(run_spec.get("factor_source_policy"), dict)
            else {"mode": "metadata_only"}
        )
        if factor_source_policy.get("mode") == "transient_run_source":
            from server.services.transient_factor_sources import scope_status

            factor_source_policy["scope_status"] = scope_status(
                str(self.job_spec.get("transient_factor_source_scope_id") or "")
            )
        strategy_source_policy = (
            dict(run_spec.get("strategy_source_policy") or {})
            if isinstance(run_spec, dict)
            and isinstance(run_spec.get("strategy_source_policy"), dict)
            else {"mode": "metadata_only"}
        )
        if strategy_source_policy.get("mode") == "transient_run_source":
            from server.services.transient_strategy_sources import scope_status

            strategy_source_policy["scope_status"] = scope_status(
                str(self.job_spec.get("transient_strategy_source_scope_id") or "")
            )
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "owner": self.owner,
            "workspace_id": self.workspace_id,
            "kind": self.kind,
            "job_role": self.job_role,
            "parent_job_id": self.parent_job_id,
            "supplemental_kind": self.supplemental_kind,
            "supplemental_identity": self.supplemental_identity,
            "source_artifact_hash": self.source_artifact_hash,
            "task_name": task_name,
            "acting_profile_ref": acting_profile_ref,
            "acting_profile_name": acting_profile_name,
            "execution_mode": "process",
            "status": self.status.value,
            "retry_of": self.retry_of,
            "attempt": self.attempt,
            "step_mode": self.step_mode,
            "retention_mode": self.retention_mode,
            "port": self.service_port,
            "output_requests": list(self.job_spec.get("output_requests") or ()),
            "source_revision": self.source_revision,
            "job_spec_hash": self.job_spec_hash,
            "run_spec_hash": self.run_spec_hash,
            "object_subjects": [
                {
                    "object_kind": item.object_kind,
                    "object_ref": item.object_ref,
                    "owner_ref": item.owner_ref,
                    "alias": item.alias,
                }
                for item in job_subjects(self.job_spec)
            ],
            "factor_source_policy": factor_source_policy,
            "strategy_specs": list(run_spec.get("strategy_plan") or run_spec.get("strategy_specs") or ()) if isinstance(run_spec, dict) else [],
            "strategy_source_policy": strategy_source_policy,
            "worker_pid": self.worker_pid,
            "worker_exitcode": self.worker_exitcode,
            "cancel_requested": self.cancel_requested_at is not None,
            "cancel_requested_at": self.cancel_requested_at,
            "cancel_reason": self.cancel_reason,
            "entitlement": self.entitlement.to_dict(),
            "execution_plan_hash": self.execution_plan_hash,
            "plan_notices": list(self.plan_notices),
            "has_result": self.result_summary is not None,
            "has_error": self.error is not None,
            "has_terminal_assurance": self.terminal_assurance is not None,
            "pinned": pinned,
            "created_at": self.created_at,
            "planned_at": self.planned_at,
            "approved_at": self.approved_at,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "updated_at": self.updated_at,
        }
