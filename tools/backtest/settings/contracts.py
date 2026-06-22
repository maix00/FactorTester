"""Canonical setting schema returned to every backtest frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class SettingScope(str, Enum):
    LOCAL = "local"
    GROUP = "group"


class ScopePolicy(str, Enum):
    LOCAL_ONLY = "local_only"
    GROUP_ONLY = "group_only"
    GROUP_OVERRIDE = "group_override"


class TabMountPoint(str, Enum):
    LOCAL_SETTINGS = "local-settings"
    GROUP_SETTINGS = "group-settings"


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
    options: tuple[SettingOption, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    chip_template: str | None = None
    help_text: str = ""

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.tab or not self.control_template:
            raise ValueError("setting definition requires key, label, tab, and template")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["scope_policy"] = self.scope_policy.value
        return value


@dataclass(frozen=True, slots=True)
class ChipDefinition:
    key: str
    label: str
    category: str
    chip_template: str
    source_keys: tuple[str, ...]
    order: int = 100
    inherit_from_root: bool = False
    value_resolvers: dict[str, str] = field(default_factory=dict)
    clickable: bool = False

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.category or not self.chip_template:
            raise ValueError("chip definition requires key, label, category, and template")
        if not self.source_keys:
            raise ValueError("chip definition requires at least one source key")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SettingTab:
    key: str
    label: str
    mount_points: tuple[TabMountPoint, ...]
    layout_template: str
    order: int
    default_mount_points: tuple[TabMountPoint, ...] = ()
    summary_template: str | None = None
    summary_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mount_points"] = [mount.value for mount in self.mount_points]
        value["default_mount_points"] = [
            mount.value for mount in self.default_mount_points
        ]
        return value
