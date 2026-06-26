"""Shared run window / time range setting registrations."""

from __future__ import annotations

from ..contracts import ScopePolicy, SettingDefinition, SettingOption
from ..registry import ApplicationSettings

RUN_WINDOW_KEYS = (
    "start_date",
    "end_date",
    "start_time",
    "end_time",
    "timezone",
    "time_precision",
)


def register_run_window_base(
    app: ApplicationSettings,
    *,
    tab: str = "time",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "start_date", "开始日期", tab, "date", "", scope_policy,
        module="run_window", chip_template="开始日期: {value}",
        serialization={"display_order": 10},
    ))
    app.register_setting(SettingDefinition(
        "end_date", "结束日期", tab, "date", "", scope_policy,
        module="run_window", chip_template="结束日期: {value}",
        serialization={"display_order": 20},
    ))
    app.register_setting(SettingDefinition(
        "start_time", "开始时间", tab, "time", "00:00", scope_policy,
        module="run_window", chip_template="开始时间: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 40},
    ))
    app.register_setting(SettingDefinition(
        "end_time", "结束时间", tab, "time", "23:59", scope_policy,
        module="run_window", chip_template="结束时间: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 50},
    ))
    app.register_setting(SettingDefinition(
        "time_precision", "时间精度", tab, "select", "exact", scope_policy,
        module="run_window",
        options=(
            SettingOption("exact", "精确时间"),
            SettingOption("trading_day", "交易日"),
        ),
        chip_template="时间精度: {value}",
        serialization={"display_order": 30},
    ))
    app.register_setting(SettingDefinition(
        "timezone", "时区", tab, "select", "Asia/Shanghai", scope_policy,
        module="run_window",
        options=(
            SettingOption("Asia/Shanghai", "Asia/Shanghai (UTC+8)"),
            SettingOption("UTC", "UTC"),
            SettingOption("America/New_York", "America/New_York"),
            SettingOption("Europe/London", "Europe/London"),
        ),
        chip_template="时区: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 60},
    ))
