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
from tools.factors.FactorExpr import PanelTimeline, build_panel_timeline


@dataclass(frozen=True)
class PreparedEvaluationBatch:
    """Reusable data boundary for several root-evaluation chunks.

    A bounded root chunk should control expression-intermediate memory, but it
    must not cause the same product panels and union timeline to be loaded and
    rebuilt for every chunk.  This object owns only the immutable input side of
    a batch; each call to :func:`evaluate_factors` still gets a fresh
    expression cache and therefore releases root intermediates normally.
    """

    products: tuple[Any, ...]
    freq: DataFreq
    start_dt: Any
    end_dt: Any
    warmup_window: Any
    # ``None`` means that only the timeline was retained.  Callers may choose
    # this mode when their own cache lifecycle already bounds source panels;
    # the IC scheduler normally keeps one partition-wide superset projection
    # and releases it explicitly after all root chunks complete.
    preloaded: dict[Any, pd.DataFrame] | None
    panel_timeline: PanelTimeline

    def assert_compatible(
        self, *, products: Sequence[Any], freq: DataFreq, start_dt: Any,
        end_dt: Any, warmup_window: Any,
    ) -> None:
        if tuple(products) != self.products or freq != self.freq:
            raise ValueError("prepared evaluation batch products/frequency mismatch")
        if start_dt != self.start_dt or end_dt != self.end_dt:
            raise ValueError("prepared evaluation batch window mismatch")
        if warmup_window != self.warmup_window:
            raise ValueError("prepared evaluation batch warmup mismatch")


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


def shared_cache_keys_for_factors(factors: Sequence[Any]) -> frozenset[tuple]:
    """Return the structural keys cached across these evaluation roots."""
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


def prepare_evaluation_batch(
    factors: Sequence[Any], *, products: Sequence[Any], freq: DataFreq | str,
    start_dt: Any, end_dt: Any, warmup_window: Any = None,
    retain_preloaded: bool = True,
) -> PreparedEvaluationBatch:
    """Load panels and build the union timeline once for a root partition.

    The IC scheduler evaluates a large frequency partition in bounded chunks.
    The expression cache must be chunk-local for memory safety, while the
    source panels and their product-union timeline are identical across those
    chunks.  Preparing this boundary separately removes repeated index union,
    sort, and observed-mask construction without changing expression results.
    """

    factors = list(factors)
    if not factors:
        raise ValueError("prepare_evaluation_batch requires at least one factor")
    resolved_freq = DataFreq(freq)
    eligible = _eligible_products(list(products), resolved_freq)
    if not eligible:
        raise ValueError(f"no products provide frequency {resolved_freq.name}")
    preloaded = _preload(
        factors, eligible, resolved_freq, start_dt, end_dt, warmup_window,
    )
    return PreparedEvaluationBatch(
        products=tuple(eligible),
        freq=resolved_freq,
        start_dt=start_dt,
        end_dt=end_dt,
        warmup_window=warmup_window,
        preloaded=preloaded if retain_preloaded else None,
        panel_timeline=build_panel_timeline(eligible, resolved_freq, preloaded),
    )


def release_evaluation_batch(prepared: PreparedEvaluationBatch) -> int:
    """Release DataHub panels belonging to a completed frequency batch.

    ``ProductDataView`` stores the full source frame plus projected and raw-axis
    variants in the process-wide ``datameta`` cache.  Dropping Python references
    to ``prepared`` is not sufficient for a long multi-frequency IC run because
    those cache entries have a several-minute TTL.  The view's base resource
    key is a stable prefix for all variants, so invalidate the prefix once the
    partition is complete.  The worker owns its DataHub singleton, therefore
    this cannot evict another worker's cache.
    """
    from tools.data.hub import DataHub

    hub = DataHub.get_instance()
    released = 0
    for product in prepared.products:
        view = getattr(product, prepared.freq.name, None)
        if view is None:
            continue
        try:
            source = view.get_current_source()
            prefix = view._resource_id_for_source(source)
        except (AttributeError, TypeError, ValueError):
            # Keep compatibility with lightweight test/sentinel products and
            # with products whose source disappeared during cancellation.
            continue
        released += hub.invalidate_prefix("datameta", prefix)
    return released


def evaluate_factors(
    factors: Sequence[Any], *, products: Sequence[Any], freq: DataFreq | str,
    start_dt: Any, end_dt: Any, warmup_window: Any = None,
    prepared: PreparedEvaluationBatch | None = None,
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
    if prepared is None:
        prepared = prepare_evaluation_batch(
            factors, products=eligible, freq=resolved_freq,
            start_dt=start_dt, end_dt=end_dt, warmup_window=warmup_window,
        )
    else:
        prepared.assert_compatible(
            products=eligible, freq=resolved_freq, start_dt=start_dt,
            end_dt=end_dt, warmup_window=warmup_window,
        )
    preloaded = prepared.preloaded
    if preloaded is None:
        # Retaining only the immutable timeline avoids a second large resident
        # panel across all chunks.  DataHub still serves these same product
        # frames from its cache, while each chunk owns only the references it
        # needs for expression evaluation.
        preloaded = _preload(
            factors, eligible, resolved_freq, start_dt, end_dt, warmup_window,
        )
    context = EvaluationBatchContext(
        products=prepared.products, freq=resolved_freq, start_dt=start_dt, end_dt=end_dt,
        warmup_window=warmup_window, preloaded=preloaded,
        panel_timeline=prepared.panel_timeline,
        shared_cache={}, shared_cache_keys=shared_cache_keys_for_factors(factors),
    )
    for factor in factors:
        factor.evaluate(
            eligible, freq=resolved_freq, start_dt=start_dt, end_dt=end_dt,
            warmup_window=warmup_window, _evaluation_context=context,
        )
    return context
