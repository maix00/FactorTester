"""Backend-owned declarations for source-backed Job inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tools.testers.run_input_contracts import RUN_INPUTS, factor_source_content_options

if TYPE_CHECKING:
    from tools.testers.settings.registry import ApplicationSettings


def register_run_inputs_base(app: Any) -> None:
    """Register retained, non-template Job inputs for a backtest application."""
    # Keep the descriptor helper importable from executable modules.  Importing
    # settings contracts here at module import time would make FactorModule's
    # field declaration re-enter settings application registration.
    from tools.testers.settings.contracts import (
        ChipDefinition,
        SettingModule,
        SettingTab,
        TabMountPoint,
    )

    app.register_module(SettingModule(
        "run_inputs", "策略 Hook 与运行输入", "execution", 185,
    ))
    app.register_tab(SettingTab(
        "run_inputs",
        "运行输入",
        (TabMountPoint.LOCAL_SETTINGS,),
        "custom",
        185,
        (TabMountPoint.LOCAL_SETTINGS,),
        content_adapter="run_inputs",
        content_options={
            "title": "策略 Hook 与运行输入",
            "description": "源码、策略配置和其他输入随任务冻结保留，清空任务文件时一并删除",
            "inputs": RUN_INPUTS,
        },
    ))
    app.register_chip_field(ChipDefinition(
        "run_inputs",
        "运行输入",
        "execution",
        "运行输入: {run_input_count}项",
        ("run_input_count",),
        module="run_inputs",
        target_tab="run_inputs",
        order=185,
        source_adapter="run_inputs",
        clickable=True,
    ))
