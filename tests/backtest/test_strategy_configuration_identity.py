from tools.factors.tester_calc.single_factor_test.group.research_run.strategy_identity import (
    strategy_configuration_id,
)


def test_strategy_configuration_identity_ignores_group_ordinal_and_presentation() -> None:
    settings = {
        "factor_refs": ("factor:a", "factor:b"),
        "factor_combination_mode": "mean",
        "split_count": 5,
        "group_index": 0,
        "allocation_policy": "equal_notional",
    }
    first = strategy_configuration_id(
        {"strategy_id": "g1", "display_name": "第一组", "group_index": 0,
         "product_path_selection_id": "night"},
        settings,
    )
    second = strategy_configuration_id(
        {"strategy_id": "g5", "display_name": "第五组", "group_index": 4,
         "product_path_selection_id": "night"},
        {**settings, "group_index": 4, "display_name": "第五组"},
    )
    assert first == second
    assert first != strategy_configuration_id(
        {"strategy_id": "g1", "product_path_selection_id": "day"}, settings,
    )
    assert first != strategy_configuration_id(
        {"strategy_id": "g1", "product_path_selection_id": "night"},
        {**settings, "split_count": 10},
    )
