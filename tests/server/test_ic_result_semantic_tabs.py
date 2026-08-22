"""Contract coverage for backend-registered IC result projections."""

from __future__ import annotations

import json

from server.jobs.report_outputs import build_report_artifacts, output_declarations
from tools.testers.settings.applications import backtest_setting_registry


def _ic_result_projections():
    from tools.testers.ic_test.registration.results import ic_result_projections

    return ic_result_projections()


def _result_with_cached_ic_categories() -> dict:
    return {
        "factors": [{
            "factor_alias": "ROC",
            "factor_ref": "factor:v1:roc",
            "ic_method": "rank",
            "primary_forward_return_horizon": "DAY1",
            "ic_series": {"dates": ["2026-01-01", "2026-01-02"], "values": [0.1, 0.2]},
            "autocorr": [{"lag": 1, "ac": 0.25}],
            "ic_resample_stability": [{"lag": 5, "mean": 0.1, "n": 2}],
            "ic_stats_by_forward_horizon": {
                "DAY1": {"0": {
                    "mean_ic": 0.1, "std_ic": 0.2, "icir_signal": 0.5,
                    "n_signal_observations": 2,
                }},
            },
        }],
    }


def test_ic_configuration_reuses_registered_common_tabs_and_run_contract() -> None:
    """IC and backtest must share the same tab/control ownership boundary."""
    ic = backtest_setting_registry.get("ic_test")
    backtest = backtest_setting_registry.get("group_test")
    ic_manifest = ic.manifest()
    backtest_manifest = backtest.manifest()
    ic_tabs = {
        item["key"]: item for item in ic_manifest["tab_lists"]["local-settings"]
    }
    backtest_tabs = {
        item["key"]: item
        for item in backtest_manifest["tab_lists"]["local-settings"]
    }

    for key in ("factor", "product_path_selection", "category"):
        assert ic_tabs[key]["content_adapter"] == backtest_tabs[key]["content_adapter"]
    for key in ("data_source", "frequency"):
        assert ic_tabs[key]["content_adapter"] == backtest_tabs[key]["content_adapter"] == "settings"
        assert ic_tabs[key]["layout_template"] == backtest_tabs[key]["layout_template"] == "settings-grid"
        ic_field = ic_manifest["defaults"][key]
        assert ic_field["value"] == "auto"
        assert ic_field["serialization"]["automatic_only"] is True
        assert ic_field["value_descriptor"] == {
            "value_type": "enum", "cardinality": "one", "editor": "select",
            "format": "", "unit": "", "option_source": "manifest.options",
            "resolver": "", "item_type": "", "ref_kind": "", "schema": {},
            "options": [{"value": "auto", "label": "自动"}],
            "minimum": None, "maximum": None, "step": None,
        }

    assert ic_manifest["default_mounted_tabs"]["local-settings"] == [
        "test_template", "time",
    ]
    assert ic_manifest["run_settings"] == backtest_manifest["run_settings"]
    assert [item["key"] for item in ic_manifest["run_fields"]] == [
        "task_name", "acting_profile_ref", "service_port", "retention_mode",
        "output_requests",
    ]
    for key in ("factor_candidates", "factor_selections", "factor_source_selections",
                "product_path_candidates", "product_path_selections",
                "category_candidates"):
        assert key in ic_manifest["defaults"]
        assert ic_manifest["defaults"][key]["adapter_managed"] is True
        assert ic_manifest["defaults"][key]["execution_policy"] == "authoring_only"
    assert ic.audit_mounts(client="web") == []


def test_ic_projection_manifest_is_backend_owned_and_ordered() -> None:
    manifest = backtest_setting_registry.get("ic_test").manifest()
    projections = manifest["result_projections"]
    assert [item["key"] for item in projections] == [
        item.key for item in _ic_result_projections()
    ]
    assert all(item["source_artifacts"] for item in projections)
    assert all(item["output_requests"] for item in projections)
    assert [item["order"] for item in projections] == sorted(
        item["order"] for item in projections
    )


def test_ic_output_declarations_carry_the_same_projection() -> None:
    declarations = output_declarations(["ic_series", "ic_statistics"])
    projection_lists = [
        declaration["result_tabs"]
        for declaration in declarations
        if declaration.get("result_tabs")
    ]
    assert len(projection_lists) == 1
    keys = [item["key"] for item in projection_lists[0]]
    expected = {
        item.key for item in _ic_result_projections()
        if {"ic_series", "ic_statistics"}.intersection(item.output_requests)
    }
    assert keys == [
        item.key for item in _ic_result_projections() if item.key in expected
    ]
    assert len(keys) == len(set(keys))


def test_ic_statistics_builder_persists_cached_analysis_categories() -> None:
    artifacts = build_report_artifacts(
        _result_with_cached_ic_categories(), requested=("ic_statistics",),
    )
    payloads = {
        item.name: json.loads(item.raw)
        for item in artifacts if item.name.endswith("_data")
    }
    assert "ic_statistics_data" in payloads
    assert "ic_statistics_summary_data" in payloads
    assert payloads["ic_resample_stability_data"]["rows"] == [{
        "factor_alias": "ROC", "factor_ref": "factor:v1:roc",
        "ic_method": "rank", "lag": 5, "mean": 0.1, "n": 2,
    }]
    assert payloads["ic_autocorrelation_data"]["rows"] == [{
        "factor_alias": "ROC", "factor_ref": "factor:v1:roc",
        "ic_method": "rank", "lag": 1, "autocorrelation": 0.25,
    }]
