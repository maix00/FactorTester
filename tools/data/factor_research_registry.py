"""Shared registry and aggregation helpers for factor research results."""

from __future__ import annotations

from typing import Any


RESEARCH_METRIC_REGISTRY: dict[str, dict[str, Any]] = {
    "ic_mean": {"label": "IC Mean", "direction": "higher", "unit": "ratio", "default_test_type": "ic"},
    "ic_t_stat": {"label": "IC t-stat", "direction": "higher", "unit": "t", "default_test_type": "ic"},
    "ic_ir": {"label": "IC IR", "direction": "higher", "unit": "ratio", "default_test_type": "ic"},
    "ls_return": {"label": "Long-Short Return", "direction": "higher", "unit": "return", "default_test_type": "backtest"},
    "a1_return": {"label": "A1 Return", "direction": "higher", "unit": "return", "default_test_type": "backtest"},
    "a5_return": {"label": "A5 Return", "direction": "higher", "unit": "return", "default_test_type": "backtest"},
    "a1_a5_return_spread": {"label": "A1-A5 Spread", "direction": "higher", "unit": "return", "default_test_type": "backtest"},
    "a1_a5_label_return_spread": {"label": "A1-A5 Label Spread", "direction": "higher", "unit": "return", "default_test_type": "bucket_label"},
    "max_drawdown": {"label": "Max Drawdown", "direction": "higher", "unit": "return", "default_test_type": "backtest"},
    "best_type_score": {"label": "Best Type Score", "direction": "higher", "unit": "correlation", "default_test_type": "factor_type"},
    "product_count": {"label": "Product Count", "direction": "higher", "unit": "count", "default_test_type": "factor_evaluation"},
}


RESEARCH_RANK_PRESETS: dict[str, dict[str, Any]] = {
    "ic-stable": {
        "test_type": "ic",
        "metric": "ic_mean",
        "min_metrics": ("ic_mean=0", "ic_t_stat=2"),
        "max_metrics": (),
    },
    "costed-backtest": {
        "test_type": "backtest",
        "metric": "ls_return",
        "min_metrics": ("ls_return=0",),
        "max_metrics": (),
    },
    "costed-good": {
        "test_type": "backtest",
        "metric": "ls_return",
        "min_metrics": ("ls_return=0",),
        "max_metrics": (),
    },
    "bucket-monotonic": {
        "test_type": "bucket_label",
        "metric": "a1_a5_label_return_spread",
        "min_metrics": ("a1_a5_label_return_spread=0",),
        "max_metrics": (),
    },
    "monotonic-long-short": {
        "test_type": "backtest",
        "metric": "a1_a5_return_spread",
        "min_metrics": ("a1_a5_return_spread=0",),
        "max_metrics": (),
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
    base = dict(RESEARCH_RANK_PRESETS.get(preset, {}))
    resolved_test_type = test_type or str(base.get("test_type") or "")
    resolved_metric = metric or str(base.get("metric") or "ls_return")
    return {
        "test_type": resolved_test_type,
        "metric": resolved_metric,
        "min_metrics": [*list(base.get("min_metrics") or ()), *list(min_metrics)],
        "max_metrics": [*list(base.get("max_metrics") or ()), *list(max_metrics)],
    }


def parse_metric_thresholds(items: list[str] | tuple[str, ...]) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for item in items:
        key, value = split_metric_threshold(item)
        parsed[key] = value
    return parsed


def split_metric_threshold(item: str) -> tuple[str, float]:
    if ":" in item:
        key, value = item.split(":", 1)
    elif "=" in item:
        key, value = item.split("=", 1)
    else:
        raise ValueError("metric threshold must use KEY=VALUE")
    key = key.strip()
    if not key:
        raise ValueError("metric threshold key is required")
    return key, float(value)


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
        metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
        display_metric = metric or default_display_metric(run, metrics)
        if not display_metric or metric_float(metrics.get(display_metric)) is None:
            continue
        key = (
            str(run.get("factor_alias") or ""),
            str(run.get("test_type") or ""),
            str(run.get("product_group") or ""),
        )
        grouped.setdefault(key, []).append({**run, "_display_metric": display_metric})

    rows: list[dict[str, Any]] = []
    for (factor_alias, test_type, product_group), items in grouped.items():
        values: list[float] = []
        pass_count = 0
        period_keys: set[str] = set()
        failures = 0
        for item in items:
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            display_metric = str(item.get("_display_metric") or metric)
            value = metric_float(metrics.get(display_metric))
            if value is None:
                continue
            values.append(value)
            period_keys.add(research_period_key(str(item.get("start_date") or ""), bucket=bucket))
            passed = run_passes_metric_thresholds(metrics, min_metrics=min_metrics, max_metrics=max_metrics)
            if passed:
                pass_count += 1
            else:
                failures += 1
        if not values:
            continue
        rows.append(
            {
                "factor_alias": factor_alias,
                "test_type": test_type,
                "product_group": product_group,
                "periods": len(period_keys) if bucket != "run" else len(values),
                "pass_count": pass_count,
                "run_count": len(values),
                "avg": sum(values) / len(values),
                "worst": min(values),
                "best": max(values),
                "failures": failures,
            }
        )
    rows.sort(key=lambda row: (str(row["factor_alias"]), str(row["test_type"]), str(row["product_group"])))
    return rows


def research_period_key(start_date: str, *, bucket: str) -> str:
    text = str(start_date or "")
    if bucket == "run":
        return text
    if bucket == "year":
        return text[:4]
    if bucket == "month":
        return text[:7]
    if bucket == "quarter":
        try:
            year = int(text[:4])
            month = int(text[5:7])
        except ValueError:
            return text[:7] or text
        return f"{year}-Q{((month - 1) // 3) + 1}"
    return text


def run_passes_metric_thresholds(metrics: dict[str, Any], *, min_metrics: dict[str, float], max_metrics: dict[str, float]) -> bool:
    for key, threshold in min_metrics.items():
        value = metric_float(metrics.get(key))
        if value is None or value < threshold:
            return False
    for key, threshold in max_metrics.items():
        value = metric_float(metrics.get(key))
        if value is None or value > threshold:
            return False
    return True


def metric_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def default_display_metric(run: dict[str, Any], metrics: dict[str, Any]) -> str:
    test_type = str(run.get("test_type") or "")
    if test_type == "factor_type":
        return "best_type_score" if "best_type_score" in metrics else "best_type"
    if test_type == "factor_evaluation":
        return "product_count" if "product_count" in metrics else "series_count"
    if test_type == "backtest":
        return "ls_return" if "ls_return" in metrics else "a1_return"
    if test_type == "ic":
        return "ic_mean"
    if test_type == "bucket_label":
        return "a1_a5_label_return_spread" if "a1_a5_label_return_spread" in metrics else "ic_mean"
    return ""
