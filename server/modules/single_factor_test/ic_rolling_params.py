"""Rolling IC window request validation.

The rolling unit is deliberately the number of valid signal observations.
Clock duration is retained only as descriptive span metadata after a window
has been selected; it is not a request mode and cannot change the window
length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from server.modules.single_factor_test.ic_diagnostics import temporal_support_from_dict


ROLLING_IC_SCHEMA = "ic-rolling-v3"


@dataclass(frozen=True)
class RollingWindowSpec:
    """One requested rolling window, expressed in signal observations."""

    mode: str
    value: int
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


def _spec_from_item(item: Any) -> RollingWindowSpec:
    if isinstance(item, dict):
        label = str(item.get("label") or "").strip()
        if "duration" in item or "span" in item:
            raise ValueError(
                "rolling window 只接受 signal_count；duration/span 已禁用"
            )
        if "signals" in item or "signal_count" in item or "k" in item:
            value = item.get("signals", item.get("signal_count", item.get("k")))
            count = _as_positive_signal_count(value)
            return RollingWindowSpec("signals", count, label or f"K={count}")
        raise ValueError("rolling window 对象必须包含 signals/signal_count/k")

    if isinstance(item, bool) or isinstance(item, (int, float)):
        count = _as_positive_signal_count(item)
        return RollingWindowSpec("signals", count, f"K={count}")

    text = str(item or "").strip()
    if not text:
        raise ValueError("rolling window 不能为空")
    if text.isdigit():
        count = _as_positive_signal_count(text)
        return RollingWindowSpec("signals", count, f"K={count}")
    raise ValueError(
        "rolling window 只接受 signal_count 整数；duration/clock_duration 已禁用"
    )


def normalize_rolling_window_specs(data: dict[str, Any]) -> list[RollingWindowSpec]:
    """Normalize signal-count windows and the legacy numeric scalar request.

    Accepted forms include ``[30, 60]`` and
    ``{"signal_counts": [30, 60]}``.  A scalar ``rolling_window`` remains a
    one-item compatibility request.  Duration-shaped input is rejected rather
    than silently converted, so an old client cannot reintroduce a clock-time
    selector.
    """

    raw = data.get("rolling_windows")
    if raw is None:
        raw = data.get("rolling_window")
    if raw is None or raw == "" or raw == []:
        return []

    if isinstance(raw, dict) and any(
        key in raw for key in ("signal_counts", "durations", "windows")
    ):
        if "durations" in raw:
            raise ValueError(
                "rolling_windows.durations 已禁用；请使用 signal_counts"
            )
        items: list[Any] = []
        for value in raw.get("signal_counts") or []:
            items.append({"signals": value})
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
        "rolling_window_unit": "signal_count",
        "signal_interval_seconds": signal_interval_seconds,
        "signal_interval_source": signal_interval_source,
        "requested_signal_count": int(spec.value),
        "resolved_k_signals": None,
        "resolution_status": "not_estimable",
        "resolution_reason": "missing signal interval",
    }
    if spec.mode != "signals":
        raise ValueError("rolling window mode 只允许 signals")
    count = int(spec.value)
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
