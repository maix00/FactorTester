"""RunWindowModule — owns the backtest time range and calculation window.

This module deliberately resolves the run window before product expansion,
market data loading, factor evaluation, and event scheduling.  Downstream
modules consume the resolved DataTime objects instead of re-parsing date fields
or inventing their own warm-up semantics.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar, cast

import pandas as pd

from tools.data.types import DataTime
from tools.testers.backtest.engines.native.flow import Flow, Phase

from .base import ExecutableModule, FieldDefinition, FieldRef
from .factor import FactorModule, factors_for_config


_FACTOR_REF = FieldRef("factor", owner="FactorModule")
_FACTOR_ROLE_BINDINGS_REF = FieldRef("factor_role_bindings", owner="FactorModule")
_WARMUP_MODE_REF = FieldRef("warmup_mode", owner="FactorSignalModule")
_WARMUP_WINDOW_REF = FieldRef("warmup_window", owner="FactorSignalModule")


@dataclass(frozen=True)
class StrategyRunWindow:
    """Resolved strategy time window.

    `start_dt`/`end_dt` define the formal run and signal window.
    `warmup_window` only expands upstream data/evaluate lookback; it must not
    change formal signal clipping, performance windows, or result timestamps.
    """

    start_dt: DataTime | None
    end_dt: DataTime | None
    warmup_window: pd.Timedelta
    # Warm-up is only one component of a full temporal contract.  Keeping the
    # factor-only contract on the resolved window exposes its provenance to
    # downstream result consumers without changing formal signal timestamps.
    temporal_support: Any | None = None

    @property
    def is_bounded(self) -> bool:
        return self.start_dt is not None and self.end_dt is not None


@dataclass
class RunWindowStore:
    strategy_windows: dict[Any, Any] = field(default_factory=dict)
    envelope: tuple[Any, Any] | None = None

    def set_windows(self, windows: dict[Any, Any], envelope: tuple[Any, Any]) -> None:
        self.strategy_windows = windows
        self.envelope = envelope

    def window_for(self, strategy: Any) -> Any | None:
        return self.strategy_windows.get(strategy)


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
    strategy_windows: ClassVar[FieldRef[dict[Any, StrategyRunWindow]]] = FieldRef("strategy_windows")
    run_window_envelope: ClassVar[FieldRef[tuple[DataTime | None, DataTime | None]]] = FieldRef("run_window_envelope")

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
            public=True, label="样本切分", default=None, control_template="date", tab="time",
            chip_template="样本切分: {value}", tab_label="时间范围", tab_order=40,
            serialization={"display_order": 70},
        ),
        "strategy_windows": FieldDefinition(public=False, display_value_kind="strategy_scoped_mapping"),
        "run_window_envelope": FieldDefinition(public=False, display_value_kind="run_window"),
    }

    resolve_run_window: ClassVar[Flow] = Flow(
        "resolve_run_window",
        inputs=(
            start_date, end_date, start_time, end_time, timezone, time_precision,
            _FACTOR_REF, _FACTOR_ROLE_BINDINGS_REF, _WARMUP_MODE_REF, _WARMUP_WINDOW_REF,
        ),
        outputs=(strategy_windows, run_window_envelope),
        phase=Phase.PRE_REPLAY,
        order=10,
        compute=lambda state, ctx: _resolve_run_window(state, ctx),
        description="解析运行时间窗口",
    )

    flows: ClassVar[tuple[Flow, ...]] = (resolve_run_window,)


def _resolve_run_window(state, ctx) -> None:
    strategy_windows: dict[Any, StrategyRunWindow] = {}
    for strategy in state.strategy_configs:
        strategy_windows[strategy] = resolve_strategy_run_window(state.config_for(strategy))

    start_dt, end_dt = run_window_envelope(strategy_windows.values())

    store_run_windows(state, strategy_windows, (start_dt, end_dt))
    ctx.set(RunWindowModule.strategy_windows, strategy_windows)
    ctx.set(RunWindowModule.run_window_envelope, (start_dt, end_dt))

    request = getattr(state, "market_data_request", None)
    if isinstance(request, dict):
        request.setdefault("start_dt", start_dt)
        request.setdefault("end_dt", end_dt)


def resolve_strategy_run_window(config) -> StrategyRunWindow:
    start_dt, end_dt = strategy_run_window_datetimes(config)
    factors = factors_for_config(config)
    warmups = [warmup_window_for_strategy(config, factor) for factor in factors]
    warmup = max(warmups, default=_zero_warmup())
    temporal_support: Any | None = None
    if factors:
        from tools.factors.temporal_support import temporal_support_for_factor

        mode = str(config.get(_WARMUP_MODE_REF, "auto") or "auto").lower()
        contracts: dict[str, Any] = {}
        for factor, factor_warmup in zip(factors, warmups):
            # A fixed/none policy is the input support actually used by this
            # run; auto retains the native resolver's structural provenance.
            if mode in {"fixed", "none"}:
                support = temporal_support_for_factor(
                    factor,
                    factor_input_override_seconds=factor_warmup.total_seconds(),
                    factor_input_source_override=f"run_window:{mode}",
                )
            else:
                support = temporal_support_for_factor(factor)
            alias = str(getattr(factor, "alias", None) or getattr(factor, "name", None) or id(factor))
            contracts[alias] = support
        if len(contracts) == 1:
            temporal_support = next(iter(contracts.values()))
        else:
            temporal_support = {
                "schema_version": "temporal-support-set-v1",
                "support_status": "not_estimable",
                "factor_count": len(contracts),
                "warmup_window_seconds": warmup.total_seconds(),
                "contracts_by_factor": {
                    alias: support.to_dict() for alias, support in contracts.items()
                },
                "notes": [
                    "多个因子角色的输入支持分别记录；不能压成一个 HAC overlap contract。",
                ],
            }
    return StrategyRunWindow(
        start_dt=start_dt,
        end_dt=end_dt,
        warmup_window=warmup,
        temporal_support=temporal_support,
    )


def strategy_run_window_datetimes(config) -> tuple[DataTime | None, DataTime | None]:
    start_date = str(config.get(RunWindowModule.start_date, "") or "").strip()
    end_date = str(config.get(RunWindowModule.end_date, "") or "").strip()
    if not start_date or not end_date:
        return None, None
    precision = str(config.get(RunWindowModule.time_precision, "exact") or "exact")
    timezone = str(config.get(RunWindowModule.timezone, "Asia/Shanghai") or "Asia/Shanghai")
    if precision == "trading_day":
        return (
            DataTime.from_dict({"date": start_date}, precision="trading_day"),
            DataTime.from_dict({"date": end_date}, precision="trading_day"),
        )
    start_time = str(config.get(RunWindowModule.start_time, "00:00") or "00:00")
    end_time = str(config.get(RunWindowModule.end_time, "23:59") or "23:59")
    return (
        DataTime.from_dict({"date": start_date, "time": start_time, "tz": timezone}, precision="exact"),
        DataTime.from_dict({"date": end_date, "time": end_time, "tz": timezone}, precision="exact"),
    )


def run_window_key_for_config(config) -> tuple:
    start_dt, end_dt = strategy_run_window_datetimes(config)
    if start_dt is None or end_dt is None:
        return ("unbounded",)
    return (str(start_dt.precision), start_dt.ts, end_dt.ts)


def run_window_envelope(windows: Iterable[StrategyRunWindow]) -> tuple[DataTime | None, DataTime | None]:
    starts: list[DataTime] = []
    ends: list[DataTime] = []
    for window in windows:
        if window.start_dt is None or window.end_dt is None:
            return None, None
        starts.append(window.start_dt)
        ends.append(window.end_dt)
    if not starts or not ends:
        return None, None
    return (
        min(starts, key=lambda dt: cast(pd.Timestamp, dt.sort_key())),
        max(ends, key=lambda dt: cast(pd.Timestamp, dt.sort_key())),
    )


def run_window_envelope_for_strategies(strategies: Iterable[Any], state) -> tuple[DataTime | None, DataTime | None]:
    resolved = run_window_store_for(state).strategy_windows
    windows: list[StrategyRunWindow] = []
    for strategy in strategies:
        if strategy in resolved:
            windows.append(resolved[strategy])
        else:
            windows.append(resolve_strategy_run_window(state.config_for(strategy)))
    return run_window_envelope(windows)


def warmup_window_for_strategies(strategies: Iterable[Any], state) -> pd.Timedelta:
    resolved = run_window_store_for(state).strategy_windows
    values: list[pd.Timedelta] = []
    for strategy in strategies:
        if strategy in resolved:
            values.append(resolved[strategy].warmup_window)
        else:
            values.append(resolve_strategy_run_window(state.config_for(strategy)).warmup_window)
    return max(values) if values else _zero_warmup()


def run_window_store_for(state):
    return state.run_window_store


def store_run_windows(
    state,
    strategy_windows: dict[Any, StrategyRunWindow],
    envelope: tuple[DataTime | None, DataTime | None],
) -> None:
    run_window_store_for(state).set_windows(strategy_windows, envelope)


def run_window_envelope_for_state(state) -> tuple[DataTime | None, DataTime | None]:
    return run_window_store_for(state).envelope or (None, None)


def warmup_window_for_strategy(config, factor: Any | None = None) -> pd.Timedelta:
    mode = str(config.get(_WARMUP_MODE_REF, "auto") or "auto").lower()
    if mode == "none":
        return _zero_warmup()
    if mode == "fixed":
        return parse_warmup_window(config.get(_WARMUP_WINDOW_REF))
    if mode == "auto":
        return auto_warmup_window(factor) or _zero_warmup()
    return _zero_warmup()


def _zero_warmup() -> pd.Timedelta:
    return cast(pd.Timedelta, pd.Timedelta(0))


def parse_warmup_window(value: Any) -> pd.Timedelta:
    if value is None or str(value).strip() == "":
        return _zero_warmup()
    value_text = str(value).strip()
    if value_text.endswith("d"):
        value_text = f"{value_text[:-1]}D"
    try:
        delta = pd.Timedelta(value_text)
    except Exception as exc:
        raise ValueError(f"invalid fixed warmup_window={value!r}; expected a time value such as '30min' or '5d'") from exc
    if pd.isna(delta):
        raise ValueError(f"invalid fixed warmup_window={value!r}; expected a concrete time value")
    if delta < pd.Timedelta(0):
        raise ValueError(f"warmup_window must be non-negative, got {value!r}")
    return cast(pd.Timedelta, delta)


def auto_warmup_window(factor: Any) -> pd.Timedelta | None:
    """Infer expression warm-up for constant time-valued rolling/shift windows."""
    for obj in _factor_warmup_candidates(factor):
        if obj is None:
            continue
        required = getattr(obj, "required_warmup_window", None) or getattr(obj, "required_lookback", None)
        if callable(required):
            value = required()
            if value is None or str(value).strip() == "":
                continue
            return parse_warmup_window(value)
        if required is not None:
            if str(required).strip() == "":
                continue
            return parse_warmup_window(required)
        inferred = _infer_expr_warmup_window(obj)
        if inferred is not None:
            return inferred
    return None


def _factor_warmup_candidates(factor: Any) -> tuple[Any, ...]:
    """Return the resolved factor and its expression representations."""
    out: list[Any] = []
    seen: set[int] = set()

    def add(obj: Any) -> None:
        if obj is None:
            return
        obj_id = id(obj)
        if obj_id in seen:
            return
        seen.add(obj_id)
        out.append(obj)

    add(factor)
    for attr in ("expression", "_expr", "_source_expr", "_func_expr"):
        try:
            add(getattr(factor, attr, None))
        except Exception:
            continue
    return tuple(out)


def _infer_expr_warmup_window(expr: Any, seen: set[int] | None = None) -> pd.Timedelta | None:
    if expr is None:
        return None
    seen = seen or set()
    expr_id = id(expr)
    if expr_id in seen:
        return None
    seen.add(expr_id)

    cls_name = type(expr).__name__
    if cls_name == "RollingOp":
        window = _expr_window_to_timedelta(getattr(expr, "window", None))
        if window is None:
            return None
        child_window = _max_timedelta(
            _infer_expr_warmup_window(child, seen)
            for child in _expr_operands(expr)
            if child is not getattr(expr, "window", None)
        )
        return window + (child_window or _zero_warmup())
    if cls_name == "ShiftOp":
        shift = _expr_window_to_timedelta(getattr(expr, "periods", None))
        if shift is None:
            return None
        child_window = _infer_expr_warmup_window(getattr(expr, "operand", None), seen)
        return shift + (child_window or _zero_warmup())
    return _max_timedelta(_infer_expr_warmup_window(child, seen) for child in _expr_operands(expr))


def _expr_operands(expr: Any) -> tuple[Any, ...]:
    operands = getattr(expr, "_operands", None)
    if operands is None:
        operands = getattr(expr, "operands", ())
    if operands is None:
        return ()
    try:
        return tuple(cast(Iterable[Any], operands))
    except TypeError:
        return ()


def _expr_window_to_timedelta(expr: Any) -> pd.Timedelta | None:
    value = getattr(expr, "value", expr)
    if isinstance(value, (int, float)):
        return None
    freq_value = getattr(value, "value", None)
    if isinstance(freq_value, pd.Timedelta):
        return cast(pd.Timedelta, freq_value)
    try:
        return parse_warmup_window(value)
    except ValueError:
        return None


def _max_timedelta(values: Any) -> pd.Timedelta | None:
    concrete = [value for value in values if value is not None]
    return max(concrete) if concrete else None
