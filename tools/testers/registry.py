"""Module 注册中心基类。

注册的原子单位是 Module：一组 key + label + order + executor + app。
"""

from __future__ import annotations

from typing import Any


class ModuleRegistry:
    """通用 Module 注册中心。

    子类在 __init__ 中注册自己的 Module 列表。
    """

    def __init__(self) -> None:
        self._modules: dict[str, Any] = {}

    def register(self, module: Any) -> None:
        key: str = getattr(module, "key", "")
        if not key:
            raise ValueError(f"module {module!r} must have a non-empty key")
        if key in self._modules:
            raise ValueError(f"duplicate module key: {key}")
        self._modules[key] = module

    def get(self, key: str) -> Any:
        try:
            return self._modules[key]
        except KeyError as exc:
            raise KeyError(f"unknown module: {key!r}") from exc

    @property
    def module_keys(self) -> tuple[str, ...]:
        return tuple(self._modules.keys())

    def sorted_modules(self) -> list[Any]:
        return sorted(self._modules.values(), key=lambda m: getattr(m, "order", 0))
