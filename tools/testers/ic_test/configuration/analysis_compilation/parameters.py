"""Normalization for legacy flat auxiliary-analysis fields."""

from __future__ import annotations

from typing import Any, Mapping


def positive_integers(value: Any, *, minimum: int) -> tuple[int, ...]:
    if value is None or value == "" or value == []:
        return ()
    values = value if isinstance(value, (list, tuple)) else (value,)
    result: set[int] = set()
    for item in values:
        if isinstance(item, bool):
            raise ValueError(f"analysis values must be integers >= {minimum}")
        try:
            number = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"analysis values must be integers >= {minimum}"
            ) from exc
        if number < minimum or number != item:
            raise ValueError(f"analysis values must be integers >= {minimum}")
        result.add(number)
    return tuple(sorted(result))


def rolling_windows(settings: Mapping[str, Any]) -> tuple[int, ...]:
    raw = settings.get("rolling_windows")
    if raw is None:
        raw = settings.get("rolling_window")
    if raw is None or raw == "" or raw == []:
        return ()
    if isinstance(raw, dict):
        if "durations" in raw:
            raise ValueError("rolling windows only accept signal counts")
        values = list(raw.get("signal_counts") or ())
        values.extend(raw.get("windows") or ())
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = [raw]
    normalized: set[int] = set()
    for item in values:
        value = item
        if isinstance(item, dict):
            value = item.get("signals", item.get("signal_count", item.get("k")))
        if isinstance(value, bool):
            raise ValueError("rolling window must be an integer >= 2")
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("rolling window must be an integer >= 2") from exc
        if count < 2 or count != value:
            raise ValueError("rolling window must be an integer >= 2")
        normalized.add(count)
    return tuple(sorted(normalized))


def period_specs(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else (value,)
    result: list[dict[str, Any]] = []
    for item in values:
        raw = {"rule": item, "label": item} if isinstance(item, str) else item
        if not isinstance(raw, dict):
            raise ValueError("IC period specification must be text or an object")
        rule = str(raw.get("rule") or raw.get("label") or "").strip()
        if not rule:
            raise ValueError("IC period specification requires a rule")
        result.append({
            "rule": rule,
            "label": str(raw.get("label") or rule),
            "min_signal_observations": int(raw.get("min_signal_observations", 2)),
            "min_periods": int(raw.get("min_periods", 3)),
        })
    return sorted(result, key=lambda item: (
        item["rule"], item["label"], item["min_signal_observations"],
        item["min_periods"],
    ))


__all__ = ["period_specs", "positive_integers", "rolling_windows"]
