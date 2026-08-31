from __future__ import annotations

import pandas as pd
import pytest

from tools.testers.ic_test.configuration import (
    ICAnalysisAttachmentRequest,
    ICCoreTestRequest,
    ICHorizonPolicy,
    ICRunAuthoringConfiguration,
    freeze_ic_run_configuration,
)
from tools.testers.ic_test.execution import execute_ic_job_analyses, plan_ic_jobs


FACTOR = "factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _configuration(*, with_analysis: bool):
    request = ICCoreTestRequest(
        product_scope_refs=("product-scope:metals",),
        factor_refs=(FACTOR,),
        horizon=ICHorizonPolicy.from_value({
            "sampling": "explicit",
            "bases": ["signal"],
            "multipliers": [5],
        }),
        entry_delay_bars=(0,),
        methods=("rank",),
        return_price_basis="next_open_to_open_adjusted",
    )
    provisional = freeze_ic_run_configuration(
        ICRunAuthoringConfiguration((request,)),
        factor_frequencies={FACTOR: "1m"},
    )
    attachments = ()
    if with_analysis:
        core_ref = provisional.analysis_graph.core_tests[0].core_test_ref
        attachments = (ICAnalysisAttachmentRequest(
            "ic_resample_stability",
            (core_ref,),
            {"sampling_intervals": [1, 2]},
        ),)
    return freeze_ic_run_configuration(
        ICRunAuthoringConfiguration(
            (request,),
            attachments,
            factor_subject_refs=(FACTOR,),
        ),
        factor_frequencies={FACTOR: "1m"},
    )


def test_job_executes_only_its_derived_analysis_subset() -> None:
    configuration = _configuration(with_analysis=True)
    plan = plan_ic_jobs(configuration)[0]
    core_ref = plan.core_test_refs[0]
    execution = execute_ic_job_analyses(
        configuration,
        plan,
        {core_ref: {"ic_series": pd.Series([0.1, 0.2, 0.3])}},
    )

    assert execution.plan_ref == plan.plan_ref
    assert execution.executed_node_ids == plan.analysis_node_ids
    assert execution.results.require(
        plan.analysis_node_ids[0],
        "ic_resample_statistics",
    ).rows[0].n == 3


def test_job_rejects_core_outputs_from_another_product_partition() -> None:
    configuration = _configuration(with_analysis=False)
    plan = plan_ic_jobs(configuration)[0]

    with pytest.raises(ValueError, match="unexpected=.*other"):
        execute_ic_job_analyses(
            configuration,
            plan,
            {"ic-core:v1:other": {"ic_series": pd.Series([0.1])}},
        )
