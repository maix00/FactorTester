"""Presentation-only helpers for remote research metric responses."""

from __future__ import annotations

from typing import Any


# Kept for offline labels and backwards-compatible CLI helper tests. The server
# remains authoritative and returns its registry through HTTP.
RESEARCH_METRIC_REGISTRY: dict[str, dict[str, str]] = {
    "ic_mean": {
        "label": "IC Mean",
        "direction": "higher",
        "unit": "ratio",
        "default_test_type": "ic",
    },
    "ic_t_stat": {
        "label": "IC t-stat",
        "direction": "higher",
        "unit": "t",
        "default_test_type": "ic",
    },
    "ls_return": {
        "label": "Long-Short Return",
        "direction": "higher",
        "unit": "return",
        "default_test_type": "backtest",
    },
}

_RANK_PRESETS: dict[str, dict[str, Any]] = {
    "ic-stable": {
        "test_type": "ic",
        "metric": "ic_mean",
        "min_metrics": ("ic_mean=0", "ic_t_stat=2"),
    },
    "costed-backtest": {
        "test_type": "backtest",
        "metric": "ls_return",
        "min_metrics": ("ls_return=0",),
    },
    "costed-good": {
        "test_type": "backtest",
        "metric": "ls_return",
        "min_metrics": ("ls_return=0",),
    },
    "bucket-monotonic": {
        "test_type": "bucket_label",
        "metric": "a1_a5_label_return_spread",
        "min_metrics": ("a1_a5_label_return_spread=0",),
    },
    "monotonic-long-short": {
        "test_type": "backtest",
        "metric": "a1_a5_return_spread",
        "min_metrics": ("a1_a5_return_spread=0",),
    },
}


def resolve_research_rank_preset(
    *,
    preset: str,
    test_type: str,
    metric: str,
    min_metrics: list[str] | tuple[str, ...],
    max_metrics: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    base = _RANK_PRESETS.get(preset, {})
    return {
        "test_type": test_type or str(base.get("test_type") or ""),
        "metric": metric or str(base.get("metric") or "ls_return"),
        "min_metrics": [
            *list(base.get("min_metrics") or ()),
            *list(min_metrics),
        ],
        "max_metrics": [
            *list(base.get("max_metrics") or ()),
            *list(max_metrics),
        ],
    }


def parse_metric_thresholds(
    items: list[str] | tuple[str, ...],
) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for item in items:
        separator = ":" if ":" in item else "=" if "=" in item else ""
        if not separator:
            raise ValueError("metric threshold must use KEY=VALUE")
        key, raw_value = item.split(separator, 1)
        key = key.strip()
        if not key:
            raise ValueError("metric threshold key is required")
        parsed[key] = float(raw_value)
    return parsed


def default_display_metric(
    run: dict[str, Any],
    metrics: dict[str, Any],
) -> str:
    test_type = str(run.get("test_type") or "")
    choices = {
        "factor_type": ("best_type_score", "best_type"),
        "factor_evaluation": ("product_count", "series_count"),
        "backtest": ("ls_return", "a1_return"),
        "ic": ("ic_mean",),
        "bucket_label": ("a1_a5_label_return_spread", "ic_mean"),
    }
    return next(
        (name for name in choices.get(test_type, ()) if name in metrics),
        "",
    )


def research_stability_rows(
    runs: list[dict[str, Any]],
    *,
    metric: str,
    min_metrics: dict[str, float],
    max_metrics: dict[str, float],
    bucket: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for run in runs:
        metrics = run.get("metrics")
        metrics = metrics if isinstance(metrics, dict) else {}
        selected = metric or default_display_metric(run, metrics)
        if not selected or _number(metrics.get(selected)) is None:
            continue
        key = (
            str(run.get("factor_alias") or ""),
            str(run.get("test_type") or ""),
            str(run.get("product_group") or ""),
        )
        grouped.setdefault(key, []).append({**run, "_metric": selected})

    rows: list[dict[str, Any]] = []
    for key, items in grouped.items():
        values: list[float] = []
        periods: set[str] = set()
        pass_count = 0
        for item in items:
            metrics = item.get("metrics") or {}
            value = _number(metrics.get(item["_metric"]))
            if value is None:
                continue
            values.append(value)
            periods.add(_period(str(item.get("start_date") or ""), bucket))
            if _passes(metrics, min_metrics, max_metrics):
                pass_count += 1
        if values:
            rows.append({
                "factor_alias": key[0],
                "test_type": key[1],
                "product_group": key[2],
                "periods": len(values) if bucket == "run" else len(periods),
                "pass_count": pass_count,
                "run_count": len(values),
                "avg": sum(values) / len(values),
                "worst": min(values),
                "best": max(values),
                "failures": len(values) - pass_count,
            })
    return sorted(
        rows,
        key=lambda row: (
            row["factor_alias"],
            row["test_type"],
            row["product_group"],
        ),
    )


def _passes(
    metrics: dict[str, Any],
    minimums: dict[str, float],
    maximums: dict[str, float],
) -> bool:
    return all(
        (value := _number(metrics.get(key))) is not None and value >= threshold
        for key, threshold in minimums.items()
    ) and all(
        (value := _number(metrics.get(key))) is not None and value <= threshold
        for key, threshold in maximums.items()
    )


def _number(value: Any) -> float | None:
    try:
        return None if isinstance(value, bool) or value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _period(start_date: str, bucket: str) -> str:
    if bucket == "year":
        return start_date[:4]
    if bucket == "month":
        return start_date[:7]
    if bucket == "quarter" and len(start_date) >= 7:
        try:
            return f"{start_date[:4]}-Q{(int(start_date[5:7]) - 1) // 3 + 1}"
        except ValueError:
            pass
    return start_date
