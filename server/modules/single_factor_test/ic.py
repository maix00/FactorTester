"""IC computation for immutable research RunSpecs."""
import hashlib
import threading
import traceback
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

from server.modules.shared.factor_tester_runtime import (
    create_isolated_factor_tester_for_run,
    selection_from_request,
)
from server.modules.shared.factor_data_coverage import require_factor_data_coverage
from server.modules.single_factor_test.ic_params import (
    SCALE_AWARE_HORIZON_BASE,
    describe_forward_horizon_sampling,
    parse_forward_horizon_bases,
    parse_ic_params,
    resolve_forward_horizons,
    run_window_datetimes,
)
from server.modules.single_factor_test.ic_response import (
    _extract_product_names,
    build_ic_response,
)
from server.modules.single_factor_test.ic_rolling import (
    normalize_rolling_window_specs,
)
from server.services.eval_progress import (
    count_evaluation_nodes,
)
from server.services.eval_progress import (
    setup as setup_progress,
)
from server.services.eval_progress import (
    teardown as teardown_progress,
)
from server.services.factor_registry import factor_from_alias
from server.services.session_runtime import user_obj_for_name
from tools.data.types import DataFreq
from tools.data.types.time_index import DataIndex
from tools.factors import Factor
from tools.factors.FactorFamily import FactorFamily
from tools.factors.FactorTester import _active_tester
from tools.factors.formula_identity import (
    is_factor_reference,
    require_frozen_factor,
)
from tools.factors.temporal_support import temporal_support_for_ic
from tools.factors.tester_calc.CrossSectionIC import CrossSectionIC
from tools.factors.tester_calc.CrossSectionPearsonIC import CrossSectionPearsonIC
from tools.factors.tester_calc.NextReturns import NextReturns
from tools.factors.tester_calc.single_factor_test.ic import (
    annotate_ic_temporal_support,
    build_ic_factor,
    collect_ic_result,
    discard_ic_factor,
    ic_evaluation_end_dt,
)
from tools.factors.tester_calc.single_factor_test.ic_diagnostics import (
    expected_sign_for_factor,
    normalize_ic_metric_selection,
)

# A single frequency partition can contain one root for every factor ×
# horizon × delay combination.  Evaluating the whole partition at once keeps
# every intermediate panel alive until the final root is collected.  That is
# especially expensive for intraday panels.  Keep the cache benefit within a
# bounded chunk, then release the roots before evaluating the next chunk.
IC_EVALUATION_BATCH_ROOTS = 8
# A long intraday IC sequence is retained for rolling diagnostics, but its
# values do not need float64 precision after the point statistics have been
# computed.  Keep short/daily sequences lossless so small-run response payloads
# remain byte-for-byte familiar.
IC_SERIES_STORAGE_COMPRESSION_MIN_POINTS = 50_000


def screening_signal_index(factor: Factor, ic_series: pd.Series) -> pd.DatetimeIndex:
    """Return one timestamp per declared factor signal for quick screening.

    IC intermediates can retain source-bar rows even when the factor declares
    a daily signal frequency.  The screening portfolio must use that declared
    signal timeline, keyed by exchange trading day for daily factors and by
    the explicit signal level for intraday factors.
    """
    freq = getattr(factor, "freq", None)
    if freq is not None and getattr(freq, "is_day_multiple", lambda: False)():
        target = DataIndex(ic_series.index).trading_day_index()
    else:
        target = DataIndex(ic_series.index).signal_index
    target = pd.DatetimeIndex(target)
    return target.drop_duplicates(keep="last") if target.has_duplicates else target


def _evaluation_batch_size(
    source_freq: DataFreq | None = None,
    *,
    partition_size: int | None = None,
) -> int:
    """Return the bounded root count used by one evaluation batch.

    The setting is intentionally global rather than tied to a factor's
    horizon parameter: `$F` determines the source-frequency partition and a
    chunk is only a memory/throughput boundary.  A small positive override is
    useful for deployments with different panel sizes.
    """

    try:
        import settings

        configured = int(getattr(settings, "IC_EVALUATION_BATCH_ROOTS", IC_EVALUATION_BATCH_ROOTS))
    except (ImportError, TypeError, ValueError):
        configured = IC_EVALUATION_BATCH_ROOTS
    # Intraday panels have many more signal rows than daily panels.  Keep only
    # two horizon × delay roots alive at once: one root loses all shared FE/RE
    # cache benefit and repeats the same expensive factor evaluation, while a
    # large batch multiplies rank/return intermediates and peak RSS.  Two is a
    # bounded compromise that preserves shared expression evaluation without
    # changing any statistic or dropping any root.
    if source_freq is not None:
        try:
            if (
                not source_freq.is_day_multiple()
                and (partition_size is None or int(partition_size) > 2)
            ):
                return min(2, max(1, configured))
        except (AttributeError, TypeError, ValueError):
            pass
    return max(1, configured)

