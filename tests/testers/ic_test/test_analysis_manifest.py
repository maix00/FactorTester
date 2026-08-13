from __future__ import annotations

from tools.testers.analysis_graph import AnalysisTargetOrigin
from tools.testers.ic_test.analysis_graph import ic_analysis_graph_definition
from tools.testers.settings import backtest_setting_registry


def test_ic_manifest_declares_core_axes_and_typed_analysis_contracts() -> None:
    manifest = ic_analysis_graph_definition().to_dict()

    assert manifest["key"] == "ic_analysis_graph"
    assert manifest["core_test"]["axes"] == [
        "product_scope_ref",
        "factor_ref",
        "horizon",
        "entry_delay_bars",
        "method",
    ]
    analyses = {item["key"]: item for item in manifest["analysis_types"]}
    assert list(analyses) == [
        "ic_resample_stability",
        "rolling_ic_stability",
        "period_diagnostics",
        "ic_autocorrelation",
        "quantile_portfolio_statistics",
        "forward_horizon_half_life",
    ]
    assert analyses["rolling_ic_stability"]["input_contract"] == {
        "accepted_kinds": ["ic_series"],
        "target_origins": ["core"],
        "cardinality": "one",
        "mapping": "map_each",
        "minimum_targets": 1,
        "maximum_targets": 1,
        "same_axes": [],
        "varying_axes": [],
    }
    quantile = analyses["quantile_portfolio_statistics"]
    assert quantile["input_contract"]["target_origins"] == ["core"]
    assert quantile["required_core_inputs"] == [
        "factor_values",
        "forward_returns",
        "eligibility",
    ]
    half_life = analyses["forward_horizon_half_life"]
    assert half_life["input_contract"]["cardinality"] == "many"
    assert half_life["input_contract"]["mapping"] == "combine"
    assert half_life["input_contract"]["same_axes"] == [
        "product_scope_ref",
        "factor_ref",
        "entry_delay_bars",
        "method",
    ]
    assert half_life["input_contract"]["varying_axes"] == ["horizon"]


def test_ic_application_manifest_exposes_graph_without_web_field_knowledge() -> None:
    manifest = backtest_setting_registry.get("ic_test").manifest()

    assert manifest["analysis_graph"] == ic_analysis_graph_definition().to_dict()


def test_analysis_target_origin_enum_is_stable_for_clients() -> None:
    assert [item.value for item in AnalysisTargetOrigin] == ["core", "analysis"]
