"""Tester setting schemas and resolution — shared across all test applications."""

from .applications import backtest_setting_registry
from .contracts import RunFieldDefinition, SettingScope, TabMountPoint
from tools.testers.field_spec import FieldSpec, ValueDescriptor
from .resolver import resolve_group_settings

__all__ = [
    "SettingScope",
    "RunFieldDefinition",
    "FieldSpec",
    "ValueDescriptor",
    "TabMountPoint",
    "backtest_setting_registry",
    "resolve_group_settings",
]
