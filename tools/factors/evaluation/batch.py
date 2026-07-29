"""Evaluate compatible Factor roots with one preload and one shared DAG cache.

The cache belongs to a single batch only.  It is deliberately not attached to
Factor or FactorTester state, so a value can never leak across products,
windows, source frequencies, or independent research runs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import pandas as pd

from tools.data.types import DataFreq
from tools.factors.FactorExpr import build_panel_timeline


@dataclass(frozen=True)
class EvaluationBatchContext:
    """The immutable compatibility boundary for a shared expression cache."""

    products: tuple[Any, ...]
    freq: DataFreq
    start_dt: Any
    end_dt: Any
    warmup_window: Any
    preloaded: dict[Any, pd.DataFrame]
    panel_timeline: Any
    shared_cache: dict[tuple, pd.DataFrame]
    shared_cache_keys: frozenset[tuple]

    def assert_compatible(
        self,
        *, products: Sequence[Any], freq: DataFreq, start_dt: Any,
        end_dt: Any, warmup_window: Any,
    ) -> None:
        if tuple(products) != self.products or freq != self.freq:
            raise ValueError("evaluation batch context products/frequency mismatch")
        if start_dt != self.start_dt or end_dt != self.end_dt:
            raise ValueError("evaluation batch context window mismatch")
        if warmup_window != self.warmup_window:
            raise ValueError("evaluation batch context warmup mismatch")


def _walk_keys(expr: Any) -> Iterable[tuple]:
    """Yield each structural node once for one root expression."""
    seen: set[tuple] = set()

    def visit(node: Any) -> Iterable[tuple]:
        key = node._structural_key()
        if key in seen:
            return
        seen.add(key)
        yield key
        for child in getattr(node, "_operands", ()):
            yield from visit(child)

    yield from visit(expr)


def _shared_keys(factors: Sequence[Any]) -> frozenset[tuple]:
    counts: Counter[tuple] = Counter()
    for factor in factors:
        counts.update(_walk_keys(factor._expr))
    # Caching leaves is harmless but does not save meaningful compute or IO:
    # preload is already shared.  Restrict this to expression nodes with at
    # least one operand, which is where repeated computation is material.
    return frozenset(
        key for factor in factors for key in _walk_keys(factor._expr)
        if counts[key] > 1 and len(key) > 1
    )


def _eligible_products(products: Sequence[Any], freq: DataFreq) -> list[Any]:
    return [
        product for product in products
        if any(getattr(available, "name", str(available)) == freq.name
               for available in product.list_available_freqs())
    ]


def _preload(
    factors: Sequence[Any], products: Sequence[Any], freq: DataFreq,
    start_dt: Any, end_dt: Any, warmup_window: Any,
) -> dict[Any, pd.DataFrame]:
    from tools.data.views.ProductDataView import ProductDataView

    columns = sorted({
        ref.column.name for factor in factors for ref in factor._expr.column_refs
    })
    if not columns:
        return {}
    preloaded: dict[Any, pd.DataFrame] = {}
    for product in products:
        view: ProductDataView = getattr(product, freq.name)
        data = view.get_and_adjust_cols(
            columns, copy=False, start_dt=start_dt, end_dt=end_dt,
            warmup_window=warmup_window,
        )
        if not data.empty:
            preloaded[(product, freq.name)] = data
    return preloaded


def evaluate_factors(
    factors: Sequence[Any], *, products: Sequence[Any], freq: DataFreq | str,
    start_dt: Any, end_dt: Any, warmup_window: Any = None,
) -> EvaluationBatchContext:
    """Evaluate roots serially with shared intermediates under one context.

    Callers may parallelise *separate* contexts, but not roots in this batch:
    a plain dictionary is intentionally used to keep cache ownership simple
    and deterministic.
    """
    factors = list(factors)
    if not factors:
        raise ValueError("evaluate_factors requires at least one factor")
    resolved_freq = DataFreq(freq)
    eligible = _eligible_products(list(products), resolved_freq)
    if not eligible:
        raise ValueError(f"no products provide frequency {resolved_freq.name}")
    preloaded = _preload(factors, eligible, resolved_freq, start_dt, end_dt, warmup_window)
    context = EvaluationBatchContext(
        products=tuple(eligible), freq=resolved_freq, start_dt=start_dt, end_dt=end_dt,
        warmup_window=warmup_window, preloaded=preloaded,
        panel_timeline=build_panel_timeline(eligible, resolved_freq, preloaded),
        shared_cache={}, shared_cache_keys=_shared_keys(factors),
    )
    for factor in factors:
        factor.evaluate(
            eligible, freq=resolved_freq, start_dt=start_dt, end_dt=end_dt,
            warmup_window=warmup_window, _evaluation_context=context,
        )
    return context
