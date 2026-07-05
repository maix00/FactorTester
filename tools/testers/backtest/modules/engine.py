"""EngineModule — owns the user-facing backtest engine selector."""

from __future__ import annotations

from typing import Any, ClassVar, cast

import pandas as pd

from .base import ExecutableModule, FieldDefinition, FieldRef
from tools.data.types.time_index import DataIndex


class EngineModule(ExecutableModule):
    key: ClassVar[str] = "execution_engine"
    label: ClassVar[str] = "执行引擎"

    engine: ClassVar[FieldRef[str]] = FieldRef("engine")
    engine_mode: ClassVar[FieldRef[str]] = FieldRef("engine_mode")
    counterparty_profile: ClassVar[FieldRef[str | None]] = FieldRef("counterparty_profile")
    bar_open_visibility_delay: ClassVar[FieldRef[str]] = FieldRef("bar_open_visibility_delay")
    bar_end_visibility_delay: ClassVar[FieldRef[str]] = FieldRef("bar_end_visibility_delay")

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
        "counterparty_profile": FieldDefinition(
            public=True,
            label="经纪商预设",
            default="",
            control_template="select",
            tab="engine",
            options=(("", "不使用预设"),),  # real profiles appended by
                # counterparty.apply_counterparty_profile_defaults()

            visible_when={"engine_mode": ("custom",)},
            editable_when={"engine_mode": ("custom",)},
            chip_template="经纪商预设: {value}",
            tab_label="执行引擎",
            tab_order=10,
            help_text=(
                "自定义模式下选择一个经纪商预设，批量填好费用/保证金/流动性等字段的默认值；"
                "字段仍可单独覆写，显式设置的值优先于预设。"
            ),
        ),
        "bar_open_visibility_delay": FieldDefinition(
            public=True,
            label="Bar Open可见延迟",
            default="1us",
            control_template="text",
            tab="engine",
            visible_when={"engine_mode": ("auto", "custom")},
            chip_template="Bar Open可见: {value}",
            tab_label="执行引擎",
            tab_order=10,
            help_text="使用 bar 代理行情时，下一根 bar 的 open 默认在上一根 bar 结束后 1us 可见；exact 模式应使用真实 tick/level-2 时间戳。",
        ),
        "bar_end_visibility_delay": FieldDefinition(
            public=True,
            label="Bar结束可见延迟",
            default="0ns",
            control_template="text",
            tab="engine",
            visible_when={"engine_mode": ("auto", "custom")},
            chip_template="Bar结束可见: {value}",
            tab_label="执行引擎",
            tab_order=10,
            help_text="使用 bar 代理行情时，close/high/low/vwap/twap 等 bar-end 字段在该 bar 结束时刻后的可见延迟。",
        ),
    }


def engine_mode_for(strategy_config) -> str:
    mode = str(strategy_config.get(EngineModule.engine_mode, "auto") or "auto").lower()
    if mode not in {"basic", "auto", "custom", "exact"}:
        return "auto"
    return mode


def bar_price_visibility_timestamp(
    index: pd.DatetimeIndex,
    *,
    price_pos: int,
    basis: str,
    config: object,
    bar_freq: object | None = None,
) -> pd.Timestamp:
    """Return the simulated visibility timestamp for a bar price field.

    This policy belongs to the engine's bar proxy model. In exact mode the
    engine should use tick/level-2 timestamps directly instead of this helper.
    For minute bars, OPEN for row N is visible after row N-1 closes; bar-end
    aggregate fields (close/high/low/vwap/twap/...) are visible at row N's
    timestamp plus an optional non-negative delay.
    """
    if engine_mode_for(config) == "exact":
        raise ValueError("exact engine mode requires real tick/level-2 timestamps, not bar proxy visibility offsets")
    normalized_basis = str(basis or "").lower()
    if price_pos < 0 or price_pos >= len(index):
        raise IndexError(f"price_pos={price_pos} is outside price index")
    price_ts = pd.Timestamp(index[price_pos])
    if normalized_basis == "open":
        if price_pos <= 0:
            raise ValueError("next-bar open visibility requires a previous bar close timestamp")
        delay = _engine_visibility_delay(
            config,
            EngineModule.bar_open_visibility_delay,
            "1us",
            field_name="bar_open_visibility_delay",
        )
        if delay <= pd.Timedelta(0):
            raise ValueError("bar_open_visibility_delay must be positive so OPEN is visible after the previous CLOSE")
        visible_after_previous_close = pd.Timestamp(index[price_pos - 1]) + delay
        freq = _bar_frequency_timedelta(index, bar_freq)
        if isinstance(freq, pd.Timedelta) and freq > pd.Timedelta(0):
            visible_at_target_bar_open = price_ts - freq + delay
            visible = max(visible_after_previous_close, visible_at_target_bar_open)
        else:
            visible = visible_after_previous_close
        if visible > price_ts:
            raise ValueError("bar OPEN visible timestamp cannot be after the bar end timestamp")
        return visible
    delay = _engine_visibility_delay(
        config,
        EngineModule.bar_end_visibility_delay,
        "0ns",
        field_name="bar_end_visibility_delay",
    )
    if delay < pd.Timedelta(0):
        raise ValueError("bar_end_visibility_delay cannot be negative")
    return price_ts + delay


def _bar_frequency_timedelta(index: pd.DatetimeIndex, bar_freq: object | None) -> pd.Timedelta | None:
    if bar_freq is not None:
        value = getattr(bar_freq, "value", bar_freq)
        try:
            freq = pd.Timedelta(cast(Any, value))
        except (TypeError, ValueError):
            freq = None
        if isinstance(freq, pd.Timedelta) and freq > pd.Timedelta(0):
            return freq
    return getattr(DataIndex(index).freq, "value", None)


def _engine_visibility_delay(config: object, ref: FieldRef[str], default: str, *, field_name: str) -> pd.Timedelta:
    raw = cast(Any, config).get(ref, default) if hasattr(config, "get") else default
    try:
        return pd.Timedelta(str(raw or default))
    except ValueError as exc:
        raise ValueError(
            f"invalid {field_name}={raw!r}; expected a pandas Timedelta string such as 1us or 5ms"
        ) from exc
