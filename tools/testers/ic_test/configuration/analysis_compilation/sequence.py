"""Compile single-series auxiliary analyses and their downstream nodes."""

from __future__ import annotations

from typing import Any, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisNode
from tools.testers.ic_test.core import ICCoreTest

from .identity import analysis_node
from .parameters import period_specs, positive_integers, rolling_windows


def compile_sequence_analyses(
    settings: Mapping[str, Any],
    cores: tuple[ICCoreTest, ...],
    primary_cores: tuple[ICCoreTest, ...],
) -> tuple[ICAnalysisNode, ...]:
    nodes: list[ICAnalysisNode] = []
    windows = rolling_windows(settings)
    if windows:
        parameters = {"rolling_windows": [
            {"unit": "signals", "value": value} for value in windows
        ]}
        nodes.extend(
            analysis_node(
                "rolling_ic_stability", (core.core_test_ref,), parameters,
            )
            for core in cores
        )
    intervals = positive_integers(settings.get("ic_decay_lags"), minimum=1)
    if intervals:
        parameters = {"sampling_intervals": list(intervals)}
        nodes.extend(
            analysis_node(
                "ic_resample_stability", (core.core_test_ref,), parameters,
            )
            for core in primary_cores
        )
    requested_periods = settings.get("ic_periods")
    periods = period_specs(requested_periods)
    parameters = {"periods": periods} if requested_periods is not None else {}
    nodes.extend(
        analysis_node("period_diagnostics", (core.core_test_ref,), parameters)
        for core in primary_cores
    )
    maximum_lag = _autocorrelation_lag(settings)
    if maximum_lag is not None:
        parameters = {"maximum_lag": maximum_lag}
        nodes.extend(
            analysis_node(
                "ic_autocorrelation", (core.core_test_ref,), parameters,
            )
            for core in primary_cores
        )
    return tuple(nodes)


def _autocorrelation_lag(settings: Mapping[str, Any]) -> int | None:
    raw = settings.get("ic_autocorrelation")
    if raw is False or raw == "off":
        return None
    if isinstance(raw, dict):
        raw = raw.get("maximum_lag")
    if raw is None:
        raw = settings.get("ic_autocorrelation_lag", 20)
    return positive_integers((raw,), minimum=1)[0]

__all__ = ["compile_sequence_analyses"]
