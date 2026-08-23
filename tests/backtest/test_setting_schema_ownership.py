from tools.testers.backtest.engines.native.flow import Phase, phase_label
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.settings.applications import single_factor_page_settings


def test_single_factor_page_uses_factor_and_product_module_field_schemas() -> None:
    app = single_factor_page_settings()

    for module, field_name, expected_module, expected_tab in (
        (FactorModule, "factor_candidates", "factor_execution", "factors"),
        (FactorModule, "factor_role_bindings", "factor_execution", "factors"),
        (ProductSelectionModule, "product_path_candidates", "product_selection", "product_path_selection"),
        (ProductSelectionModule, "product_path_selection", "product_selection", "product_path_selection"),
    ):
        field = module.fields[field_name]
        setting = app.settings[field_name]

        assert setting.label == field.label
        assert setting.serialization == field.serialization
        assert setting.module == expected_module
        assert setting.tab == expected_tab


def test_phase_labels_are_declared_by_phase() -> None:
    assert phase_label("pre_replay") == Phase.PRE_REPLAY.label
    assert phase_label("per_event") == Phase.PER_EVENT.label
    assert phase_label("post_replay") == Phase.POST_REPLAY.label
