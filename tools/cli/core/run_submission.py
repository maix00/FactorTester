"""Canonical CLI construction of preview and submission Run requests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def build_run_request(
    *,
    analyses: tuple[str, ...],
    retain_full: bool,
    step_mode: bool,
    configuration_snapshot_id: str,
    configuration_snapshot_revision: int | None,
    flow_profile: bool,
    flow_profile_min_ms: float,
    margin_execution_profile: bool,
    profile_factor_worktree: Path | None,
    factor_set_refs: tuple[str, ...],
    strategy_spec_paths: tuple[Path, ...],
    profile_strategy_worktree: Path | None,
    run_input_specs: tuple[str, ...],
    output_requests: tuple[str, ...],
    load_factor_sources: Callable[[Path], list[dict[str, Any]]],
    load_factor_sets: Callable[[tuple[str, ...]], list[dict[str, Any]]],
    load_strategy_specs: Callable[[tuple[Path, ...]], list[dict[str, Any]]],
    load_strategy_bundle: Callable[[Path], list[dict[str, Any]]],
    load_run_inputs: Callable[..., list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build the common immutable request shared by preview and submit."""
    if configuration_snapshot_revision is not None and not configuration_snapshot_id:
        raise ValueError(
            "configuration snapshot revision requires a snapshot id"
        )
    if configuration_snapshot_id and configuration_snapshot_revision is None:
        raise ValueError(
            "configuration snapshot id requires its frozen revision"
        )
    request: dict[str, Any] = {
        "analyses": list(analyses),
        "retention_mode": "full" if retain_full else "summary",
        "step_mode": step_mode,
    }
    if configuration_snapshot_id:
        request.update({
            "configuration_snapshot_id": configuration_snapshot_id,
            "configuration_snapshot_revision": configuration_snapshot_revision,
        })
    if flow_profile:
        request["performance_profile"] = {
            "kind": "cumulative_flow",
            "min_total_ms": flow_profile_min_ms,
        }
    if margin_execution_profile:
        request["margin_execution_profile"] = {"kind": "cumulative"}
    if profile_factor_worktree is not None:
        request["transient_factor_sources"] = load_factor_sources(
            profile_factor_worktree
        )
    factor_sets = load_factor_sets(factor_set_refs)
    if factor_sets:
        request["factor_subject_descriptors"] = factor_sets
    strategy_specs = load_strategy_specs(strategy_spec_paths)
    if strategy_specs:
        request["strategy_specs"] = strategy_specs
    if profile_strategy_worktree is not None:
        request["transient_strategy_sources"] = load_strategy_bundle(
            profile_strategy_worktree
        )
    run_inputs = load_run_inputs(run_input_specs, analyses=analyses)
    if run_inputs:
        request["run_input_dependencies"] = run_inputs
    if output_requests:
        request["output_requests"] = list(output_requests)
    return request
