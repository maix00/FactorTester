"""RunWindowModule — owns the backtest time range and evaluation split."""

from __future__ import annotations

from typing import ClassVar

from .base import ExecutableModule, FieldDefinition, FieldRef


class RunWindowModule(ExecutableModule):
    key: ClassVar[str] = "run_window"
    label: ClassVar[str] = "运行时间范围"

    start_date: ClassVar[FieldRef[str]] = FieldRef("start_date")
    end_date: ClassVar[FieldRef[str]] = FieldRef("end_date")
    start_time: ClassVar[FieldRef[str]] = FieldRef("start_time")
    end_time: ClassVar[FieldRef[str]] = FieldRef("end_time")
    timezone: ClassVar[FieldRef[str]] = FieldRef("timezone")
    time_precision: ClassVar[FieldRef[str]] = FieldRef("time_precision")
    evaluation_split: ClassVar[FieldRef[str]] = FieldRef("evaluation_split")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "start_date": FieldDefinition(
            public=True, label="开始日期", default="", control_template="date", tab="time",
            chip_template="开始日期: {value}", tab_label="时间范围", tab_order=40,
            serialization={"display_order": 10},
        ),
        "end_date": FieldDefinition(
            public=True, label="结束日期", default="", control_template="date", tab="time",
            chip_template="结束日期: {value}", tab_label="时间范围", tab_order=40,
            serialization={"display_order": 20},
        ),
        "time_precision": FieldDefinition(
            public=True, label="时间精度", default="exact", control_template="select", tab="time",
            options=(("exact", "精确时间"), ("trading_day", "交易日")),
            chip_template="时间精度: {value}", tab_label="时间范围", tab_order=40,
            serialization={"display_order": 30},
        ),
        "start_time": FieldDefinition(
            public=True, label="开始时间", default="00:00", control_template="time", tab="time",
            visible_when={"time_precision": ("exact",)},
            chip_template="开始时间: {value}", tab_label="时间范围", tab_order=40,
            serialization={"display_order": 40},
        ),
        "end_time": FieldDefinition(
            public=True, label="结束时间", default="23:59", control_template="time", tab="time",
            visible_when={"time_precision": ("exact",)},
            chip_template="结束时间: {value}", tab_label="时间范围", tab_order=40,
            serialization={"display_order": 50},
        ),
        "timezone": FieldDefinition(
            public=True, label="时区", default="Asia/Shanghai", control_template="select", tab="time",
            options=(
                ("Asia/Shanghai", "Asia/Shanghai (UTC+8)"),
                ("UTC", "UTC"),
                ("America/New_York", "America/New_York"),
                ("Europe/London", "Europe/London"),
            ),
            visible_when={"time_precision": ("exact",)},
            chip_template="时区: {value}", tab_label="时间范围", tab_order=40,
            serialization={"display_order": 60},
        ),
        "evaluation_split": FieldDefinition(
            public=True, label="样本切分", default=None, control_template="date", tab="evaluation",
            chip_template="样本切分: {value}", tab_label="样本划分", tab_order=200,
        ),
    }
