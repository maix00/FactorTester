"""Freeze typed IC authoring objects into one immutable run configuration."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from tools.testers.ic_test.analysis_graph import (
    ICAnalysisGraph,
    apply_analysis_attachment,
    plan_analysis_attachment,
)
from tools.testers.ic_test.core import ICCoreTestBlock, expand_core_test_blocks

from ..horizon_resolution import ICHorizonOrigin, ResolvedICHorizon
from ..model import CompiledICRunConfiguration
from .configuration import ICRunAuthoringConfiguration


def freeze_ic_run_configuration(
    authoring: ICRunAuthoringConfiguration,
    *,
    factor_frequencies: Mapping[str, Any],
) -> CompiledICRunConfiguration:
    if not isinstance(authoring, ICRunAuthoringConfiguration):
        raise TypeError("authoring must be an ICRunAuthoringConfiguration")
    blocks: list[ICCoreTestBlock] = []
    resolutions: dict[
        str, dict[str, dict[str, list[ICHorizonOrigin]]]
    ] = defaultdict(dict)
    for request in authoring.core_tests:
        for factor_ref in request.factor_refs:
            entries = request.horizon.resolve_entries(
                factor_frequencies.get(factor_ref),
            )
            factor_resolutions = resolutions[request.request_ref].setdefault(
                factor_ref, {},
            )
            for entry in entries:
                origins = factor_resolutions.setdefault(
                    entry.physical_frequency,
                    [],
                )
                origins.extend(origin for origin in entry.origins if origin not in origins)
            blocks.append(ICCoreTestBlock(
                product_scope_refs=request.product_scope_refs,
                factor_refs=(factor_ref,),
                horizons=tuple(item.physical_frequency for item in entries),
                entry_delay_bars=request.entry_delay_bars,
                methods=request.methods,
                return_price_basis=request.return_price_basis,
            ))
    core_tests = expand_core_test_blocks(blocks)
    graph = ICAnalysisGraph(core_tests)
    for request in authoring.analyses:
        plan = plan_analysis_attachment(
            graph,
            request.analysis_type,
            request.target_refs,
            parameters=request.parameters,
        )
        if not plan.compatible:
            reasons = "; ".join(issue.reason_code for issue in plan.issues)
            raise ValueError(
                f"analysis attachment {request.analysis_type} is invalid: {reasons}"
            )
        graph = apply_analysis_attachment(graph, plan)
    executable_factors = tuple(sorted({item.factor_ref for item in core_tests}))
    subjects = authoring.factor_subject_refs or executable_factors
    return CompiledICRunConfiguration(
        authoring_core_tests=authoring.core_tests,
        resolved_horizons_by_request={
            request_ref: {
                factor_ref: tuple(
                    ResolvedICHorizon(frequency, tuple(origins))
                    for frequency, origins in values.items()
                )
                for factor_ref, values in sorted(factors.items())
            }
            for request_ref, factors in sorted(resolutions.items())
        },
        analysis_graph=graph,
        job_partitions={
            scope: tuple(
                item.core_test_ref
                for item in core_tests
                if item.product_scope_ref == scope
            )
            for scope in sorted({item.product_scope_ref for item in core_tests})
        },
        factor_subject_refs=subjects,
        output_requests=authoring.output_requests,
    )


__all__ = ["freeze_ic_run_configuration"]
