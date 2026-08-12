"""Explicit temporal-support contracts for factor and IC diagnostics.

Warm-up and HAC answer related but different questions:

* ``factor_input_support`` is the amount of history required to evaluate a
  factor at one signal timestamp.  The native run-window resolver owns that
  calculation and this module records its provenance.
* ``label_horizon`` describes how far the forward target extends.
* ``holding_support`` and ``decay_support`` describe any additional overlap
  introduced by a strategy or target construction.

The sum of those supports is an explicit *overlap support* bound.  It is not
inferred from an alias.  A HAC lag can be derived automatically only when all
components and the signal interval are known.  Unknown support is represented
as ``not_estimable`` rather than silently falling back to a legacy ``N/$F``
rule.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

import pandas as pd


SCHEMA_VERSION = "temporal-support-v1"
_UNKNOWN = object()


def _as_seconds(value: Any, *, source_freq: Any | None = None) -> float | None:
    """Convert an explicit duration or bar count to non-negative seconds."""

    if value is None:
        return None
    if isinstance(value, pd.Timedelta):
        seconds = value.total_seconds()
    else:
        if hasattr(value, "value") and not isinstance(value, (str, bytes)):
            nested = getattr(value, "value", _UNKNOWN)
            if nested is not _UNKNOWN and nested is not value:
                value = nested
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if source_freq is None:
                return None
            freq_seconds = _as_seconds(source_freq)
            if freq_seconds is None:
                return None
            seconds = abs(float(value)) * freq_seconds
        else:
            try:
                seconds = pd.Timedelta(str(value)).total_seconds()
            except (TypeError, ValueError):
                return None
    if not math.isfinite(float(seconds)):
        return None
    return abs(float(seconds))


def _freq_seconds(value: Any) -> float | None:
    """Convert a DataFreq-like value without interpreting integers as bars."""

    if value is None:
        return None
    if isinstance(value, pd.Timedelta):
        seconds = value.total_seconds()
    else:
        nested = getattr(value, "value", _UNKNOWN)
        if nested is not _UNKNOWN and nested is not value:
            value = nested
        if isinstance(value, pd.Timedelta):
            seconds = value.total_seconds()
        else:
            try:
                seconds = pd.Timedelta(str(value)).total_seconds()
            except (TypeError, ValueError):
                return None
    return float(seconds) if math.isfinite(float(seconds)) and seconds > 0 else None


@dataclass(frozen=True)
class TemporalInference:
    """Detailed result of expression-history inspection."""

    seconds: float | None
    known: bool
    source: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemporalSupport:
    """JSON-serializable temporal-dependence contract.

    ``None`` means the component was not declared or could not be resolved;
    zero is an explicit declaration that the component contributes no support.
    """

    factor_input_support_seconds: float | None
    signal_interval_seconds: float | None
    label_horizon_seconds: float | None
    holding_support_seconds: float | None
    decay_support_seconds: float | None
    factor_input_source: str
    signal_interval_source: str
    label_horizon_source: str
    holding_support_source: str
    decay_support_source: str
    support_status: str
    unknown_components: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @classmethod
    def from_components(
        cls,
        *,
        factor_input_support_seconds: float | None,
        signal_interval_seconds: float | None,
        label_horizon_seconds: float | None,
        holding_support_seconds: float | None,
        decay_support_seconds: float | None,
        factor_input_source: str = "unknown",
        signal_interval_source: str = "unknown",
        label_horizon_source: str = "unknown",
        holding_support_source: str = "unknown",
        decay_support_source: str = "unknown",
        notes: Iterable[str] = (),
    ) -> "TemporalSupport":
        values = {
            "factor_input_support": factor_input_support_seconds,
            "signal_interval": signal_interval_seconds,
            "label_horizon": label_horizon_seconds,
            "holding_support": holding_support_seconds,
            "decay_support": decay_support_seconds,
        }
        unknown = tuple(name for name, value in values.items() if value is None)
        support_status = "estimable" if not unknown and signal_interval_seconds > 0 else "not_estimable"
        return cls(
            factor_input_support_seconds=_normalise_seconds(factor_input_support_seconds),
            signal_interval_seconds=_normalise_seconds(signal_interval_seconds),
            label_horizon_seconds=_normalise_seconds(label_horizon_seconds),
            holding_support_seconds=_normalise_seconds(holding_support_seconds),
            decay_support_seconds=_normalise_seconds(decay_support_seconds),
            factor_input_source=factor_input_source,
            signal_interval_source=signal_interval_source,
            label_horizon_source=label_horizon_source,
            holding_support_source=holding_support_source,
            decay_support_source=decay_support_source,
            support_status=support_status,
            unknown_components=unknown,
            notes=tuple(str(note) for note in notes if str(note).strip()),
        )

    @property
    def hac_estimable(self) -> bool:
        return self.support_status == "estimable" and self.overlap_support_seconds is not None

    @property
    def overlap_support_seconds(self) -> float | None:
        components = (
            self.factor_input_support_seconds,
            self.label_horizon_seconds,
            self.holding_support_seconds,
            self.decay_support_seconds,
        )
        if any(value is None for value in components):
            return None
        return float(sum(value for value in components if value is not None))

    @property
    def overlap_lag_signal_steps(self) -> int | None:
        overlap = self.overlap_support_seconds
        interval = self.signal_interval_seconds
        if overlap is None or interval is None or interval <= 0:
            return None
        return max(0, int(math.ceil(overlap / interval)) - 1)

    @property
    def overlap_support_components_seconds(self) -> dict[str, float | None]:
        """Return every component used by the automatic HAC bound.

        Factor input support is a raw-data dependence bound here.  It is not
        the number of observations and is not inferred from ``N`` or ``$F``.
        """

        return {
            "factor_input": self.factor_input_support_seconds,
            "label_horizon": self.label_horizon_seconds,
            "holding": self.holding_support_seconds,
            "decay": self.decay_support_seconds,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "factor_input_support_seconds": self.factor_input_support_seconds,
            "signal_interval_seconds": self.signal_interval_seconds,
            "label_horizon_seconds": self.label_horizon_seconds,
            "holding_support_seconds": self.holding_support_seconds,
            "decay_support_seconds": self.decay_support_seconds,
            "overlap_support_seconds": self.overlap_support_seconds,
            "overlap_support_components_seconds": self.overlap_support_components_seconds,
            "overlap_support_definition": "factor_input + label_horizon + holding + decay",
            "overlap_lag_formula": "ceil(overlap_support_seconds / signal_interval_seconds) - 1",
            "overlap_lag_signal_steps": self.overlap_lag_signal_steps,
            "sources": {
                "factor_input_support": self.factor_input_source,
                "signal_interval": self.signal_interval_source,
                "label_horizon": self.label_horizon_source,
                "holding_support": self.holding_support_source,
                "decay_support": self.decay_support_source,
            },
            "support_status": self.support_status,
            "unknown_components": list(self.unknown_components),
            "notes": list(self.notes),
        }


def _normalise_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"temporal support must be a finite non-negative duration, got {value!r}")
    return value


def _factor_expression(factor: Any) -> Any | None:
    if factor is None:
        return None
    for attr in ("_source_expr", "_func_expr", "_expr", "expression"):
        try:
            expression = getattr(factor, attr, None)
        except Exception:
            expression = None
        if expression is not None:
            return expression
    return factor


def _operands(expr: Any) -> tuple[Any, ...]:
    values = getattr(expr, "_operands", None)
    if values is None:
        values = getattr(expr, "operands", ())
    if values is None:
        return ()
    try:
        return tuple(values)
    except TypeError:
        return ()


def _window_seconds(value: Any, source_freq: Any | None) -> float | None:
    return _as_seconds(value, source_freq=source_freq)


def _infer_expression(expr: Any, source_freq: Any | None, seen: set[int]) -> TemporalInference:
    if expr is None:
        return TemporalInference(None, False, "unknown", ("missing expression",))
    expr_id = id(expr)
    if expr_id in seen:
        return TemporalInference(None, False, "unknown", ("expression cycle",))
    seen.add(expr_id)

    cls_name = type(expr).__name__
    if cls_name in {"ParamRef", "Parameter", "WindowParam", "FactorParam"}:
        return TemporalInference(None, False, "unknown", (f"unresolved {cls_name}",))

    raw_operands = _operands(expr)
    if cls_name == "RollingOp":
        window = _window_seconds(getattr(expr, "window", None), source_freq)
        if window is None:
            return TemporalInference(None, False, "unknown", ("rolling window is not concrete",))
        data_start = int(getattr(expr, "_data_start", 1))
        n_data = int(getattr(expr, "_n_data", max(0, len(raw_operands) - data_start)))
        children = raw_operands[data_start:data_start + n_data]
        child_results = [_infer_expression(child, source_freq, seen.copy()) for child in children]
        if any(not result.known for result in child_results):
            notes = [note for result in child_results for note in result.notes]
            return TemporalInference(None, False, "unknown", tuple(notes))
        child_support = max((result.seconds or 0.0 for result in child_results), default=0.0)
        return TemporalInference(window + child_support, True, "expression:rolling", ())

    if cls_name == "RollingExpr":
        window = _window_seconds(getattr(expr, "_window", None), source_freq)
        if window is None:
            return TemporalInference(None, False, "unknown", ("rolling window is not concrete",))
        child = _infer_expression(getattr(expr, "_data", None), source_freq, seen.copy())
        if not child.known:
            return child
        return TemporalInference(window + (child.seconds or 0.0), True, "expression:rolling", child.notes)

    if cls_name == "ShiftOp":
        periods_value = getattr(getattr(expr, "periods", None), "value", getattr(expr, "periods", None))
        periods = _window_seconds(periods_value, source_freq)
        if periods is None:
            return TemporalInference(None, False, "unknown", ("shift periods are not concrete",))
        child = _infer_expression(getattr(expr, "operand", None), source_freq, seen.copy())
        if not child.known:
            return child
        return TemporalInference(periods + (child.seconds or 0.0), True, "expression:shift", child.notes)

    # A leaf such as ColumnRef or ConstExpr has no historical support.  A
    # normal composite node takes the maximum support of parallel branches.
    if not raw_operands:
        return TemporalInference(0.0, True, "expression:leaf", ())
    child_results = [_infer_expression(child, source_freq, seen.copy()) for child in raw_operands]
    if any(not result.known for result in child_results):
        notes = [note for result in child_results for note in result.notes]
        return TemporalInference(None, False, "unknown", tuple(notes))
    return TemporalInference(
        max((result.seconds or 0.0 for result in child_results), default=0.0),
        True,
        "expression:parallel",
        tuple(note for result in child_results for note in result.notes),
    )


def infer_factor_input_support(factor: Any) -> TemporalInference:
    """Describe factor input support while preserving the native warm-up result.

    The resolver in ``run_window`` remains the behavior authority.  We call it
    for the concrete duration and use the structural walk only to distinguish a
    known zero-history leaf from an unresolved/dynamic window.
    """

    expression = _factor_expression(factor)
    source_freq = getattr(factor, "_source_freq", None)
    if source_freq is None:
        source_freq = getattr(getattr(factor, "family", None), "_source_freq", None)
    structural = _infer_expression(expression, source_freq, set())
    try:
        from tools.testers.backtest.modules.run_window import auto_warmup_window

        native = auto_warmup_window(factor)
    except Exception:
        native = None
    if native is not None:
        seconds = _as_seconds(native)
        if seconds is not None:
            return TemporalInference(seconds, True, "run_window.auto_warmup_window", structural.notes)
    if structural.known:
        return TemporalInference(structural.seconds or 0.0, True, structural.source, structural.notes)
    return structural


def temporal_support_for_factor(
    factor: Any,
    *,
    label_horizon_seconds: float | None = None,
    label_horizon_source: str = "unknown",
    holding_support_seconds: float | None = None,
    holding_support_source: str = "unknown",
    decay_support_seconds: float | None = None,
    decay_support_source: str = "unknown",
    factor_input_override_seconds: float | None = _UNKNOWN,  # type: ignore[assignment]
    factor_input_source_override: str | None = None,
) -> TemporalSupport:
    """Build a support contract for a resolved factor."""

    inferred = infer_factor_input_support(factor)
    if factor_input_override_seconds is not _UNKNOWN:
        factor_seconds = _normalise_seconds(factor_input_override_seconds)
        factor_source = factor_input_source_override or "run_window.override"
    else:
        factor_seconds = inferred.seconds
        factor_source = inferred.source
    signal_freq = getattr(factor, "freq", None)
    if signal_freq is None:
        signal_freq = getattr(factor, "_freq", None)
    signal_seconds = _freq_seconds(signal_freq)
    signal_source = "factor.freq" if signal_seconds is not None else "unknown"
    notes = list(inferred.notes)
    return TemporalSupport.from_components(
        factor_input_support_seconds=factor_seconds,
        signal_interval_seconds=signal_seconds,
        label_horizon_seconds=label_horizon_seconds,
        holding_support_seconds=holding_support_seconds,
        decay_support_seconds=decay_support_seconds,
        factor_input_source=factor_source,
        signal_interval_source=signal_source,
        label_horizon_source=label_horizon_source,
        holding_support_source=holding_support_source,
        decay_support_source=decay_support_source,
        notes=notes,
    )


def temporal_support_for_ic(
    factor: Any,
    *,
    returns_factor: Any | None = None,
    lag: int = 0,
    label_horizon_seconds: float | None = None,
    label_horizon_source: str | None = None,
) -> TemporalSupport:
    """Build the explicit contract used by a cross-sectional IC calculation."""

    signal_seconds = _freq_seconds(getattr(factor, "freq", None) or getattr(factor, "_freq", None))
    if label_horizon_seconds is None and returns_factor is not None:
        label_seconds = _freq_seconds(getattr(returns_factor, "freq", None))
        if label_seconds is not None:
            label_horizon_seconds = label_seconds + abs(int(lag)) * (signal_seconds or 0.0)
            label_horizon_source = label_horizon_source or f"NextReturns.freq+IC_lag({int(lag)})"
    return temporal_support_for_factor(
        factor,
        label_horizon_seconds=label_horizon_seconds,
        label_horizon_source=label_horizon_source or "unknown",
        holding_support_seconds=0.0,
        holding_support_source="IC:no_holding_support",
        decay_support_seconds=0.0,
        decay_support_source="IC:no_decay_support",
    )


@dataclass(frozen=True)
class HACResolution:
    """Result of strict overlap-based HAC lag resolution."""

    lag: int | None
    source: str
    status: str
    reason: str | None = None
    formula: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hac_lag": self.lag,
            "hac_lag_source": self.source,
            "hac_status": self.status,
            "hac_reason": self.reason,
            "hac_lag_formula": self.formula,
        }


def resolve_hac_lag(
    support: TemporalSupport,
    *,
    requested_lag: int | None = None,
    max_lag: int = 512,
) -> HACResolution:
    """Resolve a lag without alias-based or legacy fallback inference."""

    if max_lag < 0:
        raise ValueError("max_lag must be non-negative")
    if requested_lag is not None:
        if requested_lag < 0:
            raise ValueError("requested_lag must be non-negative")
        return HACResolution(
            min(int(requested_lag), max_lag),
            "explicit",
            "manual",
            formula="explicit requested lag clipped to max_lag",
        )
    if not support.hac_estimable:
        missing = ", ".join(support.unknown_components) or "temporal support"
        return HACResolution(
            None,
            "temporal_support",
            "not_estimable",
            f"missing or unknown: {missing}",
            formula="ceil((factor_input + label + holding + decay) / signal_interval) - 1",
        )
    lag = support.overlap_lag_signal_steps
    if lag is None:
        return HACResolution(
            None,
            "temporal_support",
            "not_estimable",
            "signal interval or overlap support is unknown",
            formula="ceil((factor_input + label + holding + decay) / signal_interval) - 1",
        )
    return HACResolution(
        min(lag, max_lag),
        "temporal_support_overlap",
        "estimable",
        formula="ceil((factor_input + label + holding + decay) / signal_interval) - 1",
    )
