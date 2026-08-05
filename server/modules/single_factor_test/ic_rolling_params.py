"""Rolling IC window request and factor-frequency resolution.

This module contains only the request contract.  Rolling statistics live in
``ic_rolling`` so that request validation can be tested independently from
the numerical diagnostics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from tools.data.types import DataFreq
from server.modules.single_factor_test.ic_diagnostics import temporal_support_from_dict


ROLLING_IC_SCHEMA = "ic-rolling-v2"


@dataclass(frozen=True)
class RollingWindowSpec:
    """One requested rolling window before factor-specific resolution."""

    mode: str
    value: int | float | str
    label: str

    @property
    def key(self) -> str:
        return f"{self.mode}:{self.label}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "value": self.value,
            "label": self.label,
            "key": self.key,
        }


def _as_positive_signal_count(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rolling signal window 非法: {value}") from exc
    if not math.isfinite(number) or number < 2 or int(number) != number:
        raise ValueError("rolling signal window 必须是 >=2 的整数")
    return int(number)


def _as_duration(value: Any) -> DataFreq:
    try:
        duration = DataFreq(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rolling duration 非法: {value}") from exc
    if duration.value <= pd.Timedelta(0):
        raise ValueError("rolling duration 必须为正")
    return duration


def _spec_from_item(item: Any) -> RollingWindowSpec:
    if isinstance(item, dict):
        label = str(item.get("label") or "").strip()
        if "signals" in item or "signal_count" in item or "k" in item:
            value = item.get("signals", item.get("signal_count", item.get("k")))
            count = _as_positive_signal_count(value)
            return RollingWindowSpec("signals", count, label or f"K={count}")
        if "duration" in item or "span" in item:
            raw = item.get("duration", item.get("span"))
            duration = _as_duration(raw)
            return RollingWindowSpec("duration", duration.name, label or duration.name)
        raise ValueError("rolling window 对象必须包含 signals 或 duration")

    if isinstance(item, bool) or isinstance(item, (int, float)):
        count = _as_positive_signal_count(item)
        return RollingWindowSpec("signals", count, f"K={count}")

    text = str(item or "").strip()
    if not text:
        raise ValueError("rolling window 不能为空")
    if text.isdigit():
        count = _as_positive_signal_count(text)
        return RollingWindowSpec("signals", count, f"K={count}")
    duration = _as_duration(text)
    return RollingWindowSpec("duration", duration.name, duration.name)


def normalize_rolling_window_specs(data: dict[str, Any]) -> list[RollingWindowSpec]:
    """Normalize multi-window and legacy scalar requests.

    Accepted forms include ``[30, 60, "1h", "1d"]`` and the explicit object
    form ``{"signal_counts": [30], "durations": ["1h"]}``.  A scalar
    ``rolling_window`` remains a one-item compatibility request.
    """

    raw = data.get("rolling_windows")
    if raw is None:
        raw = data.get("rolling_window")
    if raw is None or raw == "" or raw == []:
        return []

    if isinstance(raw, dict) and any(
        key in raw for key in ("signal_counts", "durations", "windows")
    ):
        items: list[Any] = []
        for value in raw.get("signal_counts") or []:
            items.append({"signals": value})
        for value in raw.get("durations") or []:
            items.append({"duration": value})
        items.extend(raw.get("windows") or [])
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]

    specs: list[RollingWindowSpec] = []
    seen: set[str] = set()
    for item in items:
        spec = _spec_from_item(item)
        if spec.key in seen:
            continue
        specs.append(spec)
        seen.add(spec.key)
    return specs


def signal_interval_seconds(
    support_payload: dict[str, Any] | None,
    fallback_seconds: float | None,
) -> tuple[float | None, str]:
    """Resolve the immutable temporal contract before factor-frequency fallback."""

    support = temporal_support_from_dict(support_payload)
    if support is not None and support.signal_interval_seconds:
        return float(support.signal_interval_seconds), "temporal_support"
    if fallback_seconds and fallback_seconds > 0:
        return float(fallback_seconds), "factor_frequency"
    return None, "missing"


def resolve_window_spec(
    spec: RollingWindowSpec,
    *,
    signal_interval_seconds: float | None,
    signal_interval_source: str,
) -> dict[str, Any]:
    """Resolve one request for a particular factor signal frequency."""

    result = {
        **spec.to_dict(),
        "signal_interval_seconds": signal_interval_seconds,
        "signal_interval_source": signal_interval_source,
        "requested_duration_seconds": None,
        "resolved_k_signals": None,
        "resolution_status": "not_estimable",
        "resolution_reason": "missing signal interval",
    }
    if spec.mode == "signals":
        count = int(spec.value)
        result.update({
            "resolved_k_signals": count,
            "resolution_status": "estimable",
            "resolution_reason": None,
        })
    else:
        duration = _as_duration(spec.value)
        requested_seconds = float(duration.value.total_seconds())
        result["requested_duration_seconds"] = requested_seconds
        if signal_interval_seconds is None or signal_interval_seconds <= 0:
            return result
        if requested_seconds < signal_interval_seconds:
            result["resolution_reason"] = (
                "requested duration is shorter than one signal interval"
            )
            return result
        count = max(2, int(math.ceil(requested_seconds / signal_interval_seconds)))
        result.update({
            "resolved_k_signals": count,
            "resolution_status": "estimable",
            "resolution_reason": None,
        })

    count = result["resolved_k_signals"]
    if signal_interval_seconds is not None and count is not None:
        result["expected_endpoint_span_seconds"] = (count - 1) * signal_interval_seconds
        result["expected_coverage_span_seconds"] = count * signal_interval_seconds
    else:
        result["expected_endpoint_span_seconds"] = None
        result["expected_coverage_span_seconds"] = None
    return result


__all__ = [
    "ROLLING_IC_SCHEMA", "RollingWindowSpec", "normalize_rolling_window_specs",
    "resolve_window_spec", "signal_interval_seconds",
]
