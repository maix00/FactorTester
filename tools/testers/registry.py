"""Module 注册中心基类。

注册的原子单位是 Module：一组 key + label + order + executor + app。

Module 不需要手写子类——像 static/config/modules.json 驱动首页模块网格一样，
这里也用声明式 config（JSON，纯数据）+ 一个解析函数（key -> 实际 Python 可调用对象）
构造 Module 实例。见 load_module_configs / ModuleRegistry.register_from_config。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from tools.testers.settings.applications import ApplicationSettings


class Module:
    """Module 接口：注册到 ModuleRegistry 的原子单位。

    既可以子类化（覆写 _build_app/sub_registry），也可以直接用关键字参数构造
    （key/label/order/client/layouts/executor/build_app/sub_registry）——后者是
    config 驱动场景下的常规用法，不需要为每个模块写一个类。

    app 懒构建，首次访问时调用 _build_app()（或构造时传入的 build_app 可调用对象）并缓存。

    client 决定目标客户端：web / desktop / cli。
    layouts 按 client 映射前端展示方式：
      - "stack"   — 垂直顺序排列
      - "tabs"    — tab 切换
      - "sidebar" — 侧边栏导航
      - "wizard"  — 步骤向导

    sub_registry 支持嵌套：Module 内部可以注册子 Module。
    例如 group_test 内部嵌套 BacktestModuleRegistry。传入的 sub_registry 可以是
    一个 ModuleRegistry 实例，也可以是一个无参可调用对象（懒构建，首次访问时调用）。
    """

    key: str = ""
    label: str = ""
    order: int = 0
    executor: type | None = None
    client: str = "web"
    layouts: dict[str, str] = {"web": "stack"}

    def __init__(
        self,
        *,
        key: str | None = None,
        label: str | None = None,
        order: int | None = None,
        executor: type | None = None,
        client: str | None = None,
        layouts: dict[str, str] | None = None,
        build_app: Callable[[], "ApplicationSettings"] | None = None,
        sub_registry: "ModuleRegistry | Callable[[], ModuleRegistry] | None" = None,
    ) -> None:
        if key is not None:
            self.key = key
        if label is not None:
            self.label = label
        if order is not None:
            self.order = order
        if executor is not None:
            self.executor = executor
        if client is not None:
            self.client = client
        if layouts is not None:
            self.layouts = layouts
        self._build_app_fn = build_app
        self._sub_registry_factory = sub_registry
        self._app: "ApplicationSettings | None" = None
        self._sub_registry_cache: "ModuleRegistry | None" = None

    @property
    def layout(self) -> str:
        """当前 client 对应的 layout。"""
        return self.layouts.get(self.client, "stack")

    @property
    def app(self) -> "ApplicationSettings":
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> "ApplicationSettings":
        if self._build_app_fn is not None:
            return self._build_app_fn()
        raise NotImplementedError(f"module {self.key!r} has no build_app")

    @property
    def sub_registry(self) -> "ModuleRegistry | None":
        if self._sub_registry_cache is None and self._sub_registry_factory is not None:
            factory = self._sub_registry_factory
            self._sub_registry_cache = factory() if callable(factory) else factory
        return self._sub_registry_cache


class ModuleRegistry:
    """通用 Module 注册中心。

    client / layouts 含义同 Module。
    layout 属性返回当前 client 对应的展示方式。

    子类可以在 __init__ 里手动 register()，也可以调用 register_from_config()
    从声明式 config 批量构造并注册（推荐——不需要为每个模块写一个 Module 子类）。
    """

    client: str = "web"
    layouts: dict[str, str] = {"web": "stack"}

    @property
    def layout(self) -> str:
        return self.layouts.get(self.client, "stack")

    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}

    def register(self, module: Module) -> None:
        if not module.key:
            raise ValueError(f"module {module!r} must have a non-empty key")
        if module.key in self._modules:
            raise ValueError(f"duplicate module key: {module.key}")
        self._modules[module.key] = module

    def register_from_config(
        self,
        configs: list[dict[str, Any]],
        *,
        build_app_resolver: Callable[[dict[str, Any]], Callable[[], "ApplicationSettings"] | None] | None = None,
        sub_registry_resolver: Callable[[dict[str, Any]], "ModuleRegistry | Callable[[], ModuleRegistry] | None"] | None = None,
    ) -> None:
        """从声明式 config（见 load_module_configs）批量构造 + 注册 Module。

        configs 中每项是纯数据字典：{key, label, order, client?, layouts?, ...}。
        build_app_resolver(cfg) -> 该模块的 _build_app 可调用对象（按 cfg 解析，
        通常按 key 的命名约定找到 tools.testers.settings.applications 里的
        "<key>_settings" 函数）。sub_registry_resolver(cfg) -> 该模块的子注册中心
        工厂（无子注册中心则返回 None）。
        """
        for cfg in configs:
            self.register(Module(
                key=cfg["key"],
                label=cfg.get("label", cfg["key"]),
                order=cfg.get("order", 0),
                client=cfg.get("client"),
                layouts=cfg.get("layouts"),
                build_app=build_app_resolver(cfg) if build_app_resolver else None,
                sub_registry=sub_registry_resolver(cfg) if sub_registry_resolver else None,
            ))

    def get(self, key: str) -> Module:
        try:
            return self._modules[key]
        except KeyError as exc:
            raise KeyError(f"unknown module: {key!r}") from exc

    def find(self, key: str) -> "Module | None":
        """递归查找 key 对应的 Module：先查自身，再递归各子 Module 的 sub_registry。"""
        module = self._modules.get(key)
        if module is not None:
            return module
        for candidate in self._modules.values():
            sub = candidate.sub_registry
            if isinstance(sub, ModuleRegistry):
                found = sub.find(key)
                if found is not None:
                    return found
        return None

    @property
    def module_keys(self) -> tuple[str, ...]:
        return tuple(self._modules.keys())

    def sorted_modules(self) -> list[Module]:
        return sorted(self._modules.values(), key=lambda m: m.order)


def load_module_configs(path: str | Path) -> list[dict[str, Any]]:
    """加载一个声明式 module config YAML 文件（结构与 static/config/modules.json 同形）。

    文件格式：{"version": 1, "modules": [{"key": ..., "label": ..., "order": ...}, ...]}
    """
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return payload.get("modules", [])
