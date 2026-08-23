from __future__ import annotations

from tools.testers.settings import backtest_setting_registry


def test_backtest_run_inputs_are_fully_declared_by_the_backend() -> None:
    manifest = backtest_setting_registry.get("group_test").manifest()
    tabs = {
        item["key"]: item
        for item in manifest["tab_lists"]["local-settings"]
    }

    run_inputs = tabs["run_inputs"]
    assert run_inputs["content_adapter"] == "run_inputs"
    descriptors = {
        item["kind"]: item
        for item in run_inputs["content_options"]["inputs"]
    }
    # Strategy source/spec are now registered through the factor/strategy
    # authoring fields. The run-input tab only owns arbitrary dependency
    # files; keeping the assertion here prevents the old duplicate upload
    # descriptors from returning to the manifest.
    assert set(descriptors) == {"run_dependency"}
    dependency = descriptors["run_dependency"]
    assert dependency["extensions"] == (
        ".cfg", ".csv", ".ini", ".json", ".md", ".py", ".toml",
        ".txt", ".yaml", ".yml",
    )
    assert dependency["purpose_by_extension"] == {
        ".py": "strategy_dependency",
    }
    assert {item["value"] for item in dependency["purposes"]} == {
        "", "strategy_configuration", "strategy_dependency",
        "run_configuration", "data_mapping", "documentation", "other",
    }


def test_factor_upload_control_is_declared_for_every_factor_test() -> None:
    for application in (
        "group_test", "ic_test", "factor_evaluation", "factor_type_analysis",
    ):
        manifest = backtest_setting_registry.get(application).manifest()
        factor_tab = next(
            item
            for item in manifest["tab_lists"]["local-settings"]
            if item["content_adapter"] == "factor_selection"
        )
        assert factor_tab["content_options"] == {}
        contracts = manifest["field_contracts"]["settings"]
        assert {
            "factor_candidates",
            "factor_source_selections",
            "factor_set_selections",
        }.issubset(contracts)
        assert contracts["factor_source_selections"]["value"]["ref_kind"] == (
            "factor_source_selection_list"
        )
