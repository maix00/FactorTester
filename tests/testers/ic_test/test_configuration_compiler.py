from __future__ import annotations

import pytest

from tools.testers.ic_test.configuration import (
    CompiledICRunConfiguration,
    freeze_ic_run_configuration,
    migrate_flat_ic_settings,
)


ROC = "factor:v1:profile-maxa:path:roc:commit:blob"
SGCCS = "factor:v1:profile-maxa:path:sgccs:commit:blob"
MOMENTUM_SET = "factor-set:v1:profile-maxa:path:momentum:commit:blob"


def _settings(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "factor_selections": [
            {"factor_ref": ROC, "factor_alias": "ROC|N:20d|$F:1m"},
            {"factor_ref": SGCCS, "factor_alias": "SgCCS|N:20d|$F:5m"},
        ],
        "product_path_selections": [
            {"product_path_selection_id": "night"},
            {"product_path_selection_id": "day"},
        ],
        "forward_return_horizons": {"sampling": "scale_aware"},
        "ic_lags": [1, 0],
        "ic_correlation": "both",
        "return_price_basis": "next_open_to_open_adjusted",
        "ic_decay_lags": [5, 1],
        "rolling_window": 20,
        "quantile_portfolio_statistics": {"enabled": False},
    }
    values.update(overrides)
    return values


def _compile(**overrides: object):
    return _migrate_and_freeze(
        _settings(**overrides), {ROC: "1m", SGCCS: "5m"},
    )


def _migrate_and_freeze(
    settings,
    frequencies,
    *,
    factor_set_members=None,
    output_requests=(),
):
    authoring = migrate_flat_ic_settings(
        settings,
        factor_frequencies=frequencies,
        factor_set_members=factor_set_members,
        output_requests=output_requests,
    )
    return freeze_ic_run_configuration(
        authoring, factor_frequencies=frequencies,
    )


def test_compiler_expands_methods_delays_and_factor_specific_horizons() -> None:
    compiled = _compile()
    cores = compiled.analysis_graph.core_tests

    assert {item.product_scope_ref for item in cores} == {"day", "night"}
    assert {item.method for item in cores} == {"rank", "pearson"}
    assert {item.entry_delay_bars for item in cores} == {0, 1}
    assert "DAY1" in {
        item.horizon for item in cores if item.factor_ref == ROC
    }
    assert any(
        item.factor_ref == ROC and item.horizon == "MIN1" for item in cores
    )
    assert any(
        item.factor_ref == SGCCS and item.horizon == "MIN5" for item in cores
    )
    assert set(compiled.job_partitions) == {"day", "night"}
    assert compiled.resolved_horizons_by_request[compiled.authoring_core_tests[0].request_ref][ROC][0].to_dict() == {
        "physical_frequency": "MIN1",
        "origins": [{"base": "signal", "multiplier": 1}],
    }
    assert compiled.resolved_horizons_by_request[compiled.authoring_core_tests[0].request_ref][SGCCS][0].to_dict() == {
        "physical_frequency": "MIN5",
        "origins": [{"base": "signal", "multiplier": 1}],
    }


def test_compiler_identity_uses_method_return_basis_and_analysis_parameters() -> None:
    baseline = _compile()
    pearson = _compile(ic_correlation="pearson")
    close = _compile(return_price_basis="next_close_to_close_adjusted")
    wider = _compile(rolling_window=60)

    assert len({
        baseline.configuration_ref,
        pearson.configuration_ref,
        close.configuration_ref,
        wider.configuration_ref,
    }) == 4


def test_flat_analysis_fields_compile_to_their_real_execution_targets() -> None:
    settings = _settings(
        factor_selections=[_settings()["factor_selections"][0]],
        product_path_selections=[{"product_path_selection_id": "day"}],
        forward_return_horizons={
            "sampling": "explicit", "bases": ["signal"], "multipliers": [1, 2],
        },
        ic_decay_lags=[5, 1],
        rolling_windows={"signal_counts": [60, 20]},
        rolling_window=None,
        ic_periods=["day", "week"],
        quantile_portfolio_statistics={
            "enabled": True, "group_count": 5, "modes": ["no_fee"],
        },
    )
    compiled = _migrate_and_freeze(
        settings, {ROC: "1m"},
    )
    by_type: dict[str, list] = {}
    for node in compiled.analysis_graph.analyses:
        by_type.setdefault(node.analysis_type, []).append(node)

    assert len(compiled.analysis_graph.core_tests) == 8
    assert len(by_type["rolling_ic_stability"]) == 8
    assert len(by_type["quantile_portfolio_statistics"]) == 8
    assert len(by_type["ic_resample_stability"]) == 2
    assert len(by_type["period_diagnostics"]) == 2
    assert len(by_type["ic_autocorrelation"]) == 2
    assert len(by_type["forward_horizon_half_life"]) == 4
    assert {
        tuple(node.parameters["sampling_intervals"])
        for node in by_type["ic_resample_stability"]
    } == {(1, 5)}
    assert {
        tuple(item["value"] for item in node.parameters["rolling_windows"])
        for node in by_type["rolling_ic_stability"]
    } == {(20, 60)}
    assert all(len(node.target_refs) == 2 for node in by_type[
        "forward_horizon_half_life"
    ])
    compiled.analysis_graph.validate()


