"""Locks in the flat, parallel test-type Module registry."""

from __future__ import annotations


def test_home_registers_parallel_test_types_in_order():
    from tools.testers.home import HomeModuleRegistry

    home = HomeModuleRegistry()
    assert home.module_keys == (
        "factor_evaluation", "ic_test", "backtest", "factor_type_analysis",
    )
    assert [module.label for module in home.sorted_modules()] == [
        "查看因子序列", "IC 测试", "回测", "因子类型分析",
    ]
    for module in home.sorted_modules():
        assert type(module.app).__name__ == "ApplicationSettings"


def test_backtest_alone_nests_the_execution_module_registry():
    from tools.testers.backtest.modules.registry import BacktestModuleRegistry
    from tools.testers.home import HomeModuleRegistry

    home = HomeModuleRegistry()
    nested = home.get("backtest").sub_registry
    assert isinstance(nested, BacktestModuleRegistry)
    assert nested.module_keys
    assert home.get("factor_evaluation").sub_registry is None


def test_find_resolves_parallel_types():
    from tools.testers.home import HomeModuleRegistry

    home = HomeModuleRegistry()
    assert home.find("factor_evaluation") is home.get("factor_evaluation")
    assert home.find("ic_test") is home.get("ic_test")
    assert home.find("group_test") is None
    assert home.find("does_not_exist") is None
