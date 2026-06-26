"""Locks in the config-driven Module/ModuleRegistry hierarchy:

HomeModuleRegistry -> single_factor_family_test (page Module)
  -> sub_registry: SingleFactorFamilyTestModuleRegistry
       -> 5 leaf Modules (single_factor_page, factor_evaluation,
          factor_type_analysis, ic_test, group_test)
       -> group_test.sub_registry: BacktestModuleRegistry

No Module subclasses are hand-written — they're all constructed from the
declarative JSON configs under static/config/testers/. This test catches
config/resolver drift (typo'd key, missing settings factory, broken
sub_registry wiring) without needing to read every config by hand.
"""
from __future__ import annotations


def test_home_registers_single_factor_family_test_page():
    from tools.testers.home import HomeModuleRegistry

    home = HomeModuleRegistry()
    assert home.module_keys == ("single_factor_family_test",)

    page = home.get("single_factor_family_test")
    assert page.label == "单因子家族测试"
    assert page.order == 10
    # build_app override resolves to single_factor_page_settings, not a
    # (nonexistent) single_factor_family_test_settings.
    assert type(page.app).__name__ == "ApplicationSettings"


def test_single_factor_family_test_registers_five_modules_in_order():
    from tools.testers.single_factor_family_test.registry import (
        SingleFactorFamilyTestModuleRegistry,
    )

    sub = SingleFactorFamilyTestModuleRegistry()
    assert sub.module_keys == (
        "single_factor_page",
        "factor_evaluation",
        "factor_type_analysis",
        "ic_test",
        "group_test",
    )
    ordered = sub.sorted_modules()
    assert [m.order for m in ordered] == [10, 20, 30, 40, 50]
    # Every leaf module's app builds without error (each resolves to its own
    # "<key>_settings" factory via naming convention).
    for module in ordered:
        assert type(module.app).__name__ == "ApplicationSettings"


def test_group_test_module_nests_backtest_module_registry():
    from tools.testers.backtest.modules.registry import BacktestModuleRegistry
    from tools.testers.single_factor_family_test.registry import (
        SingleFactorFamilyTestModuleRegistry,
    )

    sub = SingleFactorFamilyTestModuleRegistry()
    group_test = sub.get("group_test")
    nested = group_test.sub_registry
    assert isinstance(nested, BacktestModuleRegistry)
    assert nested.module_keys  # at least one executable module registered


def test_full_hierarchy_resolves_three_levels_deep():
    from tools.testers.home import HomeModuleRegistry

    home = HomeModuleRegistry()
    page = home.get("single_factor_family_test")
    group_test = page.sub_registry.get("group_test")
    backtest_registry = group_test.sub_registry
    assert backtest_registry.module_keys
