"""Compose the backend-owned IC core and auxiliary-analysis registry."""

from functools import lru_cache

from tools.testers.analysis_graph import AnalysisGraphDefinition, CoreTestDefinition
from tools.testers.ic_test.core import IC_CORE_AXES, IC_CORE_OUTPUT_KINDS

from .registration import builtin_ic_analyses, ic_core_axis_definitions


@lru_cache(maxsize=1)
def ic_analysis_graph_definition() -> AnalysisGraphDefinition:
    """Return the sole backend-owned IC analysis registry."""

    return AnalysisGraphDefinition(
        key="ic_analysis_graph",
        label="IC 核心测试与附加分析",
        core_test=CoreTestDefinition(
            label="核心 IC 测试",
            axes=IC_CORE_AXES,
            output_kinds=IC_CORE_OUTPUT_KINDS,
            axis_definitions=ic_core_axis_definitions(),
        ),
        analysis_types=builtin_ic_analyses(),
        authoring_contract={
            "schema_version": 1,
            "core_tests_key": "core_tests",
            "analyses_key": "analyses",
            "factor_subject_refs_key": "factor_subject_refs",
            "output_requests_key": "output_requests",
        },
    )


__all__ = ["ic_analysis_graph_definition"]