def test_output_requests_are_frozen_but_not_analysis_nodes() -> None:
    settings = _settings()
    plain = _migrate_and_freeze(
        settings, {ROC: "1m", SGCCS: "5m"},
    )
    reports = _migrate_and_freeze(
        settings,
        {ROC: "1m", SGCCS: "5m"},
        output_requests=("ic_statistics", "ic_series", "ic_statistics"),
    )

    assert plain.analysis_graph.to_dict() == reports.analysis_graph.to_dict()
    assert reports.output_requests == ("ic_series", "ic_statistics")
    assert plain.configuration_ref != reports.configuration_ref
    assert all(
        node.analysis_type not in reports.output_requests
        for node in reports.analysis_graph.analyses
    )


def test_compiler_is_order_independent_and_does_not_persist_flat_fields() -> None:
    left = _compile()
    right = _migrate_and_freeze(
        _settings(
            factor_selections=list(reversed(_settings()["factor_selections"])),
            product_path_selections=list(
                reversed(_settings()["product_path_selections"]),
            ),
            ic_lags=[1, 0, 1],
        ),
        {SGCCS: "5m", ROC: "1m"},
    )

    assert left.configuration_ref == right.configuration_ref
    payload = left.to_dict()
    assert "factor_selections" not in payload
    assert "ic_decay_lags" not in payload
    assert "rolling_window" not in payload


def test_compiler_rejects_unfrozen_factors_and_false_cross_section_capabilities() -> None:
    assert _compile(min_cross_section_count=5).analysis_graph.core_tests
    with pytest.raises(ValueError, match="frozen factor_ref"):
        migrate_flat_ic_settings(
            _settings(factor_selections=[{"factor_alias": "ROC"}]),
            factor_frequencies={ROC: "1m"},
        )
    with pytest.raises(ValueError, match="group_adjust is not executable"):
        _compile(group_adjust="on")
    with pytest.raises(ValueError, match="by_group is not executable"):
        _compile(by_group="on")
    with pytest.raises(ValueError, match="min_cross_section_count is not executable"):
        _compile(min_cross_section_count=10)


def test_frozen_configuration_round_trips_with_typed_authoring_fields() -> None:
    compiled = _compile()

    restored = CompiledICRunConfiguration.from_dict(compiled.to_dict())

    assert restored == compiled
    assert restored.configuration_ref == compiled.configuration_ref


def test_frozen_configuration_rejects_tampered_core_identity() -> None:
    payload = _compile().to_dict()
    payload["analysis_graph"]["core_tests"][0]["horizon"] = "DAY99"

    with pytest.raises(ValueError, match="core_test_ref does not match"):
        CompiledICRunConfiguration.from_dict(payload)


def test_frozen_configuration_rejects_incomplete_job_partitions() -> None:
    payload = _compile().to_dict()
    first_partition = next(iter(payload["job_partitions"].values()))
    first_partition.pop()

    with pytest.raises(ValueError, match="job partitions must contain every core test"):
        CompiledICRunConfiguration.from_dict(payload)


def test_frozen_configuration_rejects_horizon_resolution_that_disagrees_with_cores() -> None:
    payload = _compile().to_dict()
    request_ref = payload["authoring_core_tests"][0]["request_ref"]
    payload["resolved_horizons_by_request"][request_ref][ROC][0][
        "physical_frequency"
    ] = "DAY99"

    with pytest.raises(ValueError, match="resolved horizons do not match"):
        CompiledICRunConfiguration.from_dict(payload)


def test_frozen_configuration_rejects_tampered_horizon_authorship() -> None:
    payload = _compile(forward_return_horizons={
        "sampling": "explicit",
        "bases": ["signal"],
        "multipliers": [1, 3],
    }).to_dict()
    request = payload["authoring_core_tests"][0]
    request["horizon"]["multipliers"] = [7]

    with pytest.raises(ValueError, match="request_ref does not match"):
        CompiledICRunConfiguration.from_dict(payload)


def test_factor_set_subject_is_preserved_without_duplicate_member_manifest() -> None:
    settings = _settings(factor_set_selections=[{"target_ref": MOMENTUM_SET}])

    compiled = _migrate_and_freeze(
        settings,
        {ROC: "1m", SGCCS: "5m"},
        factor_set_members={MOMENTUM_SET: (ROC, SGCCS)},
    )

    assert compiled.factor_subject_refs == (MOMENTUM_SET,)
    assert {item.factor_ref for item in compiled.analysis_graph.core_tests} == {
        ROC, SGCCS,
    }
    assert "factor_set_members" not in compiled.to_dict()


def test_standalone_factor_remains_a_subject_beside_a_factor_set() -> None:
    settings = _settings(factor_set_selections=[{"target_ref": MOMENTUM_SET}])

    compiled = _migrate_and_freeze(
        settings,
        {ROC: "1m", SGCCS: "5m"},
        factor_set_members={MOMENTUM_SET: (ROC,)},
    )

    assert compiled.factor_subject_refs == (MOMENTUM_SET, SGCCS)


def test_factor_set_members_must_be_present_in_executable_factor_selection() -> None:
    settings = _settings(
        factor_selections=[_settings()["factor_selections"][0]],
        factor_set_selections=[{"target_ref": MOMENTUM_SET}],
    )

    with pytest.raises(ValueError, match="members are missing from factor_selections"):
        _migrate_and_freeze(
            settings,
            {ROC: "1m"},
            factor_set_members={MOMENTUM_SET: (ROC, SGCCS)},
        )


def test_frozen_configuration_rejects_unknown_standalone_factor_subject() -> None:
    payload = _compile().to_dict()
    payload["factor_subject_refs"] = [
        "factor:v1:profile-maxa:path:unknown:commit:blob",
    ]

    with pytest.raises(ValueError, match="standalone factor subject"):
        CompiledICRunConfiguration.from_dict(payload)
