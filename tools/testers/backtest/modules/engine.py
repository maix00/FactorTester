"""EngineModule — owns the user-facing backtest engine selector."""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef


class EngineModule(ExecutableModule):
    key: ClassVar[str] = "execution_engine"
    label: ClassVar[str] = "执行引擎"

    engine: ClassVar[FieldRef[str]] = FieldRef("engine")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "engine": FieldDefinition(
            public=True,
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
    }
