"""Canonical setting schema returned to every backtest frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class SettingScope(str, Enum):
    SHARED = "shared"
    STRATEGY = "strategy"


class ScopePolicy(str, Enum):
    SHARED_ONLY = "shared_only"
    STRATEGY_ONLY = "strategy_only"
    SELECTABLE = "selectable"


@dataclass(frozen=True, slots=True)
class SettingOption:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    key: str
    label: str
    tab: str
    control_template: str
    default: Any
    scope_policy: ScopePolicy
    default_scope: SettingScope
    options: tuple[SettingOption, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    chip_template: str | None = None
    help_text: str = ""

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.tab or not self.control_template:
            raise ValueError("setting definition requires key, label, tab, and template")
        if self.scope_policy == ScopePolicy.SHARED_ONLY and self.default_scope != SettingScope.SHARED:
            raise ValueError("shared-only setting must default to shared scope")
        if self.scope_policy == ScopePolicy.STRATEGY_ONLY and self.default_scope != SettingScope.STRATEGY:
            raise ValueError("strategy-only setting must default to strategy scope")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope_policy"] = self.scope_policy.value
        value["default_scope"] = self.default_scope.value
        return value


@dataclass(frozen=True, slots=True)
class SettingTab:
    key: str
    label: str
    layout_template: str
    order: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
