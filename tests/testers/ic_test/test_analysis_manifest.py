from __future__ import annotations

import pytest

from tools.testers.analysis_graph import (
    AnalysisTargetOrigin,
    CoreAxisDefinition,
    CoreTestDefinition,
)
from tools.testers.field_spec import ValueDescriptor
from tools.testers.ic_test.analysis_graph import ic_analysis_graph_definition
from tools.testers.ic_test.analysis_graph.runtime.adapters import (
    builtin_runtime_adapters,
)
from tools.testers.settings import backtest_setting_registry


def test_ic_manifest_declares_core_axes_and_typed_analysis_contracts() -> None:
    manifest = ic_analysis_graph_definition().to_dict()

    assert manifest["key"] == "ic_analysis_graph"
    assert {
        key: manifest["authoring_contract"][key]
        for key in (
            "schema_version", "core_tests_key", "analyses_key",
            "factor_subject_refs_key", "output_requests_key",
        )
    } == {
        "schema_version": 1,
        "core_tests_key": "core_tests",
        "analyses_key": "analyses",
        "factor_subject_refs_key": "factor_subject_refs",
        "output_requests_key": "output_requests",
    }
    assert manifest["core_test"]["axes"] == [
        "product_scope_ref",
        "factor_ref",
        "horizon",
        "entry_delay_bars",
        "method",
        "return_price_basis",
    ]
    axes = {
        item["key"]: item for item in manifest["core_test"]["axis_definitions"]
    }
    assert axes["factor_ref"] == {
        "key": "factor_ref",
        "label": "因子",
        "authoring_key": "factor_refs",
        "source_adapter": "selected_factors",
        "accepts_many": True,
        "resolution_adapter": "frozen_factor_members",
        "value_descriptor": {
            "value_type": "reference",
            "cardinality": "many",
            "editor": "catalog",
            "format": "",
            "unit": "",
            "option_source": "catalog.factor",
            "resolver": "selected_factors",
            "item_type": "reference",
            "ref_kind": "frozen_factor_ref",
            "schema": {},
            "options": [],
            "minimum": None,
            "maximum": None,
            "step": None,
        },
        "help_text": "选择冻结因子或因子集合；集合在冻结运行配置时展开为具体因子",
        "value_contract": {
            "item_type": "frozen_factor_ref",
            "minimum_items": 1,
            "unique_items": True,
        },
    }
    assert axes["horizon"]["authoring_key"] == "horizon"
    assert axes["horizon"]["value_descriptor"]["editor"] == "base_multiplier_grid"
    assert axes["horizon"]["resolution_adapter"] == "per_factor_frequency"
    assert axes["horizon"]["accepts_many"] is True
    assert axes["horizon"]["value_contract"] == {
        "modes": ["scale_aware", "explicit"],
        "default_mode": "scale_aware",
        "base_values": ["signal"],
        "allow_physical_frequency_base": True,
        "multiplier_minimum": 1,
        "multiplier_integer_only": True,
        "minimum_multipliers": 1,
    }
    assert axes["entry_delay_bars"]["authoring_key"] == "entry_delay_bars"
    assert axes["entry_delay_bars"]["value_contract"] == {
        "item_type": "integer",
        "minimum": 0,
        "minimum_items": 1,
        "unique_items": True,
    }
    assert axes["method"]["authoring_key"] == "methods"
    assert axes["method"]["value_descriptor"]["options"] == [
        {"value": "rank", "label": "Rank IC"},
        {"value": "pearson", "label": "Pearson IC"},
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
    # Analysis chips are part of the backend-owned graph contract.  The web
    # client may render these descriptors generically, but must not maintain a
    # second list of analysis names, labels, or parameter formatting rules.
    for analysis in analyses.values():
        chip = analysis["chip"]
        assert chip["key"] == analysis["key"]
        assert chip["category"] == "analysis"
        assert chip["source"] == "analysis_parameters"
        assert chip["target"] == "analysis_overlay"
        assert chip["clickable"] is True
        assert chip["label"]
        assert chip["template"]
        assert set(chip["parameter_keys"]).issubset(
            {parameter["key"] for parameter in analysis["parameters"]}
        )
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
        "return_price_basis",
    ]
    assert half_life["input_contract"]["varying_axes"] == ["horizon"]


def test_ic_application_manifest_exposes_graph_without_web_field_knowledge() -> None:
    manifest = backtest_setting_registry.get("ic_test").manifest()

    assert manifest["analysis_graph"] == ic_analysis_graph_definition().to_dict()
    group = manifest["analysis_graph"]["authoring_contract"][
        "configuration_group_schema"
    ]
    assert group["required"] == [
        "config_group_id", "batch_id", "name", "factor_ref",
        "product_scope_ref", "entry_delay_bars", "horizon", "methods",
        "return_price_basis",
    ]
    assert group["properties"]["entry_delay_bars"] == {
        "type": "integer", "minimum": 0, "title": "入场延迟",
    }


def test_every_manifest_analysis_has_a_typed_runtime_adapter() -> None:
    registered = {
        item.key for item in ic_analysis_graph_definition().analysis_types
    }
    assert registered == set(builtin_runtime_adapters())


def test_analysis_target_origin_enum_is_stable_for_clients() -> None:
    assert [item.value for item in AnalysisTargetOrigin] == ["core", "analysis"]


def test_core_axis_contract_cannot_drift_from_execution_axes() -> None:
    with pytest.raises(ValueError, match="exactly match"):
        CoreTestDefinition(
            label="Core",
            axes=("factor_ref", "horizon"),
            output_kinds=("ic_series",),
            axis_definitions=(
                CoreAxisDefinition(
                    "factor_ref", "因子", "factor_selections",
                    ValueDescriptor("reference", cardinality="one", editor="catalog"),
                ),
            ),
        )
