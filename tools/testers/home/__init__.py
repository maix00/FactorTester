"""Home — 顶层测试类型注册中心。

注册所有平行测试类型 Module。模块列表是声明式 config
（见 static/config/testers/home.json）——不需要手写 Module 子类，新增顶级
页面只改那份 JSON。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.testers.registry import ModuleRegistry, load_module_configs

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "static" / "config" / "testers" / "home.yaml"


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


class HomeModuleRegistry(ModuleRegistry):
    """顶层注册中心：注册所有页面级 Module。"""

    client = "web"
    layouts = {"web": "stack"}

    def __init__(self) -> None:
        super().__init__()
        self.register_from_config(
            load_module_configs(_CONFIG_PATH),
            build_app_resolver=_build_app_resolver,
            sub_registry_resolver=_sub_registry_resolver,
        )