# Compatibility aliases for internal callers that imported the pre-split names.
_parse_ic_params = parse_ic_params
_forward_horizon_bases = parse_forward_horizon_bases
_resolve_forward_horizons = resolve_forward_horizons
_run_window_datetimes = run_window_datetimes


def _factor_execution_refs(data: dict[str, Any]) -> dict[str, str]:
    """Return exact committed factor identities frozen at submission.

    Never synthesize a report identity from an alias, N/$F, or a family
    fingerprint. The immutable RunSpec's complete frozen factor records are
    the sole navigation and execution identity source.
    """
    raw: dict[str, str] = {}
    run_spec = data.get("run_spec")
    if isinstance(run_spec, dict):
        shared = run_spec.get("configuration", {}).get("shared", {})
        factors = shared.get("factors") if isinstance(shared, dict) else None
        if isinstance(factors, list):
            raw = _refs_from_frozen_factors(factors)
    if not isinstance(raw, dict):
        return {}
    output: dict[str, str] = {}
    for alias, target_ref in raw.items():
        alias_text = str(alias or "").strip()
        target_text = str(target_ref or "").strip()
        if not alias_text:
            continue
        if not is_factor_reference(target_text):
            continue
        output[alias_text] = target_text
    return output


def _refs_from_frozen_factors(values: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values if isinstance(values, (list, tuple)) else ():
        try:
            frozen = require_frozen_factor(item)
        except (TypeError, ValueError):
            continue
        result[frozen["alias"]] = frozen["ref"]
    return result


# ═══════════════════════════════════════════════════════════════
# IC 计算状态容器
# ═══════════════════════════════════════════════════════════════

class _ICComputeResult:
    """IC 计算结果的中间状态。"""
    def __init__(self):
        self.series_by_column_lag: Dict[str, Dict[int, pd.Series]] = {}
        self.stats_by_column_lag: Dict[str, Dict[int, pd.Series]] = {}
        self.series_by_column_horizon_lag: Dict[str, Dict[str, Dict[int, pd.Series]]] = {}
        self.stats_by_column_horizon_lag: Dict[str, Dict[str, Dict[int, pd.Series]]] = {}
        self.primary_horizon_by_column: Dict[str, str] = {}
        self.factor_by_column: Dict[str, Factor] = {}
        self.method_by_column: Dict[str, str] = {}
        self.temporal_support_by_column_lag: Dict[str, Dict[int, dict[str, Any]]] = {}
        self.temporal_support_by_column_horizon_lag: Dict[
            str, Dict[str, Dict[int, dict[str, Any]]]
        ] = {}
        # IC roots for one factor commonly share the same signal timestamps.
        # Reusing immutable DatetimeIndex objects avoids retaining one large
        # MultiIndex per horizon/delay series.
        self.series_index_cache: Dict[str, List[pd.DatetimeIndex]] = {}
        self.selected_product_names: List[str] = []
        # Scalar quick grouped-return results keyed by factor/horizon/delay.
        # Store the compact result, not the FE/RE panels, so supporting all
        # requested horizons does not multiply the IC job's retained memory.
        self.quantile_portfolio_statistics_by_column_horizon_lag: Dict[
            str, Dict[str, Dict[int, dict[str, Any]]]
        ] = {}


class _ICCancelled(RuntimeError):
    """Raised when an async IC job has been cancelled."""


def _compact_ic_series(
    series: pd.Series,
    *,
    display_alias: str,
    index_cache: Dict[str, List[pd.DatetimeIndex]],
    preserve_precision: bool,
) -> pd.Series:
    """Use a shared signal axis and bounded precision for retained IC roots.

    IC consumers only use the signal timestamp, not the auxiliary DAY1/source
    levels carried by the evaluator's MultiIndex.  Rebuilding that axis as an
    immutable DatetimeIndex removes repeated product/session labels.  Long
    non-primary roots are stored as float32 after their float64 statistics have
    already been calculated; primary series stay float64 for report fidelity.
    """
    index = series.index
    if isinstance(index, pd.MultiIndex):
        signal_name = next(
            (name for name in index.names if name and str(name).startswith("_SIGNAL")),
            None,
        )
        timestamps = pd.DatetimeIndex(
            index.get_level_values(signal_name if signal_name is not None else -1),
            name=signal_name or index.names[-1],
        )
    else:
        timestamps = pd.DatetimeIndex(index)

    # Index.equals is only evaluated against the handful of roots belonging
    # to this factor; it makes reuse safe even when different horizons have
    # different endpoints or missing signal slots.
    candidates = index_cache.setdefault(display_alias, [])
    shared_index = next(
        (candidate for candidate in candidates if candidate.equals(timestamps)),
        None,
    )
    if shared_index is None:
        shared_index = timestamps
        candidates.append(shared_index)

    values = series.to_numpy(
        dtype=(np.float64 if preserve_precision else np.float32),
        copy=True,
    )
    return pd.Series(values, index=shared_index, name=series.name)


def _ic_lag_from_payload(payload: Dict[str, Any]) -> int:
    try:
        return int(payload.get("Lag", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _temporal_support_for_payload(
    payload: Dict[str, Any], factor_list: List[Factor],
) -> Any | None:
    """Resolve the explicit IC temporal contract for one batch root."""

    if not factor_list:
        return None
    return temporal_support_for_ic(
        factor_list[0],
        returns_factor=payload.get("RE"),
        lag=_ic_lag_from_payload(payload),
    )


def _batch_factor_warmup(
    supports: Iterable[Any | None],
) -> pd.Timedelta | None:
    """Return a common safe warm-up only when every root declares one."""

    values: list[float] = []
    support_list = list(supports)
    for support in support_list:
        seconds = getattr(support, "factor_input_support_seconds", None)
        if seconds is None:
            return None
        values.append(float(seconds))
    if not values:
        return None
    return pd.Timedelta(seconds=max(values))


def _maximum_label_support(
    partition: Iterable[tuple[tuple, List[Factor], Factor, Any, Any | None]],
) -> Any | None:
    """Select the partition root with the largest forward-label horizon."""

    supports = [item[4] for item in partition if item[4] is not None]
    if not supports:
        return None
    return max(
        supports,
        key=lambda support: float(
            getattr(support, "label_horizon_seconds", 0.0) or 0.0
        ),
    )


def _merge_ic_result(
    compute: _ICComputeResult,
    key: tuple,
    result: Tuple,
    tester: Any,
    primary_ic_lag: int,
    primary_horizons: Dict[str, str],
    *,
    all_products: list[Any] | None = None,
    quantile_portfolio_config: Dict[str, Any] | None = None,
):
    """将一组 IC 结果合并到 compute 中。"""
    horizon_name = str(key[-4])
    lag_i = int(key[-3])
    method = str(key[-2])
    display_alias = str(key[-1])
    primary_horizon = primary_horizons[display_alias]
    factor_list, ic_series, stats, re_table, fe_table, data_present_mask = result
    is_primary_series = (
        horizon_name == primary_horizon and lag_i == primary_ic_lag
    )
    if (
        is_primary_series
        or not isinstance(ic_series.index, pd.DatetimeIndex)
        or (
            not is_primary_series
            and len(ic_series) >= IC_SERIES_STORAGE_COMPRESSION_MIN_POINTS
        )
    ):
        ic_series = _compact_ic_series(
            ic_series,
            display_alias=display_alias,
            index_cache=compute.series_index_cache,
            preserve_precision=is_primary_series,
        )
    for factor in factor_list:
        # ``collect_ic_result`` returns an owned series.  Keep that single
        # object in the horizon/delay map instead of copying a long intraday
        # IC sequence once more for every index.  The primary map intentionally
        # shares the same reference: response construction only reads these
        # series (rolling/replace/dropna all create their own views/copies), so
        # this removes a second multi-megabyte allocation per root.
        compute.series_by_column_horizon_lag.setdefault(display_alias, {}).setdefault(horizon_name, {})[lag_i] = ic_series
        compute.stats_by_column_horizon_lag.setdefault(display_alias, {}).setdefault(horizon_name, {})[lag_i] = stats
        if horizon_name == primary_horizon:
            compute.series_by_column_lag.setdefault(display_alias, {})[lag_i] = ic_series
            compute.stats_by_column_lag.setdefault(display_alias, {})[lag_i] = stats
        compute.factor_by_column[display_alias] = factor
        compute.method_by_column[display_alias] = method
        if all_products is not None and isinstance(quantile_portfolio_config, dict):
            from server.modules.single_factor_test.ic_response import (
                _quick_portfolio_statistics,
            )

            quick = _quick_portfolio_statistics(
                tester,
                factor,
                all_products,
                quantile_portfolio_config,
                factor_panel=fe_table,
                forward_panel=re_table,
                eligibility=data_present_mask,
                # The IC series is the evaluated signal timeline for this
                # horizon/delay.  Use it explicitly instead of inferring an
                # axis from a cached factor table that may still contain one
                # row per source bar.
                signal_index=screening_signal_index(factor, ic_series),
            )
            if quick.get("status") == "computed":
                quick["source_scope"] = (
                    "primary_forward_return_panel"
                    if is_primary_series else "forward_return_panel"
                )
                quick["source_scope_definition"] = (
                    "factor-declared primary horizon and entry delay"
                    if is_primary_series else
                    "realized factor forward-return panel for this horizon and entry delay"
                )
            compute.quantile_portfolio_statistics_by_column_horizon_lag.setdefault(
                display_alias, {}
            ).setdefault(horizon_name, {})[lag_i] = quick
        temporal_support = stats.get("temporal_support") if isinstance(stats, pd.Series) else None
        if isinstance(temporal_support, dict):
            compute.temporal_support_by_column_horizon_lag.setdefault(
                display_alias, {}
            ).setdefault(horizon_name, {})[lag_i] = dict(temporal_support)
        if isinstance(temporal_support, dict) and horizon_name == primary_horizon:
            compute.temporal_support_by_column_lag.setdefault(display_alias, {})[lag_i] = dict(temporal_support)
        if horizon_name == primary_horizon and lag_i == primary_ic_lag:
            r = tester._get_result(factor)
            r.ic_series = ic_series.copy()
            r.ic_stats = stats.copy()
            if not re_table.empty:
                r.returns = re_table
            if not fe_table.empty:
                r.func_table = fe_table
            if not data_present_mask.empty:
                r.data_present_mask = data_present_mask.copy(deep=False)
                r.data_present_all = bool(data_present_mask.to_numpy(dtype=bool).all())
            p_names = _extract_product_names(fe_table, re_table)
            if p_names:
                for p_name in p_names:
                    if p_name not in compute.selected_product_names:
                        compute.selected_product_names.append(p_name)


# ═══════════════════════════════════════════════════════════════
# IC 分组计算（共享：被 JSON 和 SSE 两个端点复用）
# ═══════════════════════════════════════════════════════════════

def _compute_ic_groups(
    tester: Any,
    param_items: List[Tuple[tuple, List[Factor]]],
    param_payloads: Dict[tuple, Dict[str, Any]],
    primary_ic_lag: int,
    primary_horizons: Dict[str, str],
    *,
    emitter: Any | None = None,
    cancel_event: threading.Event | None = None,
    all_products: list[Any] | None = None,
    quantile_portfolio_config: Dict[str, Any] | None = None,
) -> _ICComputeResult:
    """执行 IC 分组计算（支持并行）。返回中间状态。"""
    state = _ICComputeResult()

    def _check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _ICCancelled("IC test job cancelled")

    total_groups = len(param_items)

    # Construct each executable root once.  The same object is used for progress
    # sizing and evaluation; progress reporting must not rebuild the factor DAG.
    from collections import defaultdict
    batch_partitions: Dict[str, list[tuple[tuple, List[Factor], Factor, Any, Any | None]]] = defaultdict(list)
    fallback_items: list[tuple[tuple, List[Factor], Factor, Any | None]] = []
    pending_roots: dict[int, Factor] = {}

    def _cleanup_preserving_active_failure(cleanup: Any) -> None:
        """Run cleanup without replacing an exception already in flight."""
        import sys

        active_failure = sys.exc_info()[0] is not None
        try:
            cleanup()
        except Exception:
            if not active_failure:
                raise

    def _discard_owned_roots(roots: Iterable[Factor]) -> None:
        """Release every owned root once without hiding an active run failure."""
        import sys

        active_failure = sys.exc_info()[0] is not None
        cleanup_failure: Exception | None = None
        for root in roots:
            pending_roots.pop(id(root), None)
            try:
                discard_ic_factor(tester, root)
            except Exception as exc:
                if cleanup_failure is None:
                    cleanup_failure = exc
        if cleanup_failure is not None and not active_failure:
            raise cleanup_failure

    try:
        for key, factor_list in param_items:
            _check_cancelled()
            ic_factor, source_freq = build_ic_factor(param_payloads[key], factor_list)
            pending_roots[id(ic_factor)] = ic_factor
            temporal_support = _temporal_support_for_payload(
                param_payloads[key], factor_list,
            )
            if source_freq is None:
                fallback_items.append(
                    (key, factor_list, ic_factor, temporal_support),
                )
            else:
                batch_partitions[source_freq.name].append(
                    (key, factor_list, ic_factor, source_freq, temporal_support),
                )

        # ── node-level 进度统计 ──
        if emitter is not None:
            total_nodes = 0
            # Each bounded chunk gets one shared expression cache.  Count the
            # DAG union inside those exact boundaries; summing roots separately
            # advertises nodes that cache sharing means will never execute.
            for partition in batch_partitions.values():
                batch_size = _evaluation_batch_size(
                    partition[0][3], partition_size=len(partition),
                )
                for offset in range(0, len(partition), batch_size):
                    total_nodes += count_evaluation_nodes([
                        item[2]
                        for item in partition[offset:offset + batch_size]
                        if hasattr(item[2], '_expr')
                    ])
            total_nodes += sum(
                count_evaluation_nodes([item[2]])
                for item in fallback_items
                if hasattr(item[2], '_expr')
            )
            setup_progress(total_nodes, lambda c, t: emitter.emit_progress(c, t, 'eval'))
            emitter.emit_start(total=total_nodes, groups=total_groups, phase='init')

        # All roots in one source-frequency partition share the same products,
        # run window and preload.  Evaluate them serially inside a batch so
        # structurally identical FE subtrees can use one run-scoped cache.
        # Roots without an explicit source frequency retain the old isolated
        # path because their compatible context cannot be asserted safely.
        from tools.factors.evaluation import (
            evaluate_factors,
            prepare_evaluation_batch,
            release_evaluation_batch,
        )

        group_done = 0
        for partition in batch_partitions.values():
            _check_cancelled()
            batch_warmup = _batch_factor_warmup(item[4] for item in partition)
            evaluate_kwargs: Dict[str, Any] = {
                "freq": partition[0][3],
                "start_dt": tester.start_dt,
                # The signal/output end is not the raw-data end.  Forward
                # labels need the next trading session after the requested
                # endpoint; ``collect_ic_result`` clips the result back to
                # tester.end_dt after evaluation.
                "end_dt": ic_evaluation_end_dt(
                    tester,
                    _maximum_label_support(partition),
                ),
            }
            if batch_warmup is not None and batch_warmup > pd.Timedelta(0):
                evaluate_kwargs["warmup_window"] = batch_warmup
            # Prepare the immutable source-panel/timeline boundary once for
            # the whole frequency partition.  Root chunks retain independent
            # expression caches, while reusing this partition-wide superset
            # projection prevents one DataHub projection per root's column set.
            # The explicit release in the partition ``finally`` bounds the
            # lifetime of this one superset panel.
            # Lightweight/unit-test callers may use sentinel product objects
            # and monkeypatch ``evaluate_factors``.  Keep that legacy seam
            # intact; real Product instances always expose the frequency
            # contract and take the reusable preparation path.
            prepared = None
            if all(hasattr(product, "list_available_freqs") for product in tester.products):
                prepared = prepare_evaluation_batch(
                    [item[2] for item in partition],
                    products=tester.products,
                    **evaluate_kwargs,
                )
            try:
                batch_size = _evaluation_batch_size(
                    partition[0][3], partition_size=len(partition),
                )
                for offset in range(0, len(partition), batch_size):
                    _check_cancelled()
                    chunk = partition[offset:offset + batch_size]
                    roots = [item[2] for item in chunk]
                    try:
                        if prepared is None:
                            evaluate_factors(roots, products=tester.products, **evaluate_kwargs)
                        else:
                            evaluate_factors(
                                roots, products=tester.products, prepared=prepared,
                                **evaluate_kwargs,
                            )
                        for key, factor_list, ic_factor, _source_freq, temporal_support in chunk:
                            result = collect_ic_result(tester, ic_factor, factor_list)
                            if temporal_support is not None:
                                expected_sign, expected_sign_source = expected_sign_for_factor(factor_list[0]) if factor_list else (None, None)
                                result = (
                                    result[0], result[1],
                                    annotate_ic_temporal_support(
                                        tester,
                                        ic_factor,
                                        factor_list,
                                        result[2],
                                        temporal_support,
                                        ic_series=result[1],
                                        expected_sign=expected_sign,
                                        expected_sign_source=expected_sign_source,
                                    ),
                                    result[3], result[4], result[5],
                                )
                            group_done += 1
                            if emitter is not None:
                                emitter.emit_progress(group_done, total_groups, 'group_done')
                            _merge_ic_result(
                                state, key, result, tester, primary_ic_lag, primary_horizons,
                                all_products=all_products,
                                quantile_portfolio_config=quantile_portfolio_config,
                            )
                    finally:
                        _discard_owned_roots(item[2] for item in chunk)
                    # Drop the temporary root list before the next chunk.  The
                    # partition metadata remains lightweight and is needed only to
                    # derive the next slice.
                    del roots, chunk
            finally:
                if prepared is not None:
                    prepared_batch = prepared
                    try:
                        _cleanup_preserving_active_failure(
                            lambda: release_evaluation_batch(prepared_batch),
                        )
                    finally:
                        del prepared

        # This branch is expected only for legacy factors that do not declare
        # a source frequency.  Evaluate the prebuilt root directly so progress
        # sizing and execution still share one DAG construction.
        for key, factor_list, ic_factor, temporal_support in fallback_items:
            _check_cancelled()
            try:
                evaluate_kwargs: Dict[str, Any] = {
                    "freq": None,
                    "start_dt": tester.start_dt,
                    "end_dt": ic_evaluation_end_dt(tester, temporal_support),
                }
                warmup_seconds = getattr(
                    temporal_support, "factor_input_support_seconds", None,
                )
                if warmup_seconds is not None and warmup_seconds > 0:
                    evaluate_kwargs["warmup_window"] = pd.Timedelta(
                        seconds=warmup_seconds,
                    )
                ic_factor.evaluate(tester.products, **evaluate_kwargs)
                expected_sign, expected_sign_source = (
                    expected_sign_for_factor(factor_list[0])
                    if factor_list else (None, None)
                )
                result = collect_ic_result(
                    tester,
                    ic_factor,
                    factor_list,
                    temporal_support=temporal_support,
                    expected_sign=expected_sign,
                    expected_sign_source=expected_sign_source,
                )
            finally:
                _discard_owned_roots((ic_factor,))
            group_done += 1
            if emitter is not None:
                emitter.emit_progress(group_done, total_groups, 'group_done')
            _merge_ic_result(
                state, key, result, tester, primary_ic_lag, primary_horizons,
                all_products=all_products,
                quantile_portfolio_config=quantile_portfolio_config,
            )
    finally:
        # A build, progress setup, or prepared-batch failure may happen before a
        # chunk reaches its local cleanup.  Release every root still owned by
        # this call; successfully processed chunks remove themselves above.
        try:
            _discard_owned_roots(tuple(pending_roots.values()))
        finally:
            if emitter is not None:
                _cleanup_preserving_active_failure(teardown_progress)

    return state


# ═══════════════════════════════════════════════════════════════
# 结果构建（共享：把中间状态转为 JSON dict）
# ═══════════════════════════════════════════════════════════════

# Keep the historical private entry name while the response builder lives in
# its own bounded module; existing tests and internal callers remain stable.
_build_ic_response = build_ic_response


# ═══════════════════════════════════════════════════════════════
# IC 计算核心（共享预处理 + 调度）
# ═══════════════════════════════════════════════════════════════

def _prepare_ic_compute(
    data: dict,
    tester: Any,
    factor_family: Any,
) -> Tuple[
    List[str],              # display columns
    str,                    # paths_hash
    list,                   # all_products
    Dict[tuple, List[Factor]],  # ic_param_map
    Dict[tuple, Dict[str, Any]], # param_payloads
    list | None,            # ic_decay_lags
    Any,                    # legacy rolling_window; rolling_windows is normalized separately
    List[int],              # ic_lags
    int,                    # primary_ic_lag
    List[str],              # forward_horizons
    Dict[str, str],         # primary_forward_horizon by display column
]:
    """解析参数并构建 IC 分组映射。"""
    (product_path_selection_id, _, factor_items, paths, ic_decay_lags, rolling_window,
     ic_lags, primary_ic_lag, ic_correlation, returns_col,
     forward_horizon_bases, forward_horizon_multipliers) = parse_ic_params(data)
    # Validate the multi-window contract before any factor evaluation.  The
    # normalized specs are parsed again at response construction so legacy
    # tuple callers of ``parse_ic_params`` remain source-compatible.
    normalize_rolling_window_specs(data)

    paths_hash_source = paths if paths else [product_path_selection_id]
    paths_hash = hashlib.md5(str(sorted(paths_hash_source)).encode()).hexdigest()

    matched_factors: List[Factor] = []
    for item in factor_items:
        f = factor_family.get_factor_by_alias(item.get('alias', ''))
        if f is not None:
            matched_factors.append(f)
    if not matched_factors:
        raise ValueError('没有找到匹配的因子，请检查收益率频率设置中的因子是否属于当前因子家族')

    all_products = tester.products.copy()

    ic_param_map: Dict[tuple, List[Factor]] = {}
    param_payloads: Dict[tuple, Dict[str, Any]] = {}
    display_columns: List[str] = []
    forward_horizons: List[str] = []
    primary_horizons: Dict[str, str] = {}

    shift = 0 if returns_col.value.name.startswith('OPEN') else 1

    next_returns_family = NextReturns()
    methods = ['rank', 'pearson'] if ic_correlation == 'both' else [ic_correlation]
    method_family = {
        'rank': CrossSectionIC,
        'pearson': CrossSectionPearsonIC,
    }
    method_label = {
        'rank': 'Rank IC',
        'pearson': 'Pearson IC',
    }
    for factor in matched_factors:
        effective_freq = factor.freq
        if effective_freq is None:
            raise ValueError(f'Factor {factor.alias}: 无法确定收益率频率')
        factor_horizons = resolve_forward_horizons(
            effective_freq, forward_horizon_bases, forward_horizon_multipliers,
        )
        for horizon in factor_horizons:
            if horizon.name not in forward_horizons:
                forward_horizons.append(horizon.name)
        for method in methods:
            display_alias = factor.alias if len(methods) == 1 else f"{factor.alias} · {method_label[method]}"
            if display_alias not in display_columns:
                display_columns.append(display_alias)
            primary_horizons.setdefault(display_alias, factor_horizons[0].name)
            for horizon in factor_horizons:
                for lag_i in ic_lags:
                    key = (
                        str(factor._structural_key()),
                        effective_freq.name,
                        shift,
                        returns_col.value.name,
                        horizon.name,
                        lag_i,
                        method,
                        display_alias,
                    )
                    if key not in ic_param_map:
                        returns_factor = next_returns_family.get_factor(
                            SC=returns_col.value,
                            RF=horizon.value,
                            S=shift,
                            **{'$F': effective_freq.value, '$Rev': '0'},
                        )
                        ic_param_map[key] = []
                        param_payloads[key] = {
                            'FE': factor,
                            'RE': returns_factor,
                            'Lag': lag_i,
                            '$F': effective_freq.value,
                            '_ic_family_cls': method_family[method],
                            '_ic_method': method,
                        }
                    ic_param_map[key].append(factor)

    if not forward_horizons:
        raise ValueError('没有可用的 forward return horizon')
    if forward_horizon_bases == [SCALE_AWARE_HORIZON_BASE]:
        forward_horizons.sort(key=lambda value: DataFreq(value).value)
    return (
        display_columns, paths_hash, all_products, ic_param_map, param_payloads,
        ic_decay_lags, rolling_window, ic_lags, primary_ic_lag,
        forward_horizons, primary_horizons,
    )


def _run_ic_compute_to_sink(
    data: dict[str, Any],
    tester: Any,
    factor_family: FactorFamily,
    sink: Any,
    prepared: tuple | None = None,
    cancel_event: Any | None = None,
) -> None:
    _token = None
    try:
        cancel_event = cancel_event or getattr(getattr(sink, "job", None), "cancel_event", None)
        if cancel_event is not None and cancel_event.is_set():
            raise _ICCancelled("IC test job cancelled before start")

        if prepared is None:
            prepared = _prepare_ic_compute(data, tester, factor_family)
        (display_columns, paths_hash, all_products, ic_param_map, param_payloads,
         ic_decay_lags, rolling_window, ic_lags, primary_ic_lag,
         forward_horizons, primary_horizons) = prepared

        tester.sync_signal_index = None
        tester.sync_signal_index_replaced = None
        _token = _active_tester.set(tester)

        param_items = list(ic_param_map.items())

        compute = _compute_ic_groups(
            tester, param_items, param_payloads, primary_ic_lag, primary_horizons,
            emitter=sink,
            cancel_event=cancel_event,
            all_products=all_products,
            quantile_portfolio_config=(
                data.get('quantile_portfolio_statistics')
                or data.get('quantile_portfolio')
                or {}
            ),
        )
        if cancel_event is not None and cancel_event.is_set():
            raise _ICCancelled("IC test job cancelled")
        response = _build_ic_response(
            tester, display_columns, all_products, compute,
            paths_hash, ic_lags, primary_ic_lag, ic_decay_lags, rolling_window,
            forward_horizons, primary_horizons,
            _factor_execution_refs(data),
            data.get('ic_periods'),
            horizon_sampling=describe_forward_horizon_sampling(data),
            metric_selection=normalize_ic_metric_selection(data.get('ic_metric_selection')),
            rolling_window_specs=normalize_rolling_window_specs(data),
            quantile_portfolio_config=(
                data.get('quantile_portfolio_statistics')
                or data.get('quantile_portfolio')
                or {}
            ),
        )
        from server.services.external_factor_artifacts import result_metadata

        response["external_factor_artifacts"] = result_metadata(
            data.get("external_factor_artifacts")
        )
        run_spec = data.get("run_spec") or {}
        typed_ic = run_spec.get("typed_ic") or {}
        response["provenance"] = {
            "run_spec_hash": data.get("run_spec_hash") or "",
            "group_provenance": deepcopy(
                typed_ic.get("group_provenance") or typed_ic.get("groups") or []
            ),
            "product_selections": deepcopy(
                (run_spec.get("configuration") or {}).get("shared", {}).get(
                    "product_selections", {}
                )
            ),
        }
        sink.emit_result(response)
    except _ICCancelled as exc:
        sink.emit_error(str(exc), cancelled=True)
    except Exception as e:
        sink.emit_error(str(e), traceback=traceback.format_exc())
    finally:
        if _token is not None:
            _active_tester.reset(_token)


def execute_ic_run_spec(data: dict[str, Any], *, sink: Any, cancel_event: Any) -> None:
    """Execute IC from frozen paths and aliases without consulting PageRuntime."""
    owner = str(data.get("_owner") or data.get("owner_username") or "").strip()
    run_id = str(data.get("run_id") or data.get("run_token") or "").strip()
    if not owner or not run_id:
        raise ValueError("IC RunSpec requires owner and run_id")
    selection = selection_from_request(data, page_uuid="")
    start_dt, end_dt = run_window_datetimes(data)
    if start_dt is None or end_dt is None:
        raise ValueError("IC RunSpec requires start_date and end_date")
    tester = create_isolated_factor_tester_for_run(
        selection,
        run_id=run_id,
        start_dt=start_dt,
        end_dt=end_dt,
        user=user_obj_for_name(owner),
    )
    factor_descriptors = [
        require_frozen_factor(item) for item in (data.get("factors") or [])
    ]
    from server.services.external_factor_artifacts import load_frozen_artifacts

    external = {
        factor.alias: factor
        for factor in load_frozen_artifacts(data.get("external_factor_artifacts"))
    }
    resolved = []
    for descriptor in factor_descriptors:
        alias = str(descriptor.get("alias") or "").strip()
        factor_owner = str(descriptor.get("owner_ref") or owner).strip()
        resolved.append(
            external.get(alias) or factor_from_alias(alias, username=factor_owner)
        )
    for factor in resolved:
        require_factor_data_coverage(
            tester.products,
            factor,
            start_dt=start_dt,
            end_dt=end_dt,
            data_source=str(data.get("data_source") or ""),
        )

    class _ResolvedFactorCollection:
        """Run-local lookup for independently resolved FactorExpr instances."""

        def __init__(self, factors: list[Factor]):
            self.factors = factors
            self._by_alias = {factor.alias: factor for factor in factors}

        def get_factor_by_alias(self, alias: str):
            return self._by_alias.get(alias)

    factor_collection = _ResolvedFactorCollection(resolved)
    _run_ic_compute_to_sink(
        data, tester, factor_collection, sink, cancel_event=cancel_event,
    )
