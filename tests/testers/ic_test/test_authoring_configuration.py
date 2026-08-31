from __future__ import annotations

import pytest

from tools.testers.ic_test.configuration import (
    ICAnalysisAttachmentRequest,
    ICCoreTestRequest,
    ICRunAuthoringConfiguration,
    freeze_ic_run_configuration,
)


ROC = "factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SGCCS = "factor:v2:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _authoring() -> ICRunAuthoringConfiguration:
    return ICRunAuthoringConfiguration(
        core_tests=(ICCoreTestRequest(
            product_scope_refs=("night", "day"),
            factor_refs=(ROC, SGCCS),
            horizon={
                "sampling": "explicit",
                "bases": ["signal"],
                "multipliers": [1, 3],
            },
            entry_delay_bars=(0,),
            methods=("rank",),
            return_price_basis="next_open_to_open_adjusted",
        ),),
        output_requests=("ic_statistics", "ic_series"),
    )


def test_typed_authoring_freezes_multiplier_horizons_per_factor() -> None:
    frozen = freeze_ic_run_configuration(
        _authoring(), factor_frequencies={ROC: "1m", SGCCS: "5m"},
    )

    assert {
        item.horizon for item in frozen.analysis_graph.core_tests
        if item.factor_ref == ROC
    } == {"MIN1", "MIN3"}
    assert {
        item.horizon for item in frozen.analysis_graph.core_tests
        if item.factor_ref == SGCCS
    } == {"MIN5", "MIN15"}
    assert frozen.authoring_core_tests[0].horizon.to_dict() == {
        "mode": "explicit",
        "bases": ["signal"],
        "multipliers": [1, 3],
    }


def test_typed_authoring_attaches_registered_analysis_to_exact_targets() -> None:
    baseline = freeze_ic_run_configuration(
        _authoring(), factor_frequencies={ROC: "1m", SGCCS: "5m"},
    )
    target = baseline.analysis_graph.core_tests[0].core_test_ref
    authoring = ICRunAuthoringConfiguration(
        core_tests=_authoring().core_tests,
        analyses=(ICAnalysisAttachmentRequest(
            analysis_type="rolling_ic_stability",
            target_refs=(target,),
            parameters={"rolling_windows": [40]},
        ),),
    )

    frozen = freeze_ic_run_configuration(
        authoring, factor_frequencies={ROC: "1m", SGCCS: "5m"},
    )

    assert len(frozen.analysis_graph.analyses) == 1
    assert frozen.analysis_graph.analyses[0].target_refs == (target,)
    assert frozen.analysis_graph.analyses[0].parameters == {
        "rolling_windows": [{"unit": "signals", "value": 40}],
    }


def test_normal_freezer_rejects_flat_settings_instead_of_migrating_them() -> None:
    with pytest.raises(TypeError, match="ICRunAuthoringConfiguration"):
        freeze_ic_run_configuration(
            {"rolling_window": 20}, factor_frequencies={},
        )


def test_authoring_round_trip_preserves_relative_horizon_and_not_ui_state() -> None:
    authoring = _authoring()

    payload = authoring.to_dict(include_refs=False)
    restored = ICRunAuthoringConfiguration.from_dict(payload)

    assert restored == authoring
    assert "request_ref" not in payload["core_tests"][0]
    assert "expanded" not in payload
    assert "pivot" not in payload


def test_authoring_core_request_order_and_duplicates_do_not_change_identity() -> None:
    first = _authoring().core_tests[0]
    second = ICCoreTestRequest(
        product_scope_refs=("day",),
        factor_refs=(ROC,),
        horizon={"sampling": "explicit", "bases": ["DAY1"], "multipliers": [2]},
        entry_delay_bars=(1,),
        methods=("pearson",),
        return_price_basis="next_close_to_close_adjusted",
    )
    left = ICRunAuthoringConfiguration(core_tests=(first, second))
    right = ICRunAuthoringConfiguration(core_tests=(second, first, second))

    assert left == right
    assert left.to_dict() == right.to_dict()


def test_schema2_grouped_payload_maps_each_group_to_one_typed_core() -> None:
    payload = {
        "schema_version": 2,
        "configuration_groups": [{
            "config_group_id": "g-day",
            "factor_ref": "factor:v2:ddddddddddddddddddddddddddddddddddddddddddd",
            "product_scope_ref": "product-group:day",
            "entry_delay_bars": 2,
            "horizon": {"sampling": "scale_aware"},
            "methods": ["rank"],
            "return_price_basis": "next_open_to_open_adjusted",
        }],
    }
    authoring = ICRunAuthoringConfiguration.from_dict(payload)
    assert len(authoring.core_tests) == 1
    assert authoring.core_tests[0].product_scope_refs == ("product-group:day",)
    assert authoring.core_tests[0].entry_delay_bars == (2,)


def test_schema2_grouped_payload_rejects_more_than_one_slice1_group() -> None:
    payload = {"schema_version": 2, "configuration_groups": [
        {"config_group_id": "first", "factor_ref": "factor:v2:Wroo2lwG5LBiImordFdeS5OTS_IAfxFmLCZUzPgJZe4", "product_scope_ref": "s", "entry_delay_bars": 0, "horizon": {"sampling": "scale_aware"}, "methods": ["rank"], "return_price_basis": "x"},
        {"config_group_id": "second", "factor_ref": "factor:v2:n6065XCpFt8yYTj9iGHCdrs7ZSKvjHRedB33HumEd5w", "product_scope_ref": "s", "entry_delay_bars": 1, "horizon": {"sampling": "scale_aware"}, "methods": ["rank"], "return_price_basis": "x"},
    ]}
    with pytest.raises(ValueError, match="exactly one"):
        ICRunAuthoringConfiguration.from_dict(payload)
