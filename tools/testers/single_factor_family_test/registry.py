"""Single-factor family test — 测试模块注册中心。

管理页面上显示的每个测试模块（单因子测试、分组回测、IC测试、
因子评估、因子类型分析）。模块列表是声明式 config（见
static/config/testers/single_factor_family_test.json），不需要为每个
模块手写一个 Module 子类——像 static/config/modules.json 驱动首页模块网格
一样，这里只需维护 JSON，Python 侧只做两件解析工作：
  - build_app：按 "<key>_settings" 命名约定在 applications.py 里找工厂函数；
  - sub_registry：JSON 里的 sub_registry 字符串 -> 实际子注册中心工厂（懒构建）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.testers.registry import ModuleRegistry, load_module_configs

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "static" / "config" / "testers" / "single_factor_family_test.yaml"
)


def _build_app_resolver(cfg: dict[str, Any]):
    from tools.testers.settings import applications
    name = cfg.get("build_app", cfg["key"])
    fn = getattr(applications, f"{name}_settings", None)
    if fn is None:
        raise AttributeError(
            f"module {cfg['key']!r}: no settings factory '{name}_settings' in tools.testers.settings.applications"
        )
    return fn


def _backtest_module_registry():
    from tools.testers.backtest.modules.registry import BacktestModuleRegistry
    return BacktestModuleRegistry()


_SUB_REGISTRY_FACTORIES = {
    "backtest_module_registry": _backtest_module_registry,
}


def _sub_registry_resolver(cfg: dict[str, Any]):
    name = cfg.get("sub_registry")
    if not name:
        return None
    factory = _SUB_REGISTRY_FACTORIES.get(name)
    if factory is None:
        raise KeyError(f"module {cfg['key']!r}: unknown sub_registry {name!r}")
    return factory


class SingleFactorFamilyTestModuleRegistry(ModuleRegistry):
    """single_factor_page 页面的测试模块注册中心。

    每个测试模块是一个 Module，包含 executor + app 两个维度。
    """

    layouts = {"web": "stack"}

    def __init__(self) -> None:
        super().__init__()
        self.register_from_config(
            load_module_configs(_CONFIG_PATH),
            build_app_resolver=_build_app_resolver,
            sub_registry_resolver=_sub_registry_resolver,
        )
