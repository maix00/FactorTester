"""Compile portfolio and cross-horizon auxiliary analyses."""

from __future__ import annotations

from typing import Any, Mapping

from tools.testers.ic_test.analysis_graph import ICAnalysisNode
from tools.testers.ic_test.core import ICCoreTest

from .identity import analysis_node


def compile_portfolio_analyses(
    settings: Mapping[str, Any],
    cores: tuple[ICCoreTest, ...],
) -> tuple[ICAnalysisNode, ...]:
    nodes: list[ICAnalysisNode] = []
    portfolio = _quantile_portfolio(settings)
    if portfolio is not None:
        nodes.extend(
            analysis_node(
                "quantile_portfolio_statistics",
                (core.core_test_ref,),
                {"portfolio": portfolio},
            )
            for core in cores
        )
    nodes.extend(
        analysis_node("forward_horizon_half_life", targets, {})
        for targets in _half_life_groups(cores)
    )
    return tuple(nodes)


def _quantile_portfolio(
    settings: Mapping[str, Any],
) -> dict[str, Any] | None:
    raw = settings.get("quantile_portfolio_statistics")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("quantile_portfolio_statistics must be an object")
    if not bool(raw.get("enabled", True)):
        return None
    return {key: value for key, value in sorted(raw.items()) if key != "enabled"}


def _half_life_groups(
    cores: tuple[ICCoreTest, ...],
) -> tuple[tuple[str, ...], ...]:
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
    result = [
        tuple(sorted(item.core_test_ref for item in values))
        for values in groups.values()
        if len({item.horizon for item in values}) >= 2
    ]
    return tuple(sorted(result))


__all__ = ["compile_portfolio_analyses"]
