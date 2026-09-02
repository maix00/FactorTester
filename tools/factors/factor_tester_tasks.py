"""Task handlers dispatched by FactorTester.dispatch(task_name, **kwargs).

Each function here is the exact logic that used to live as a FactorTester
method body -- moved out, with `self` renamed to `state: FactorTesterState`,
so FactorTester itself can be a thin dispatcher with no business logic of
its own. Behavior is unchanged from the pre-refactor methods.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Set

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.data.types import DataColumn

def tqdm(iterable, *args: Any, **kwargs: Any):
    try:
        progress = getattr(import_module("tqdm"), "tqdm")
    except ModuleNotFoundError:  # pragma: no cover - exercised in slim worker envs
        return iterable
    return progress(iterable, *args, **kwargs)

if TYPE_CHECKING:
    from tools.data.types import DataTime
    from tools.factors.Factors import Factor
    from tools.factors.factor_tester_state import FactorTesterState
    from tools.factors.FactorRunResult import FactorRunResult
    from tools.products.Product import Product


def delete(state: "FactorTesterState") -> None:
    from tools.parameters.Parameter import Parameter  # noqa: F401  (kept for parity with prior import-time side effects)
    for f in list(state.factors):
        try:
            if f.family is not None:
                for param in list(f.family.params):
                    if not param.alias.startswith('$'):
                        try:
                            param.delete()
                        except Exception:
                            pass
            f.clear()
            f.delete()
        except Exception:
            pass
    with state._results_lock:
        for result in state.results.values():
            result.clear_caches()
        state.results.clear()
    state.factors.clear()
    state.products = set()
    state.all_products = set()
    try:
        state.logger.info("factor_tester_deleted", extra={"tester_alias": state.alias})
    except Exception:
        pass


def get_result(state: "FactorTesterState", factor: "Factor") -> "FactorRunResult":
    from tools.factors.FactorRunResult import FactorRunResult
    with state._results_lock:
        if factor not in state.results:
            state.results[factor] = FactorRunResult(factor=factor)
        return state.results[factor]


def discard_result(state: "FactorTesterState", factor: "Factor", *, clear_factor: bool = True) -> None:
    with state._results_lock:
        result = state.results.pop(factor, None)
    if result is not None:
        result.clear_caches()
    if state.last_group_factor is factor:
        state.last_group_factor = None
    if clear_factor:
        factor.clear()


def update_time_range(state: "FactorTesterState", start_dt: "DataTime", end_dt: "DataTime") -> None:
    state.start_dt = start_dt
    state.end_dt = end_dt
    state.start_date = start_dt.ts
    state.end_date = end_dt.ts
    state.logger.info(f"Time range updated to {start_dt} - {end_dt}")


def sift_product(state: "FactorTesterState", sift_func: Callable[["Product"], bool]) -> None:
    new_products = set()
    for product in state.products:
        if sift_func(product):
            new_products.add(product)
    state.products = new_products


def sift_product_by_empty_data(state: "FactorTesterState") -> None:
    new_products = set()
    for product in state.products:
        df = product.get_some_data(copy=False)
        if not df.empty and max(df[DataColumn.VOLUME.name]) > 0:
            new_products.add(product)
    state.products = new_products
    state.sift_product_by_empty_data_bool = True


def sift_product_by_volumes(
    state: "FactorTesterState", ratio: Optional[float] = None,
    time_col: Optional[Any] = None, time_range: Optional[Any] = None,
) -> Set["Product"]:
    if ratio is None:
        return state.products
    if not state.sift_product_by_empty_data_bool:
        sift_product_by_empty_data(state)
    results = {}
    for product in state.products:
        sum_volume = product.get_slices(
            target_cols=DataColumn.VOLUME, time_col=time_col, time_range=time_range, copy=False,
        ).sum().values
        if sum_volume == 0:
            continue
        results[product] = sum_volume
    sorted_products = sorted(results, key=lambda x: results[x], reverse=True)
    return set(sorted_products[:int(len(sorted_products) * ratio)])


def calc_factor(
    state: "FactorTesterState", factors: "Factor|List[Factor]",
    parallel: bool = True, max_workers: int = 4,
    warmup_window: pd.Timedelta | None = None,
) -> None:
    from tools.factors.Factors import Factor
    from tools.factors.FactorTester import _active_tester

    if isinstance(factors, Factor):
        factors = [factors]
    state.factors = factors

    # A declared common source frequency gives us a precise compatibility
    # boundary for a shared preload/intermediate cache.  Factors that still
    # rely on automatic source inference deliberately stay on the legacy path.
    from collections import defaultdict
    from tools.data.types import DataFreq
    from tools.factors.evaluation import evaluate_factors

    compatible: dict[str, list["Factor"]] = defaultdict(list)
    remaining: list["Factor"] = []
    for factor in factors:
        raw_freq = (
            getattr(factor, "_source_freq", None)
            or getattr(getattr(factor, "family", None), "_source_freq", None)
        )
        if raw_freq is None:
            remaining.append(factor)
            continue
        compatible[DataFreq(raw_freq).name].append(factor)

    for batch in compatible.values():
        if len(batch) > 1:
            evaluate_factors(
                batch, products=state.products, freq=batch[0]._source_freq
                or batch[0].family._source_freq,
                start_dt=state.start_dt, end_dt=state.end_dt,
                warmup_window=warmup_window,
            )
        else:
            remaining.extend(batch)
    factors = remaining
    if not factors:
        return

    if parallel and len(factors) > 1:
        desc = f'Calculate {len(factors)} factors for {len(state.products)} products'
        token = _active_tester.get()

        def _calc_one(factor: "Factor") -> None:
            _active_tester.set(token)
            factor.evaluate(
                state.products, start_dt=state.start_dt, end_dt=state.end_dt,
                warmup_window=warmup_window,
            )

        with ThreadPoolExecutor(max_workers=min(max_workers, len(factors))) as pool:
            futures = {pool.submit(_calc_one, f): f for f in factors}
            for future in tqdm(as_completed(futures), total=len(futures), desc=desc):
                exc = future.exception()
                if exc is not None:
                    for fut in futures:
                        fut.cancel()
                    raise RuntimeError(f"calc_factor: {futures[future].alias} 计算失败") from exc
    else:
        for factor in tqdm(factors, desc=f'Calculate factors for {len(state.products)} products'):
            factor.evaluate(
                state.products, start_dt=state.start_dt, end_dt=state.end_dt,
                warmup_window=warmup_window,
            )


def ic_stats(state: "FactorTesterState", ic_series: pd.Series) -> pd.Series:
    from tools.factors.tester_calc.single_factor_test.ic import ic_stats as _ic_stats
    return _ic_stats(ic_series)


def resolve_factor(state: "FactorTesterState", factor_alias: str) -> Optional["Factor"]:
    return next(
        (f for f in state.factors if f.alias == factor_alias or f.name == factor_alias),
        None,
    )

# Note: the old group-calendar functions (collect_group_factor_freqs,
# resolve_group_calendar_freq*, build_group_calendar_index,
# merge_group_calendar_indices) were dropped here rather than carried
# forward -- build_group_calendar_index imported from
# tools.factors.tester_calc.single_factor_test.group.core, a module deleted
# in issue-114 step 0, so it has been dead/uncallable code ever since; its
# only caller was the old per-product-selection group-test pipeline being
# replaced in this same change (see backtester.py).
