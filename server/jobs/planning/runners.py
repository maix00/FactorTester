"""Importable worker runners that derive compact plans from frozen job specs."""

from __future__ import annotations

from typing import Any


def plan_job(payload: dict[str, Any], sink: Any, cancel_event: Any) -> None:
    """Validate a frozen job spec and emit a bounded execution plan."""
    spec = payload.get("job_spec")
    if not isinstance(spec, dict):
        raise ValueError("job_spec must be an object")
    if cancel_event.is_set():
        sink.emit_error("planning cancelled", cancelled=True)
        return
    runner_path = str(payload.get("runner_path") or "").strip()
    if not runner_path:
        raise ValueError("runner_path is required")
    from server.modules.shared.factor_param_resolver import (
        register_factor_param_resolver_for_user,
    )
    from server.services.factor_registry import transient_factor_source_scope

    owner = str(spec.get("_owner") or payload.get("_owner") or "").strip()
    if owner:
        run_spec = spec.get("run_spec") or spec
        frozen_factors = (run_spec.get("configuration") or {}).get(
            "shared", {},
        ).get("factors") or spec.get("factors") or []
        register_factor_param_resolver_for_user(owner, frozen_factors)
    from server.modules.single_factor_test.planning import build_execution_plan

    with transient_factor_source_scope(
        str(payload.get("transient_factor_source_scope_id") or ""),
        owner=owner,
    ):
        plan = build_execution_plan(str(payload.get("kind") or ""), spec)
    sink.emit_plan({
        "success": True,
        "plan": plan,
        "notices": list(plan.get("notices") or []),
        "requires_confirmation": bool(plan.get("requires_confirmation")),
    })
