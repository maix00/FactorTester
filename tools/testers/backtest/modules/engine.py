"""EngineModule — owns the user-facing backtest engine selector."""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef


class EngineModule(ExecutableModule):
    key: ClassVar[str] = "execution_engine"
    label: ClassVar[str] = "执行引擎"

    engine: ClassVar[FieldRef[str]] = FieldRef("engine")
    engine_mode: ClassVar[FieldRef[str]] = FieldRef("engine_mode")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "engine": FieldDefinition(
            public=True,
            label="引擎",
            default="native",
            control_template="select",
            tab="engine",
            scope_policy="local_only",
            options=(
                ("native", "Native 事件驱动回测工具"),
                ("backtrader", "Backtrader 事件驱动回测工具"),
                ("qlib", "Qlib 事件驱动回测工具"),
                ("zipline", "Zipline 事件驱动回测工具"),
                ("rqalpha", "RQAlpha 事件驱动回测工具"),
            ),
            chip_template="引擎: {value}",
            tab_label="执行引擎",
            tab_order=10,
            tab_default_mount_points=("local-settings",),
        ),
        "engine_mode": FieldDefinition(
            public=True,
            label="模式",
            default="auto",
            control_template="select",
            tab="engine",
            options=(
                ("basic", "基础"),
                ("auto", "自动兼容"),
                ("custom", "自定义"),
                ("exact", "严格"),
            ),
            chip_template="模式: {value}",
            tab_label="执行引擎",
            tab_order=10,
        ),
    }


def engine_mode_for(strategy_config) -> str:
    mode = str(strategy_config.get(EngineModule.engine_mode, "auto") or "auto").lower()
    if mode not in {"basic", "auto", "custom", "exact"}:
        return "auto"
    return mode
