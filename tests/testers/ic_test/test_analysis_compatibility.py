from __future__ import annotations

from tools.testers.ic_test.analysis_graph import (
    ICAnalysisGraph,
    ICAnalysisNode,
    assess_analysis_attachment,
    list_analysis_attachment_candidates,
)
from tools.testers.ic_test.core import ICCoreTest


def _core(horizon: str, *, scope: str = "metals") -> ICCoreTest:
    return ICCoreTest(
        product_scope_ref=scope,
        factor_ref="factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        horizon=horizon,
        entry_delay_bars=0,
        method="rank",
        return_price_basis="next_open_to_open_adjusted",
    )


def test_candidate_list_explains_compatible_and_incompatible_analyses() -> None:
    core = _core("MIN5")
    graph = ICAnalysisGraph((core,))

    candidates = {
        item.analysis_type: item
        for item in list_analysis_attachment_candidates(
            graph, (core.core_test_ref,),
        )
    }

    assert candidates["rolling_ic_stability"].compatible is True
    assert candidates["forward_horizon_half_life"].compatible is False
    assert {
        issue.code
        for issue in candidates["forward_horizon_half_life"].issues
    } == {"target_count", "varying_axis"}


def test_candidate_list_understands_batch_map_each_selection() -> None:
    min5 = _core("MIN5")
    min10 = _core("MIN10")

    candidates = {
        item.analysis_type: item
        for item in list_analysis_attachment_candidates(
            ICAnalysisGraph((min5, min10)),
            (min5.core_test_ref, min10.core_test_ref),
        )
    }

    assert candidates["rolling_ic_stability"].compatible is True
    assert candidates["forward_horizon_half_life"].compatible is True


def test_combine_candidate_checks_same_and_varying_axes() -> None:
    min5 = _core("MIN5")
    min10 = _core("MIN10")
    energy = _core("MIN15", scope="energy")
    graph = ICAnalysisGraph((min5, min10, energy))

    accepted = assess_analysis_attachment(
        graph,
        "forward_horizon_half_life",
        (min5.core_test_ref, min10.core_test_ref),
    )
    rejected = assess_analysis_attachment(
        graph,
        "forward_horizon_half_life",
        (min5.core_test_ref, energy.core_test_ref),
    )

    assert accepted.compatible is True
    assert rejected.compatible is False
    assert [issue.code for issue in rejected.issues] == ["same_axis"]
    assert rejected.issues[0].details == {"axis": "product_scope_ref"}


def test_editing_an_existing_node_cannot_target_its_descendant() -> None:
    core = _core("MIN5")
    parent = ICAnalysisNode(
        "parent", "rolling_ic_stability", (core.core_test_ref,),
        {"rolling_windows": [{"unit": "signals", "value": 20}]},
    )
    descendant = ICAnalysisNode(
        "descendant", "period_diagnostics", (parent.node_id,), {},
    )
    graph = ICAnalysisGraph((core,), (parent, descendant))

    assessment = assess_analysis_attachment(
        graph,
        "rolling_ic_stability",
        (descendant.node_id,),
        editing_node_id=parent.node_id,
    )

    assert assessment.compatible is False
    assert "cycle" in {issue.code for issue in assessment.issues}


def test_compatibility_projection_is_structured_for_manifest_consumers() -> None:
    core = _core("MIN5")
    value = assess_analysis_attachment(
        ICAnalysisGraph((core,)),
        "forward_horizon_half_life",
        (core.core_test_ref,),
    ).to_dict()

    assert value["analysis_type"] == "forward_horizon_half_life"
    assert value["compatible"] is False
    assert value["target_refs"] == [core.core_test_ref]
    assert all(set(issue) == {"code", "message", "details"} for issue in value["issues"])
