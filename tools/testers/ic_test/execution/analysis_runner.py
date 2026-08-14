"""Run one product-scoped Job's registered IC auxiliary analyses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tools.testers.ic_test.analysis_graph.runtime import (
    ICAnalysisResultStore,
    execute_ic_analysis_nodes,
)
from tools.testers.ic_test.configuration import CompiledICRunConfiguration

from .model import ICJobExecutionPlan
from .planner import validate_ic_job_plan


@dataclass(frozen=True, slots=True)
class ICJobAnalysisExecution:
    plan_ref: str
    executed_node_ids: tuple[str, ...]
    results: ICAnalysisResultStore


def execute_ic_job_analyses(
    configuration: CompiledICRunConfiguration,
    plan: ICJobExecutionPlan,
    core_outputs: Mapping[str, Mapping[str, Any]],
) -> ICJobAnalysisExecution:
    """Execute only the analysis nodes derived for one frozen Job plan."""

    validate_ic_job_plan(configuration, plan)
    expected_refs = set(plan.core_test_refs)
    actual_refs = set(core_outputs)
    if actual_refs != expected_refs:
        raise ValueError(
            "IC Job core outputs do not match the product-scoped Job plan: "
            f"missing={sorted(expected_refs - actual_refs)}, "
            f"unexpected={sorted(actual_refs - expected_refs)}"
        )
    cores = {
        core.core_test_ref: core for core in configuration.analysis_graph.core_tests
    }
    store = ICAnalysisResultStore()
    for core_ref in sorted(core_outputs):
        outputs = core_outputs[core_ref]
        if not isinstance(outputs, Mapping):
            raise ValueError(f"core outputs for {core_ref} must be an object")
        unknown = sorted(set(outputs) - cores[core_ref].output_kinds)
        if unknown:
            raise ValueError(
                f"core {core_ref} published unregistered output kinds: {unknown}"
            )
        for output_kind, value in outputs.items():
            store.publish(core_ref, output_kind, value)
    executed = execute_ic_analysis_nodes(
        configuration.analysis_graph,
        plan.analysis_node_ids,
        store,
    )
    return ICJobAnalysisExecution(plan.plan_ref, executed, store)


__all__ = ["ICJobAnalysisExecution", "execute_ic_job_analyses"]
