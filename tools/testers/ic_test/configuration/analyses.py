"""Translate existing IC authoring fields into typed analysis nodes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisNode
from tools.testers.ic_test.core import ICCoreTest


def analysis_nodes_from_settings(
    settings: Mapping[str, Any],
    core_tests: Iterable[ICCoreTest],
    *,
    primary_core_refs: Iterable[str] = (),
) -> tuple[ICAnalysisNode, ...]:
    cores = tuple(core_tests)
    primary_refs = frozenset(primary_core_refs)
    primary_cores = tuple(
        core for core in cores if core.core_test_ref in primary_refs
    )
    nodes: list[ICAnalysisNode] = []
    rolling_windows = _rolling_windows(settings)
    if rolling_windows:
        parameters = {"rolling_windows": [
            {"unit": "signals", "value": value} for value in rolling_windows
        ]}
        nodes.extend(
            _node("rolling_ic_stability", (core.core_test_ref,), parameters)
            for core in cores
        )
    decay_intervals = _positive_integers(settings.get("ic_decay_lags"), minimum=1)
    if decay_intervals:
        parameters = {"sampling_intervals": list(decay_intervals)}
        nodes.extend(
            _node("ic_resample_stability", (core.core_test_ref,), parameters)
            for core in primary_cores
        )
    requested_periods = settings.get("ic_periods")
    periods = _period_specs(requested_periods)
    parameters = {"periods": periods} if requested_periods is not None else {}
    nodes.extend(
        _node("period_diagnostics", (core.core_test_ref,), parameters)
        for core in primary_cores
    )
    maximum_lag = _autocorrelation_lag(settings)
    if maximum_lag is not None:
        parameters = {"maximum_lag": maximum_lag}
        nodes.extend(
            _node("ic_autocorrelation", (core.core_test_ref,), parameters)
            for core in primary_cores
        )
    portfolio = _quantile_portfolio(settings)
    if portfolio is not None:
        parameters = {"portfolio": portfolio}
        nodes.extend(
            _node(
                "quantile_portfolio_statistics", (core.core_test_ref,), parameters,
            )
            for core in cores
        )
    for targets in _half_life_groups(cores):
        nodes.append(_node("forward_horizon_half_life", targets, {}))
    return tuple(sorted(nodes, key=lambda item: item.node_id))


def _rolling_windows(settings: Mapping[str, Any]) -> tuple[int, ...]:
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


def _positive_integers(value: Any, *, minimum: int) -> tuple[int, ...]:
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


def _period_specs(value: Any) -> list[dict[str, Any]]:
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


def _autocorrelation_lag(settings: Mapping[str, Any]) -> int | None:
    raw = settings.get("ic_autocorrelation")
    if raw is False or raw == "off":
        return None
    if isinstance(raw, dict):
        raw = raw.get("maximum_lag")
    if raw is None:
        raw = settings.get("ic_autocorrelation_lag", 20)
    values = _positive_integers((raw,), minimum=1)
    return values[0]


def _quantile_portfolio(settings: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = settings.get("quantile_portfolio_statistics")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("quantile_portfolio_statistics must be an object")
    if not bool(raw.get("enabled", True)):
        return None
    return {
        key: value for key, value in sorted(raw.items()) if key != "enabled"
    }


def _half_life_groups(cores: tuple[ICCoreTest, ...]) -> tuple[tuple[str, ...], ...]:
    groups: dict[tuple[Any, ...], list[ICCoreTest]] = {}
    for core in cores:
        key = (
            core.product_scope_ref,
            core.factor_ref,
            core.entry_delay_bars,
            core.method,
            core.return_price_basis,
        )
        groups.setdefault(key, []).append(core)
    result: list[tuple[str, ...]] = []
    for values in groups.values():
        if len({item.horizon for item in values}) < 2:
            continue
        result.append(tuple(sorted(item.core_test_ref for item in values)))
    return tuple(sorted(result))


def _node(
    analysis_type: str,
    target_refs: tuple[str, ...],
    parameters: Mapping[str, Any],
) -> ICAnalysisNode:
    identity = {
        "analysis_type": analysis_type,
        "target_refs": sorted(target_refs),
        "parameters": parameters,
    }
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    node_id = f"ic-analysis:v1:{hashlib.sha256(encoded).hexdigest()}"
    return ICAnalysisNode(
        node_id=node_id,
        analysis_type=analysis_type,
        target_refs=tuple(sorted(target_refs)),
        parameters=parameters,
    )


__all__ = ["analysis_nodes_from_settings"]
