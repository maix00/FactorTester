"""Group test endpoint."""
import logging, math, time, traceback
from typing import Any, cast
import numpy as np
import pandas as pd
from flask import request, jsonify
from tools.factors.FactorTester import FactorTester, _active_tester, _signal_time
from tools.factors.Parameters import FactorNextPeriodReturns
from tools.factors.tests.single_factor_test.group.core import infer_periods_per_year
from tools.factors.tests.single_factor_test.group.core import _emit_progress as _core_emit_progress
from tools.factors.tests.single_factor_test.group.core import ensure_group_factor_inputs
from tools.factors.tests.single_factor_test.group.detail import (
    build_group_detail,
    _build_product_fee_rates,
    _display_with_fee as _display_product_with_fee,
)
from tools.factors.tests.single_factor_test.group.metadata import GROUP_TEST_PHASES, GROUP_TEST_METRICS_META
from tools.factors.tests.single_factor_test.group.monotonicity import build_group_ranking_detail
from tools.products.AdjustableTermStructure import resolve_term_structure_product
from tools.products.Product import Product
from . import sft_bp
import server.services.runtime_state as runtime_state
from server.modules.shared.price_data_helpers import to_epoch_ms
from server.services.factor_registry import get_factor_family_instance

_log = logging.getLogger(__name__)


def _ensure_tester_factors_for_group(
    tester: Any,
    factor_aliases: list[str],
    factor_family_alias: str | None,
    *,
    params_list: list | None = None,
    username: str | None = None,
) -> None:
    """Ensure direct group runs can resolve factors even when IC has not run."""
    missing_aliases = [
        str(alias) for alias in factor_aliases
        if alias and tester.resolve_factor(str(alias)) is None
    ]
    if not missing_aliases:
        return
    if not factor_family_alias:
        return

    factor_family = get_factor_family_instance(str(factor_family_alias), username=username)
    if params_list is None:
        params_list = runtime_state.get_session_params(str(factor_family_alias), factor_family)
    factors = factor_family.get_factors(params_list=params_list)
    existing_by_alias = {getattr(f, 'alias', ''): i for i, f in enumerate(getattr(tester, 'factors', []))}
    for factor in factors:
        alias = getattr(factor, 'alias', '')
        if not alias:
            continue
        if alias in existing_by_alias:
            tester.factors[existing_by_alias[alias]] = factor
        else:
            tester.factors.append(factor)
            existing_by_alias[alias] = len(tester.factors) - 1


def _progress(message: str) -> None:
    print(f"[GroupTest] {message}", flush=True)


def _get_metrics_meta() -> dict:
    """Return the single-source metrics metadata for frontend rendering."""
    return GROUP_TEST_METRICS_META


def _safe_float(v):
    """安全转为 float，NaN/inf 返回 None。"""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(fv) or math.isinf(fv)) else fv


def _safe_bool(obj) -> bool:
    """安全求布尔值，避免 numpy 数组的 ambiguous truth value 错误。"""
    if obj is None:
        return False
    if isinstance(obj, np.ndarray):
        return bool(obj.size > 0)
    return bool(obj)


def _parse_initial_capital(raw: Any, default: float = 100000000.0) -> float:
    """Parse initial capital with a stable backend default."""
    if raw in (None, ''):
        return float(default)
    value = _safe_float(raw)
    if value is None or value <= 0:
        raise ValueError(f'初始金额必须是正数，收到: {raw!r}')
    return float(value)


def _parse_group_fee_config(data: dict) -> tuple[float, list, bool]:
    """Parse legacy group-test fee payload into engine inputs.

    ``fee`` is provided in percent units by the UI, while the engine expects a
    ratio. Per-variety modifications are cleaned into FeeModification objects.
    """
    from tools.products.transactions.fees import clean_modifications

    raw_fee = data.get('fee', 0)
    fee_value = _safe_float(raw_fee)
    fee_uniform = 0.0 if fee_value is None else float(fee_value) / 100.0
    raw_modifications = data.get('fee_modifications') or data.get('feeModifications') or []
    if not isinstance(raw_modifications, list):
        raw_modifications = []
    fee_modifications = clean_modifications(raw_modifications)
    use_closetoday = bool(data.get('use_closetoday') or data.get('useCloseToday'))
    return fee_uniform, fee_modifications, use_closetoday


def _product_fee_rates_by_name(group_result: Any) -> dict[str, dict[str, float]]:
    """Build per-product fee rows from a group result."""
    if group_result is None:
        return {}
    return _build_product_fee_rates(
        getattr(group_result, 'valid_cols', None),
        getattr(group_result, 'open_ratio_vec', None),
        getattr(group_result, 'close_ratio_vec', None),
        getattr(group_result, 'close_today_ratio_vec', None),
    )


def _registered_product(product_name: str):
    if not product_name:
        return None
    return resolve_term_structure_product(product_name)


def _snapshot_product_display(product_ref: Any, fee_rates: dict[str, dict[str, float]] | None = None, *, collapsed_from: str | None = None) -> dict[str, Any]:
    fee_rates = fee_rates or {}
    raw_name = getattr(product_ref, 'name', str(product_ref) if product_ref is not None else '')
    product = product_ref if isinstance(product_ref, Product) else _registered_product(raw_name) if product_ref else None
    name = getattr(product, 'name', None) if product is not None else raw_name
    display = _display_product_with_fee(product if product is not None else name, fee_rates)
    if collapsed_from and collapsed_from != name:
        display['source_name'] = collapsed_from
    return display


def _cn_futures_contract_parent(product_ref: Any):
    contract_uid = getattr(product_ref, 'name', None) or str(product_ref)
    if not contract_uid:
        return None
    try:
        from sources.LocalCNFutures.CNFutures import CNFutures
        return CNFutures.get_contract_parent(str(contract_uid))
    except Exception:
        return None


def _snapshot_actual_quantity(
    position_row: Any,
    amount_row: Any | None,
    product_idx: int,
    eps: float = 1e-12,
) -> tuple[float, float]:
    """Read quantity and amount directly from simulate's pre-computed arrays.

    NEVER recompute amount from price — amount comes from hold_amounts_np
    (= position_notional in simulate, already using the correct open_price).
    """
    qty = 0.0
    amt = 0.0
    if position_row is not None and product_idx < len(position_row):
        qty_value = _safe_float(position_row[product_idx])
        qty = 0.0 if qty_value is None else qty_value
    if amount_row is not None and product_idx < len(amount_row):
        amt_value = _safe_float(amount_row[product_idx])
        amt = 0.0 if amt_value is None else amt_value
    if abs(qty) <= eps:
        qty = 0.0
    if abs(amt) <= eps:
        amt = 0.0
    return qty, amt





def _snapshot_group_label(group_idx: int, group_names: Any) -> str:
    if isinstance(group_names, dict):
        for key in (group_idx, str(group_idx)):
            if key in group_names and group_names[key]:
                return str(group_names[key])
    return f'Group {group_idx + 1}'


def _snapshot_display_timezone(group_result: Any, valid_cols: list[Any] | None = None) -> str:
    index_list = list(getattr(group_result, 'index_list', []) or [])
    for idx_entry in index_list:
        ts = _signal_time(idx_entry)
        if isinstance(ts, pd.Timestamp) and ts.tzinfo is not None:
            return str(ts.tz)
    for product_ref in valid_cols or list(getattr(group_result, 'valid_cols', []) or []):
        product = product_ref if isinstance(product_ref, Product) else _registered_product(str(product_ref))
        timezone = getattr(product, 'timezone', None) if product is not None else None
        if timezone:
            return str(timezone)
    return 'Asia/Shanghai'


def _build_snapshot_matrix(
    *,
    matrix_key: str,
    matrix_label: str,
    group_result: Any,
    valid_cols: list[Any],
    fee_rates_by_name: dict[str, dict[str, float]],
    t_idx: int | None,
    prev_t_idx: int | None,
    capital_diagnostics: dict[str, Any] | None = None,
    group_names: Any = None,
    collapse_term_structure: bool = False,
) -> dict[str, Any]:
    positions = getattr(group_result, 'position_quantities_np', None)
    amounts = getattr(group_result, 'hold_amounts_np', None)
    target_before_floor = getattr(group_result, 'target_amounts_before_floor_np', None)
    prev_end_amounts = getattr(group_result, 'prev_end_amounts_np', None)
    memberships = getattr(group_result, 'membership_np', None)
    total_equity_np = getattr(group_result, 'total_equity_np', None)
    cash_np = getattr(group_result, 'cash_np', None)
    pre_rebalance_total_equity_np = getattr(group_result, 'pre_rebalance_total_equity_np', None)
    post_rebalance_total_equity_np = getattr(group_result, 'post_rebalance_total_equity_np', None)
    pre_rebalance_cash_np = getattr(group_result, 'pre_rebalance_cash_np', None)
    post_rebalance_cash_np = getattr(group_result, 'post_rebalance_cash_np', None)
    buy_fee_amount_np = getattr(group_result, 'buy_fee_amount_np', None)
    sell_fee_amount_np = getattr(group_result, 'sell_fee_amount_np', None)
    liquidity_capacity_np = getattr(group_result, 'liquidity_capacity_np', None)
    liquidity_modes = getattr(group_result, 'liquidity_modes', None) or []
    liquidity_percents = getattr(group_result, 'liquidity_percents', None) or []
    if positions is None and amounts is None:
        return {'key': matrix_key, 'label': matrix_label, 'columns': [], 'rows': [], 'cells': []}

    current_products = list(valid_cols or [])
    row_order: list[str] = []
    row_meta: dict[str, dict[str, Any]] = {}
    per_group: list[dict[str, dict[str, Any]]] = []

    def _product_name(product_ref: Any) -> str:
        return getattr(product_ref, 'name', str(product_ref))

    def _resolved_product(product_ref: Any):
        if collapse_term_structure:
            resolved = None
            try:
                resolved = getattr(product_ref, 'parent_product', None)
                if callable(resolved):
                    resolved = resolved()
            except Exception:
                resolved = None
            if resolved is None:
                resolved = resolve_term_structure_product(product_ref)
            if resolved is None:
                resolved = _cn_futures_contract_parent(product_ref)
            if resolved is not None:
                return resolved
        return product_ref

    def _row_key(raw_product: Any) -> str:
        resolved = _resolved_product(raw_product)
        return _product_name(resolved if resolved is not None else raw_product)

    def _row_display(product_ref: Any, sources: list[str]) -> dict[str, Any]:
        display = _snapshot_product_display(product_ref, fee_rates_by_name, collapsed_from=sources[0] if sources else None)
        if collapse_term_structure and len(sources) > 1:
            display['source_names'] = sources
        return display

    product_rows = []
    raw_name_to_p_idx: dict[str, int] = {}
    for p_idx, raw_product in enumerate(current_products):
        raw_name = _product_name(raw_product)
        resolved_product = _resolved_product(raw_product) if collapse_term_structure else raw_product
        row_key = _product_name(resolved_product if resolved_product is not None else raw_product)
        product_rows.append({
            'raw_product': raw_product,
            'raw_name': raw_name,
            'resolved_product': resolved_product,
            'row_key': row_key,
            'p_idx': p_idx,
        })
        raw_name_to_p_idx[raw_name] = p_idx

    def _group_index_map(index: int) -> tuple[Any, Any, Any, Any, Any, Any]:
        cur_pos = positions[t_idx, index] if positions is not None and t_idx is not None and t_idx < positions.shape[0] else None
        cur_amt = amounts[t_idx, index] if amounts is not None and t_idx is not None and t_idx < amounts.shape[0] else None
        prev_pos = positions[prev_t_idx, index] if positions is not None and prev_t_idx is not None and prev_t_idx < positions.shape[0] else None
        prev_amt = (
            prev_end_amounts[t_idx, index]
            if prev_end_amounts is not None and t_idx is not None and t_idx < prev_end_amounts.shape[0]
            else amounts[prev_t_idx, index] if amounts is not None and prev_t_idx is not None and prev_t_idx < amounts.shape[0]
            else None
        )
        cur_mem = memberships[t_idx, index] if memberships is not None and t_idx is not None and t_idx < memberships.shape[0] else None
        prev_mem = memberships[prev_t_idx, index] if memberships is not None and prev_t_idx is not None and prev_t_idx < memberships.shape[0] else None
        return (cur_pos, cur_amt, prev_pos, prev_amt, cur_mem, prev_mem)

    diagnostics_by_group: dict[int, dict[str, Any]] = {}
    if isinstance(capital_diagnostics, dict):
        for item in capital_diagnostics.get('blocked_groups', []) or []:
            try:
                diagnostics_by_group[int(item.get('group_index'))] = item
            except (TypeError, ValueError, AttributeError):
                continue

    group_count = 0
    for matrix in (positions, amounts, memberships):
        if matrix is not None and getattr(matrix, 'ndim', 0) >= 2:
            group_count = int(matrix.shape[1])
            break

    for g_idx in range(group_count):
        cur_pos, cur_amt, prev_pos, prev_amt, cur_mem, prev_mem = _group_index_map(g_idx)
        group_rows: dict[str, dict[str, Any]] = {}
        for p_idx, product_row in enumerate(product_rows):
            raw_product = product_row['raw_product']
            raw_name = product_row['raw_name']
            row_key = product_row['row_key']
            resolved_product = product_row['resolved_product']
            cur_qty, cur_amount = _snapshot_actual_quantity(cur_pos, cur_amt, p_idx)
            prev_qty, prev_amount = _snapshot_actual_quantity(prev_pos, prev_amt, p_idx)
            if row_key not in group_rows:
                group_rows[row_key] = {
                    'name': row_key,
                    'source_names': [raw_name],
                    'current_qty': 0.0,
                    'current_amount': 0.0,
                    'prev_qty': 0.0,
                    'prev_amount': 0.0,
                    'current_membership': False,
                    'prev_membership': False,
                    'target_budget_amount': 0.0,
                    'planned_qty': 0.0,
                    'planned_amount': 0.0,
                    'display': _row_display(resolved_product if resolved_product is not None else raw_product, [raw_name]),
                }
                if row_key not in row_order:
                    row_order.append(row_key)
                    row_meta[row_key] = group_rows[row_key]['display']
            else:
                if raw_name not in group_rows[row_key]['source_names']:
                    group_rows[row_key]['source_names'].append(raw_name)
                    group_rows[row_key]['display'] = _row_display(resolved_product if resolved_product is not None else raw_product, group_rows[row_key]['source_names'])
                    row_meta[row_key] = group_rows[row_key]['display']
            group_rows[row_key]['current_qty'] += cur_qty
            group_rows[row_key]['current_amount'] += cur_amount
            group_rows[row_key]['prev_qty'] += prev_qty
            group_rows[row_key]['prev_amount'] += prev_amount
            if cur_mem is not None and p_idx < len(cur_mem):
                group_rows[row_key]['current_membership'] = bool(group_rows[row_key]['current_membership'] or bool(cur_mem[p_idx]))
            if prev_mem is not None and p_idx < len(prev_mem):
                group_rows[row_key]['prev_membership'] = bool(group_rows[row_key]['prev_membership'] or bool(prev_mem[p_idx]))
            target_amount_value = None
            if target_before_floor is not None and t_idx is not None and t_idx < target_before_floor.shape[0] and g_idx < target_before_floor.shape[1] and p_idx < target_before_floor.shape[2]:
                target_amount_value = _safe_float(target_before_floor[t_idx, g_idx, p_idx])
            if target_amount_value is not None:
                group_rows[row_key]['target_budget_amount'] += float(target_amount_value)
            # planned_qty/planned_amount come directly from simulate arrays, NOT recomputed:
            # - position_quantities_np = desired_quantities (after full pipeline:
            #   liquidity cap → floor → cash packing)
            # - hold_amounts_np = position_notional (= desired_quantities × open_price contract value)
            if positions is not None and t_idx is not None and t_idx < positions.shape[0] and g_idx < positions.shape[1] and p_idx < positions.shape[2]:
                sim_planned_qty = _safe_float(positions[t_idx, g_idx, p_idx]) or 0.0
                group_rows[row_key]['planned_qty'] += float(sim_planned_qty)
            if amounts is not None and t_idx is not None and t_idx < amounts.shape[0] and g_idx < amounts.shape[1] and p_idx < amounts.shape[2]:
                sim_planned_amount = _safe_float(amounts[t_idx, g_idx, p_idx]) or 0.0
                group_rows[row_key]['planned_amount'] += float(sim_planned_amount)
        per_group.append(group_rows)

    columns = []
    for g_idx in range(len(per_group)):
        current_active = 0
        selected_count = 0
        for row_key, row in per_group[g_idx].items():
            if abs(row['current_qty']) > 1e-12 or abs(row['current_amount']) > 1e-12:
                current_active += 1
            if bool(row.get('current_membership')):
                selected_count += 1
        label = _snapshot_group_label(g_idx, group_names)
        columns.append({
            'name': label,
            'label': label,
            'index': g_idx,
            'count': selected_count,
            'count_label': '持仓品种数(xxx)',
        })

    cells = []
    summary_cells = []
    summary_keys = []

    def _matrix_value(matrix: Any, g_idx: int) -> float | None:
        if matrix is None or t_idx is None or t_idx >= matrix.shape[0] or g_idx >= matrix.shape[1]:
            return None
        return _safe_float(matrix[t_idx, g_idx])

    def _append_amount_row(
        row_key: str,
        display: dict[str, Any],
        end_matrix: Any,
        *,
        pre_rebalance_matrix: Any | None = None,
        post_rebalance_matrix: Any | None = None,
        buy_fee_matrix: Any | None = None,
        sell_fee_matrix: Any | None = None,
    ) -> None:
        if end_matrix is None or t_idx is None or t_idx >= end_matrix.shape[0]:
            return
        amount_cells = []
        for g_idx in range(len(per_group)):
            end_amount = _matrix_value(end_matrix, g_idx)
            pre_rebalance_amount = _matrix_value(pre_rebalance_matrix, g_idx)
            post_rebalance_amount = _matrix_value(post_rebalance_matrix, g_idx)
            if prev_t_idx is not None and prev_t_idx < end_matrix.shape[0] and g_idx < end_matrix.shape[1]:
                previous_end_amount = _safe_float(end_matrix[prev_t_idx, g_idx])
                if pre_rebalance_amount is None:
                    pre_rebalance_amount = previous_end_amount
                if post_rebalance_amount is None:
                    post_rebalance_amount = previous_end_amount
            end_amount = 0.0 if end_amount is None else end_amount
            pre_rebalance_amount = end_amount if pre_rebalance_amount is None else pre_rebalance_amount
            post_rebalance_amount = pre_rebalance_amount if post_rebalance_amount is None else post_rebalance_amount
            buy_fee_amount = _matrix_value(buy_fee_matrix, g_idx)
            sell_fee_amount = _matrix_value(sell_fee_matrix, g_idx)
            buy_fee_amount = 0.0 if buy_fee_amount is None else buy_fee_amount
            sell_fee_amount = 0.0 if sell_fee_amount is None else sell_fee_amount
            delta_amount = end_amount - post_rebalance_amount
            if delta_amount > 1e-12:
                status = 'increasing'
                direction = 'increase'
            elif delta_amount < -1e-12:
                status = 'decreasing'
                direction = 'decrease'
            else:
                status = 'holding'
                direction = 'flat'
            amount_cells.append({
                'status': status,
                'product': display,
                'quantity': None,
                'amount': round(float(end_amount), 6),
                'pre_rebalance_amount': round(float(pre_rebalance_amount), 6),
                'post_rebalance_amount': round(float(post_rebalance_amount), 6),
                'end_amount': round(float(end_amount), 6),
                'buy_fee_amount': round(float(buy_fee_amount), 6),
                'sell_fee_amount': round(float(sell_fee_amount), 6),
                'fee_amount': round(float(buy_fee_amount + sell_fee_amount), 6),
                'previous_quantity': None,
                'delta_quantity': None,
                'delta_amount': round(float(delta_amount), 6),
                'change_direction': direction,
                'pending_exit': False,
                'source_names': [],
            })
        row_meta[row_key] = display
        summary_keys.append(row_key)
        summary_cells.append(amount_cells)

    _append_amount_row(
        '__total_equity__',
        {'name': '总资产'},
        total_equity_np,
        pre_rebalance_matrix=pre_rebalance_total_equity_np,
        post_rebalance_matrix=post_rebalance_total_equity_np,
        buy_fee_matrix=buy_fee_amount_np,
        sell_fee_matrix=sell_fee_amount_np,
    )
    _append_amount_row(
        '__cash__',
        {'name': '现金'},
        cash_np,
        pre_rebalance_matrix=pre_rebalance_cash_np,
        post_rebalance_matrix=post_rebalance_cash_np,
        buy_fee_matrix=buy_fee_amount_np,
        sell_fee_matrix=sell_fee_amount_np,
    )

    for row_key in row_order:
        row_cells = []
        row_display = row_meta.get(row_key) or _snapshot_product_display(row_key)
        for g_idx in range(len(per_group)):
            row = per_group[g_idx].get(row_key)
            if not row:
                row_cells.append({
                    'status': 'absent',
                    'product': None,
                    'quantity': 0.0,
                    'amount': 0.0,
                    'pending_exit': False,
                    'selected': False,
                    'open_reason': None,
                })
                continue
            cur_active = abs(row['current_qty']) > 1e-12 or abs(row['current_amount']) > 1e-12
            prev_active = abs(row['prev_qty']) > 1e-12 or abs(row['prev_amount']) > 1e-12
            desired_now = bool(row['current_membership'])
            desired_prev = bool(row['prev_membership'])
            delta_qty = row['current_qty'] - row['prev_qty']
            delta_amount = row['current_amount'] - row['prev_amount']
            diag = diagnostics_by_group.get(g_idx)
            open_reason = None
            planned_qty = row.get('planned_qty') or 0.0
            planned_amount = row.get('planned_amount') or 0.0
            target_budget_amount = row.get('target_budget_amount') or 0.0
            remaining_cash = None
            if post_rebalance_cash_np is not None and t_idx is not None:
                try:
                    if 0 <= t_idx < post_rebalance_cash_np.shape[0] and 0 <= g_idx < post_rebalance_cash_np.shape[1]:
                        remaining_cash = _safe_float(post_rebalance_cash_np[t_idx, g_idx])
                except Exception:
                    remaining_cash = None
            if desired_now and not cur_active:
                # selected but not opened — diagnose using simulate data
                reasons = []
                if remaining_cash is not None and remaining_cash < 1.0:
                    reasons.append(f"剩余现金约 {int(round(float(remaining_cash))):,} 元")
                if planned_qty < 1e-12 and target_budget_amount > 0:
                    reasons.append(f"计划金额 {int(round(float(target_budget_amount))):,} 元，可开0手(流动性限额/保证金不足)")
                if reasons:
                    open_reason = '；'.join(reasons)
                elif remaining_cash is not None:
                    open_reason = f"剩余现金约 {int(round(float(remaining_cash))):,} 元"
                else:
                    open_reason = '资金不足以开仓'

            if desired_now and not cur_active:
                status = 'selected'
            elif cur_active and not prev_active:
                status = 'entering'
            elif prev_active and not cur_active:
                status = 'exiting'
            elif cur_active and not desired_now and (desired_prev or prev_active):
                status = 'pending_exit'
            elif cur_active and prev_active and delta_qty > 1e-12:
                status = 'increasing'
            elif cur_active and prev_active and delta_qty < -1e-12:
                status = 'decreasing'
            elif cur_active:
                status = 'holding'
            else:
                status = 'absent'
            if delta_qty > 1e-12 or delta_amount > 1e-12:
                change_direction = 'increase'
            elif delta_qty < -1e-12 or delta_amount < -1e-12:
                change_direction = 'decrease'
            else:
                change_direction = 'flat'
            # Compute per-product liquidity cap amount for this time step
            liquidity_cap_amount = None
            if liquidity_capacity_np is not None and liquidity_modes and liquidity_percents:
                try:
                    # Use the first source product's p_idx to look up liquidity cap
                    source_names = row.get('source_names', [])
                    first_name = source_names[0] if source_names else row_key
                    first_p_idx = raw_name_to_p_idx.get(first_name)
                    if (first_p_idx is not None
                        and 0 <= g_idx < len(liquidity_modes)
                        and liquidity_modes[g_idx] == 'percent'
                        and t_idx is not None
                        and 0 <= t_idx < liquidity_capacity_np.shape[0]
                        and 0 <= g_idx < liquidity_capacity_np.shape[1]
                        and 0 <= first_p_idx < liquidity_capacity_np.shape[2]):
                        raw_cap = _safe_float(liquidity_capacity_np[t_idx, g_idx, first_p_idx])
                        if raw_cap is not None and np.isfinite(raw_cap) and raw_cap > 0:
                            liquidity_cap_amount = round(float(raw_cap), 2)
                except Exception:
                    pass

            row_cells.append({
                'status': status,
                'product': row_display,
                'quantity': round(float(row['current_qty']), 6),
                'amount': round(float(row['current_amount']), 6),
                'previous_quantity': round(float(row['prev_qty']), 6),
                'previous_amount': round(float(row['prev_amount']), 6),
                'delta_quantity': round(float(delta_qty), 6),
                'delta_amount': round(float(delta_amount), 6),
                'change_direction': change_direction,
                'pending_exit': status == 'pending_exit',
                'selected': bool(desired_now and not cur_active),
                'open_reason': open_reason,
                'planned_qty': round(float(planned_qty), 6),
                'planned_amount': round(float(planned_amount), 6),
                'target_budget_amount': round(float(target_budget_amount), 6),
                'liquidity_cap_amount': liquidity_cap_amount,
                'source_names': row.get('source_names', []),
            })
        cells.append(row_cells)

    return {
        'key': matrix_key,
        'label': matrix_label,
        'columns': columns,
        'rows': [row_meta[k] for k in summary_keys] + [row_meta[k] for k in row_order],
        'cells': summary_cells + cells,
    }


def _build_snapshot_matrices(group_result: Any, valid_cols: list[str], fee_rates_by_name: dict[str, dict[str, float]], t_idx: int | None, prev_t_idx: int | None, capital_diagnostics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    group_names = getattr(group_result, 'group_names', None) or {}
    return [
        _build_snapshot_matrix(
            matrix_key='raw',
            matrix_label='全产品',
            group_result=group_result,
            valid_cols=valid_cols,
            fee_rates_by_name=fee_rates_by_name,
            t_idx=t_idx,
            prev_t_idx=prev_t_idx,
            capital_diagnostics=capital_diagnostics,
            group_names=group_names,
            collapse_term_structure=False,
        ),
        _build_snapshot_matrix(
            matrix_key='collapsed',
            matrix_label='期限折叠',
            group_result=group_result,
            valid_cols=valid_cols,
            fee_rates_by_name=fee_rates_by_name,
            t_idx=t_idx,
            prev_t_idx=prev_t_idx,
            capital_diagnostics=capital_diagnostics,
            group_names=group_names,
            collapse_term_structure=True,
        ),
    ]


def _snapshot_change_indices(group_result: Any) -> list[int]:
    positions = getattr(group_result, 'position_quantities_np', None)
    memberships = getattr(group_result, 'membership_np', None)
    source = positions if positions is not None else memberships
    if source is None:
        return []
    try:
        arr = np.asarray(source)
        if arr.ndim != 3 or arr.shape[0] < 2:
            return []
        if arr.dtype == np.bool_:
            changed = np.any(arr[1:] != arr[:-1], axis=(1, 2))
        else:
            arr = np.nan_to_num(np.asarray(arr, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
            changed = np.any(np.abs(arr[1:] - arr[:-1]) > 1e-12, axis=(1, 2))
        return [idx + 1 for idx, value in enumerate(changed) if bool(value)]
    except Exception:
        return []


def _latest_group_result(tester: Any):
    """Return the latest available GroupRunResult from a tester."""
    if tester is None:
        return None

    results = getattr(tester, 'results', None)
    if not isinstance(results, dict) or not results:
        return None

    last_factor = getattr(tester, 'last_group_factor', None)
    if last_factor is not None:
        last_result = results.get(last_factor)
        if last_result is not None and getattr(last_result, 'group_result', None) is not None:
            return last_result.group_result

    for _factor, result in reversed(list(results.items())):
        group_result = getattr(result, 'group_result', None)
        if group_result is not None:
            return group_result

    return None


def _build_zero_position_warning(group_result: Any) -> str | None:
    """Explain when the first rebalance cannot open any position."""
    diagnostics = _build_zero_position_diagnostics(group_result)
    return diagnostics['warning'] if diagnostics else None


def _build_zero_position_diagnostics(group_result: Any) -> dict[str, Any] | None:
    """Return a compact explanation when the first rebalance opens no positions."""
    if group_result is None:
        return None
    quantities = getattr(group_result, 'position_quantities_np', None)
    membership = getattr(group_result, 'membership_np', None)
    prices = getattr(group_result, 'price_np', None)
    point_values = getattr(group_result, 'point_value_vec', None)
    lot_sizes = getattr(group_result, 'min_trade_quantity_vec', None)
    open_ratios = getattr(group_result, 'open_ratio_vec', None)
    open_fixed = getattr(group_result, 'open_fixed_vec', None)
    margin_ratios = getattr(group_result, 'margin_ratio_vec', None)
    margin_flags = getattr(group_result, 'is_margin_traded_vec', None)
    initial_capital = getattr(group_result, 'initial_capital', None)
    if quantities is None or membership is None or prices is None:
        return None
    if getattr(quantities, 'size', 0) == 0 or getattr(membership, 'size', 0) == 0 or getattr(prices, 'size', 0) == 0:
        return None
    initial_capital_value = _safe_float(initial_capital)
    if initial_capital_value is None:
        return None

    def _coerce_1d(values: Any, length: int, default: float = 0.0, *, dtype=float) -> np.ndarray:
        arr = np.asarray(values if values is not None else [], dtype=dtype).reshape(-1)
        if arr.size == length:
            return arr
        out = np.full(length, default, dtype=dtype)
        if arr.size > 0:
            limit = min(arr.size, length)
            out[:limit] = arr[:limit]
        return out

    first_membership = np.asarray(membership[0], dtype=bool)
    first_quantities = np.asarray(quantities[0], dtype=float)
    if first_membership.ndim != 2 or first_quantities.ndim != 2:
        return None

    group_count, product_count = first_membership.shape
    price_row = np.asarray(prices[0], dtype=float).reshape(-1)
    if price_row.size != product_count:
        price_row = _coerce_1d(price_row, product_count, default=np.nan)

    point_values_row = _coerce_1d(point_values, product_count, default=1.0)
    lot_sizes_row = _coerce_1d(lot_sizes, product_count, default=1.0)
    open_ratio_row = _coerce_1d(open_ratios, product_count, default=0.0)
    open_fixed_row = _coerce_1d(open_fixed, product_count, default=0.0)
    margin_ratio_row = _coerce_1d(margin_ratios, product_count, default=1.0)
    margin_flag_row = _coerce_1d(margin_flags, product_count, default=False, dtype=bool)
    valid_cols = list(getattr(group_result, 'valid_cols', None) or [])
    group_names = getattr(group_result, 'group_names', None) or {}

    def _group_name(group_index: int) -> str:
        raw = group_names.get(group_index, group_index)
        try:
            return str(raw)
        except Exception:
            return f'第{group_index + 1}组'

    blocked_groups: list[dict[str, Any]] = []
    for g_idx in range(group_count):
        wants_position = first_membership[g_idx]
        if not wants_position.any():
            continue
        has_position = np.any(np.abs(first_quantities[g_idx]) > 1e-12)
        if has_position:
            continue

        active_products = np.where(wants_position)[0]
        if active_products.size == 0:
            continue
        budget_per_product = initial_capital_value / float(active_products.size)
        candidates: list[dict[str, Any]] = []
        for p_idx in active_products:
            price_value = _safe_float(price_row[p_idx]) if p_idx < price_row.size else None
            point_value = _safe_float(point_values_row[p_idx]) if p_idx < point_values_row.size else None
            lot_size = _safe_float(lot_sizes_row[p_idx]) if p_idx < lot_sizes_row.size else None
            open_ratio = _safe_float(open_ratio_row[p_idx]) if p_idx < open_ratio_row.size else 0.0
            open_fee_fixed = _safe_float(open_fixed_row[p_idx]) if p_idx < open_fixed_row.size else 0.0
            margin_ratio = _safe_float(margin_ratio_row[p_idx]) if p_idx < margin_ratio_row.size else None
            if price_value is None or point_value is None or lot_size is None:
                continue
            contract_value = price_value * point_value * lot_size
            if not math.isfinite(contract_value) or contract_value <= 0:
                continue
            occupied = contract_value * (margin_ratio if bool(margin_flag_row[p_idx]) and margin_ratio is not None else 1.0)
            fee = contract_value * float(open_ratio or 0.0) + lot_size * float(open_fee_fixed or 0.0)
            required = occupied + fee
            candidates.append({
                'product_index': int(p_idx),
                'product_name': valid_cols[p_idx] if p_idx < len(valid_cols) else f'#{p_idx}',
                'required_capital': float(required),
                'contract_value': float(contract_value),
                'occupied_capital': float(occupied),
                'fee_capital': float(fee),
                'diagnostic_type': 'estimated',
            })

        if not candidates:
            blocked_groups.append({
                'group_index': int(g_idx),
                'group_name': _group_name(g_idx),
                'active_count': int(active_products.size),
                'budget_per_product': float(budget_per_product),
                'cheapest_product_name': None,
                'cheapest_required_capital': None,
                'cheapest_occupied_capital': None,
                'cheapest_fee_capital': None,
                'diagnostic_type': 'missing_trade_spec',
            })
            continue

        cheapest = min(candidates, key=lambda item: item['required_capital'])
        if budget_per_product + 1e-12 < cheapest['required_capital']:
            blocked_groups.append({
                'group_index': int(g_idx),
                'group_name': _group_name(g_idx),
                'active_count': int(active_products.size),
                'budget_per_product': float(budget_per_product),
                'cheapest_product_name': cheapest['product_name'],
                'cheapest_required_capital': float(cheapest['required_capital']),
                'cheapest_occupied_capital': float(cheapest['occupied_capital']),
                'cheapest_fee_capital': float(cheapest['fee_capital']),
                'diagnostic_type': 'capital_shortage',
            })

    if not blocked_groups:
        return None

    first = blocked_groups[0]
    capital_text = f"{initial_capital_value:,.0f}"
    budget_text = f"{first['budget_per_product']:,.0f}"
    if first.get('diagnostic_type') == 'missing_trade_spec' or first.get('cheapest_required_capital') is None:
        warning = (
            f"首期有 {len(blocked_groups)} 个组未能开出任何仓位。"
            f"按等权分配后，每个活跃品种可分到的预算约 {budget_text} 元，"
            f"但当前结果里缺少完整的合约价值或费率字段，无法精确反推首手需求；"
            f"从实际持仓看，目标仓位已经被压成 0。"
            f"当前初始金额为 {capital_text} 元。"
        )
    else:
        required_text = f"{first['cheapest_required_capital']:,.0f}"
        warning = (
            f"首期有 {len(blocked_groups)} 个组未能开出任何仓位。"
            f"按等权分配后，每个活跃品种可分到的预算约 {budget_text} 元，"
            f"但 {first['group_name']} 里最便宜的品种 {first['cheapest_product_name']} 的一手资金需求约 {required_text} 元，"
            f"因此目标仓位在最小手数上被压成 0。"
            f"当前初始金额为 {capital_text} 元。"
        )
    return {
        'warning': warning,
        'initial_capital': float(initial_capital_value),
        'blocked_group_count': int(len(blocked_groups)),
        'blocked_groups': blocked_groups,
    }


def _compute_return_metrics(r_array: np.ndarray, index_like=None, avg_turnover=None) -> dict:
    """从收益率序列计算绩效指标。"""
    s = pd.Series(r_array).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(s)
    if n == 0:
        return {}
    annual_periods = infer_periods_per_year(index_like) if index_like is not None else 252.0
    cum_s = (1 + s).cumprod()
    dd = (cum_s.cummax() - cum_s) / cum_s.cummax()
    ls_annual = _safe_float((cum_s.iloc[-1] ** (annual_periods / n) - 1) * 100) if n > 1 else None
    ls_dd = _safe_float(dd.max() * 100) if n > 0 else None
    return {
        'Total Return':  _safe_float((cum_s.iloc[-1] - 1) * 100) if n > 0 else None,
        'Annual Return': ls_annual,
        'Volatility':    _safe_float(s.std() * (annual_periods ** 0.5) * 100),
        'Sharpe Ratio':  _safe_float((s.mean() * annual_periods) / (s.std() * annual_periods**0.5)) if s.std() != 0 else None,
        'Max Drawdown':  ls_dd,
        'Calmar Ratio':  _safe_float(float(ls_annual) / float(ls_dd)) if (ls_annual and ls_dd) else None,
        'Win Rate':      _safe_float((s > 0).sum() / n * 100) if n > 0 else None,
        'Mean Return':   _safe_float(s.mean() * 100),
        'Skewness':      _safe_float(s.skew()),
        'Kurtosis':      _safe_float(s.kurtosis()),
        'Avg Turnover':  _safe_float(avg_turnover),
    }


def _compute_ls_metrics(r_ls_array: np.ndarray, report_df: pd.DataFrame, index_like=None) -> dict:
    """从 Long-Short 收益率序列计算绩效指标。"""
    avg_turnover = round(float(
        (report_df['Avg Turnover'].iloc[0] + report_df['Avg Turnover'].iloc[-1]) / 2
    ), 4) if not report_df.empty and 'Avg Turnover' in report_df.columns else None
    return _compute_return_metrics(r_ls_array, index_like=index_like, avg_turnover=avg_turnover)




def _serialize_float_series(values: np.ndarray | list, default: float = 0.0) -> list:
    result = []
    for value in values:
        try:
            fv = float(value)
        except (TypeError, ValueError):
            result.append(default)
            continue
        result.append(round(fv, 8) if not (math.isnan(fv) or math.isinf(fv)) else default)
    return result


def _returns_to_cumulative(returns: np.ndarray) -> np.ndarray:
    safe = np.nan_to_num(np.asarray(returns, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    return np.cumprod(1.0 + safe)


def _unique_group_key(name: str, used: set[str]) -> str:
    """去重：如果 name 已存在，追加 #2, #3..."""
    key = name or 'LS'
    suffix = 2
    while key in used:
        key = f'{name} #{suffix}'
        suffix += 1
    used.add(key)
    return key


def _normalize_group_names(group_names) -> dict[int, str]:
    if not isinstance(group_names, dict):
        return {}
    normalized: dict[int, str] = {}
    for key, value in group_names.items():
        try:
            normalized[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _group_display_key(group_idx: int, group_names=None) -> str:
    """扁平模型：直接用 group_names dict 或索引作为显示名。"""
    names = _normalize_group_names(group_names)
    if group_idx in names:
        return names[group_idx]
    return str(group_idx)


def _metric_display_key(raw_key, group_names=None) -> str:
    try:
        key_int = int(raw_key)
    except (TypeError, ValueError):
        return str(raw_key)
    return _group_display_key(key_int, group_names)


def _compute_weighted_ls_returns(gross_np: np.ndarray, fee_np: np.ndarray, ls_config: dict, n_groups: int) -> tuple[np.ndarray, np.ndarray]:
    gross_np = np.nan_to_num(np.asarray(gross_np, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    fee_np = np.nan_to_num(np.asarray(fee_np, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    legs = []
    for leg in ls_config.get('long') or []:
        if 0 <= leg['group'] < n_groups:
            legs.append({'side': 1.0, 'group': leg['group'], 'cap': leg['weight']})
    for leg in ls_config.get('short') or []:
        if 0 <= leg['group'] < n_groups:
            legs.append({'side': -1.0, 'group': leg['group'], 'cap': leg['weight']})
    if not legs:
        legs = [{'side': 1.0, 'group': 0, 'cap': 0.5}, {'side': -1.0, 'group': n_groups - 1, 'cap': 0.5}]

    initial_caps = np.array([float(leg['cap']) for leg in legs], dtype=float)
    groups = np.array([int(leg['group']) for leg in legs], dtype=int)
    sides = np.array([float(leg['side']) for leg in legs], dtype=float)

    leg_gross = gross_np[:, groups] * sides[np.newaxis, :]
    leg_fee = fee_np[:, groups]
    leg_net = (1.0 - leg_fee) * (1.0 + leg_gross) - 1.0
    leg_net = np.where(np.isfinite(leg_net), leg_net, 0.0)

    leg_caps = initial_caps[np.newaxis, :] * np.cumprod(1.0 + leg_net, axis=0)
    total_caps = np.nansum(leg_caps, axis=1)
    previous_total_caps = np.concatenate([[np.nansum(initial_caps) or 1.0], total_caps[:-1]])
    r_ls = np.divide(
        total_caps,
        previous_total_caps,
        out=np.ones_like(total_caps, dtype=float),
        where=np.abs(previous_total_caps) > 1e-12,
    ) - 1.0
    r_ls = np.where(np.isfinite(r_ls), r_ls, 0.0)
    total_caps = np.where(np.isfinite(total_caps), total_caps, previous_total_caps)
    return r_ls.astype(float), total_caps.astype(float)


def _serialize_group_simulation_result(
    *,
    tester: Any,
    submission_id: str,
    factor_alias: str,
    n_groups: int,
    ls_configs: list[dict] | None,
    rebalance_mode: str,
    simulation_result: dict[str, Any],
    flat_group_info: list[dict] | None = None,
) -> dict[str, Any]:
    report_df = simulation_result['report_df']
    idx_list = simulation_result['idx_list']
    timestamps = [to_epoch_ms(_signal_time(d)) for d in idx_list]
    group_result = simulation_result['group_result']
    n_total = group_result.returns_np.shape[1] if group_result is not None else n_groups

    # ── Resolve group metadata: flat model (all groups are flat entries) ──
    result_group_names = getattr(group_result, 'group_names', None) or {}

    _gross = group_result.gross_returns_np if group_result is not None else None
    gross_np = _gross if _gross is not None else np.zeros((len(timestamps), n_total))
    _fee = group_result.fee_costs_np if group_result is not None else None
    fee_np = _fee if _fee is not None else np.zeros((len(timestamps), n_total))

    # 用模拟中实盘总权益（市值+现金），而非 cumsum(returns)
    _equity = group_result.total_equity_np if group_result is not None else None
    equity_np = _equity if _equity is not None else np.zeros((len(timestamps), n_total))
    # 兜底：总权益为 0 的一律用 initial_capital 填充（首行无数据等边界情况）
    cap = float(getattr(group_result, 'initial_capital', None) or 100000000.0)
    equity_np = np.where(equity_np <= 0, cap, equity_np)
    capital_diagnostics = _build_zero_position_diagnostics(group_result)
    capital_warning = capital_diagnostics['warning'] if capital_diagnostics else None

    # Build flat_group_info lookup: {group_index: info_dict}
    flat_info_by_idx: dict[int, dict] = {}
    if flat_group_info:
        for fi in flat_group_info:
            gi = fi.get('group_index', -1)
            if gi >= 0:
                flat_info_by_idx[gi] = fi

    groups_data = []
    _progress(
        f"simulation serialize groups start submission={submission_id} "
        f"factor={factor_alias} total_groups={n_total}"
    )
    _core_emit_progress("serialize", f"开始序列化分组结果，共 {n_total} 组",
                        completed=0, total=n_total)
    for g in range(n_total):
        _progress(
            f"simulation serialize group {g + 1}/{n_total} "
            f"submission={submission_id} factor={factor_alias}"
        )
        _core_emit_progress("serialize", f"序列化分组 {g+1}/{n_total}",
                            completed=g + 1, total=n_total)
        vals = [round(float(v), 2) if not (math.isnan(v) or math.isinf(v)) else None for v in equity_np[:, g]]
        gross_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in gross_np[:, g]]
        fee_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0 for v in fee_np[:, g]]
        group_key = _group_display_key(g, result_group_names)
        group_name = group_key
        entry = {
            'key': group_key,
            'name': group_name,
            'group_index': g,
            'submission_id': submission_id,
            'timestamps': timestamps,
            'total_equity': vals,
            'gross_returns': gross_vals,
            'fee_costs': fee_vals,
            'trade_notional_ratios': [
                round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else 0.0
                for v in group_result.trade_notional_ratio_np[:, g]
            ] if group_result is not None and group_result.trade_notional_ratio_np is not None else [],
        }
        # If this group has a product-level filter (screened subgroup), attach metadata
        fi = flat_info_by_idx.get(g)
        if fi and fi.get('product_names'):
            entry['product_names'] = fi['product_names']
            if fi.get('id'):
                entry['_id'] = fi['id']
        groups_data.append(entry)
    _progress(f"simulation serialize groups done submission={submission_id} factor={factor_alias}")
    _core_emit_progress("serialize", f"分组结果序列化完成，共 {n_total} 组",
                        completed=n_total, total=n_total)

    metrics: dict = {}
    if not report_df.empty:
        raw_metrics = report_df.to_dict(orient='index')
        for metric_idx, (k, v) in enumerate(raw_metrics.items(), start=1):
            _progress(
                f"simulation serialize metric {metric_idx}/{len(raw_metrics)} "
                f"submission={submission_id} factor={factor_alias}"
            )
            display_key = _metric_display_key(k, result_group_names)
            metrics[display_key] = {
                mk: (None if mv is None or (isinstance(mv, float) and (math.isnan(mv) or math.isinf(mv))) else float(mv))
                for mk, mv in v.items()
            }
    used_keys = set(metrics.keys())
    if ls_configs:
        for ls_idx, ls_config in enumerate(ls_configs, start=1):
            _progress(
                f"simulation LS start {ls_idx}/{len(ls_configs)} "
                f"submission={submission_id} factor={factor_alias} name={ls_config.get('name')}"
            )
            r_ls, ls_cum_arr = _compute_weighted_ls_returns(gross_np, fee_np, ls_config, n_total)
            ls_name = ls_config['name'] or 'Long-Short'
            ls_key = _unique_group_key(ls_name, used_keys)
            ls_vals = [round(float(v), 8) if not (math.isnan(v) or math.isinf(v)) else None for v in ls_cum_arr]
            groups_data.append({
                'key': ls_key,
                'name': ls_name,
                'submission_id': submission_id,
                'timestamps': timestamps,
                'total_equity': ls_vals,
                'gross_returns': _serialize_float_series(r_ls, default=0.0),
                'fee_costs': [0.0] * len(r_ls),
                'trade_notional_ratios': [0.0] * len(r_ls),
                'is_ls': True,
                'ls_info': {'type': 'long_short', 'key': ls_key, 'config': ls_config},
            })
            metrics[ls_key] = _compute_ls_metrics(r_ls, report_df, idx_list)
            _progress(
                f"simulation LS done {ls_idx}/{len(ls_configs)} "
                f"submission={submission_id} factor={factor_alias} key={ls_key}"
            )

    return {
        'success': True,
        'groups': groups_data,
        'metrics': metrics,
        'metrics_meta': _get_metrics_meta(),
        'n_groups': n_total,
        'initial_capital': float(group_result.initial_capital) if group_result is not None and getattr(group_result, 'initial_capital', None) is not None else None,
        'multi_session_active': bool(group_result.multi_session_active) if group_result is not None else False,
        'capital_warning': capital_warning,
        'capital_diagnostics': capital_diagnostics,
        'rebalance_mode': rebalance_mode,
        'submission_id': submission_id,
        'factor_alias': factor_alias,
        'tester_alias': getattr(tester, 'alias', '?'),
        'tester_product_count': len(tester.products) if hasattr(tester, 'products') else 0,
        '_raw': {
            'gross_np': gross_np,
            'fee_np': fee_np,
            'timestamps': timestamps,
            'report_df': report_df,
            'idx_list': idx_list,
        },
    }


@sft_bp.route('/run_group_test', methods=['POST'])
def run_group_test():
    """运行分组测试，接收扁平 groups + ls_configs + page_uuid。
    
    Request JSON:
    {
        "groups": [ {... group fields (name, groupIndex, factorAlias, testerId, feeMode, ...} ],
        "ls_configs": [ {"name": "LS-1", "long": [...], "short": [...]}, ... ],
        "page_uuid": "...",
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "initial_capital": 1000000,
    }
    
    前端只传 groups + ls_configs + page_uuid。
    factor_family_alias 从 page_uuid 对应的 page state 解析。
    fee / rebalance / close-today 从 group 自身字段读取。
    跨 tester LS 自动由 ls_configs legs 中不同 tester_id 的合并（build_overlap_batches）处理。
    """
    data = request.get_json(silent=True) or {}
    success, result = _run_group_test_core(data)
    if success:
        return jsonify(result)
    else:
        status = result.get('status', 500)
        return jsonify(result), status


def _product_list_from_group_payload(group: dict) -> list[str] | None:
    raw = group.get('productMask')
    if raw is None:
        raw = group.get('productList')
    if isinstance(raw, dict):
        selected = [str(name) for name, enabled in raw.items() if enabled]
        return selected or None
    if isinstance(raw, list):
        selected = [str(name) for name in raw if name]
        return selected or None
    return None


def _run_group_test_core(data: dict) -> tuple[bool, dict]:
    """
    核心分组测试逻辑，可以被 /run_group_test (JSON) 和 /run_group_test_stream (SSE) 共享。
    
    返回 (success, dict)
    - success=True：dict 是成功响应
    - success=False：dict 包含 error 和 status 字段
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tools.factors.tests.single_factor_test.group import _FactorGroupTestGroup
    from tools.factors.tests.single_factor_test.group.group_tester import FactorGroupTester

    flat_groups_raw = data.get('groups')
    if not isinstance(flat_groups_raw, list) or not flat_groups_raw:
        return False, {'success': False, 'error': 'groups 必须是非空数组', 'status': 400}
    flat_ls_configs = data.get('ls_configs') or []
    if not isinstance(flat_ls_configs, list):
        flat_ls_configs = []

    request_started = time.perf_counter()
    _progress(
        f"group simulations request start groups={len(flat_groups_raw)} "
        f"ls_configs={len(flat_ls_configs)}"
    )

    rebalance_mode = 'buy_and_hold'

    from tools.data.DataTime import DataTime

    precision = data.get("precision") or data.get("time_precision") or "exact"
    start_dt = DataTime.from_dict(data, precision=precision)
    end_data = dict(data)
    end_data["date"] = end_data.pop("end_date", end_data.pop("date", None))
    end_data["time"] = end_data.pop("end_time", end_data.pop("time", None))
    end_dt = DataTime.from_dict(end_data, precision=precision)

    try:
        initial_capital = _parse_initial_capital(data.get('initial_capital'))
    except ValueError as e:
        return False, {'success': False, 'error': str(e), 'status': 400}

    # ── Build _FactorGroupTestGroup from flat groups array ──
    # Group by tester_id, then by factor_alias
    tester_groups: dict[str, dict[str, list[dict]]] = {}  # tester_id → factor_alias → [group_dicts]
    for g in flat_groups_raw:
        if not isinstance(g, dict):
            continue
        tid = str(g.get('testerId', ''))
        fa = str(g.get('factorAlias', ''))
        if not tid or not fa:
            continue
        tester_groups.setdefault(tid, {}).setdefault(fa, []).append(g)

    # Determine split count per (tester_id, factor_alias). Frontend payload
    # uses camelCase ``splitCount``; backend internals use ``split_count``.
    # means "the factor was split into N buckets"; it is distinct from the
    # number of flat groups submitted in this request.
    split_count_by_triple: dict[tuple, int] = {}
    for tid, by_fa in tester_groups.items():
        for fa, gs in by_fa.items():
            split_count = None
            missing = []
            for g in gs:
                raw_split_count = g.get('splitCount')
                if raw_split_count is not None:
                    split_count = max(split_count or 0, int(raw_split_count))
                else:
                    missing.append(g.get('name') or g.get('key') or g.get('groupIndex'))
            if split_count is None:
                raise ValueError(
                    f"缺少 splitCount: tester_id={tid} factor_alias={fa} "
                    f"groups={missing}"
                )
            split_count_by_triple[(tid, fa)] = split_count

    # Build flat _FactorGroupTestGroup list
    all_flat_groups: list[_FactorGroupTestGroup] = []
    sim_index_by_group: dict[int, int] = {}
    all_ls_configs_by_index: dict[int, list[dict] | None] = {}
    factor_aliases_by_submission: dict[str, list[str]] = {}

    sim_index = 0
    for tid, by_fa in tester_groups.items():
        for fa, gs in by_fa.items():
            split_count = split_count_by_triple[(tid, fa)]
            existing = factor_aliases_by_submission.get(tid) or []
            if fa not in existing:
                existing.append(fa)
            factor_aliases_by_submission[tid] = existing
            for g in gs:
                # frontend groupIndex is 1-based → convert to 0-based
                gi = int(g.get('groupIndex', 1)) - 1
                if gi < 0 or gi >= split_count:
                    raise ValueError(
                        f"groupIndex out of range: {gi + 1} (1-based) not in [1, {split_count}], "
                        f"tester_id={tid} factor_alias={fa}"
                    )
                name = str(g.get('shortAlias') or g.get('name') or g.get('key') or f'{fa}_G{gi}')
                fg = _FactorGroupTestGroup(
                    tester_id=tid,
                    factor_alias=fa,
                    n_groups=split_count,
                    group_index=gi,
                    key=name,
                    name=name,
                    product_list=_product_list_from_group_payload(g),
                    fee_mode=g.get('feeMode'),
                    fee_rate=g.get('feeRate'),
                    fee_modifications=g.get('feeModifications'),
                    use_close_today=bool(g.get('useCloseToday')),
                    rebalance_mode=g.get('rebalanceMode'),
                    liquidity_mode=g.get('liquidityMode'),
                    liquidity_percent=g.get('liquidityPercent'),
                    margin_mode=g.get('marginMode'),
                )
                offset = len(all_flat_groups)
                sim_index_by_group[offset] = sim_index
                all_flat_groups.append(fg)
            all_ls_configs_by_index[sim_index] = flat_ls_configs if flat_ls_configs else None  # all LS configs visible to this spec
            sim_index += 1

    if not all_flat_groups:
        return False, {'success': False, 'error': '没有有效的分组配置', 'status': 400}
    expected_flat_count = data.get('flatCount')
    try:
        expected_flat_count = int(expected_flat_count)
    except (TypeError, ValueError):
        expected_flat_count = len(flat_groups_raw)
    if expected_flat_count != len(all_flat_groups):
        return False, {
            'success': False,
            'error': (
                f'前端传回 {expected_flat_count} 个扁平组，但后端只解析出 '
                f'{len(all_flat_groups)} 个有效分组。请检查派生组是否缺少测试器/因子/组数继承字段。'
            ),
            'status': 400,
        }

    # ── Resolve factor_family_alias from page_uuid ──
    page_uuid = str(data.get('page_uuid') or '')
    factor_family_alias = ''
    if page_uuid:
        try:
            page_state = runtime_state.get_page_state(page_uuid)
            factor_family_alias = str(getattr(page_state, 'factor_family_alias', '') or '')
        except Exception:
            pass
    # Allow override from request (same as SSE handler)
    req_family = data.get('factor_family_alias')
    if req_family:
        factor_family_alias = str(req_family)

    # ── Factor inputs & calendar ──
    auto_group_calendar_freq = bool(data.get('auto_group_calendar_freq', True))
    requested_group_calendar_freq = None if auto_group_calendar_freq else data.get('group_calendar_freq')
    group_factor_params_list = data.get('_group_factor_params_list')
    if not isinstance(group_factor_params_list, list):
        group_factor_params_list = None
    group_owner_username = data.get('_group_owner_username')
    group_owner_username = str(group_owner_username) if group_owner_username else None

    # Ensure testers and factors
    tester0 = None
    for submission_id, factor_aliases in factor_aliases_by_submission.items():
        tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test_prepare_factors')
        if tester0 is None:
            tester0 = tester
        _ensure_tester_factors_for_group(
            tester,
            factor_aliases,
            factor_family_alias,
            params_list=group_factor_params_list,
            username=group_owner_username,
        )
        for factor_alias in factor_aliases:
            factor = tester.resolve_factor(str(factor_alias))
            if factor is None:
                return False, {
                    'success': False,
                    'error': f'未找到因子 {factor_alias}。请确认当前因子参数已保存，或刷新页面后重试。',
                    'status': 400,
                }
            ensure_group_factor_inputs(
                tester,
                factor,
                returns_col=FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
            )

    calendar_indices: list[pd.Index] = []
    all_factor_freqs: list[Any] = []
    for submission_id, factor_aliases in factor_aliases_by_submission.items():
        try:
            tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test_calendar')
        except Exception as exc:
            _progress(f"calendar build skip submission={submission_id} error={exc}")
            continue
        tester_factor_freqs = tester.collect_group_factor_freqs(factor_aliases)
        all_factor_freqs.extend(tester_factor_freqs)
    try:
        effective_group_calendar_freq = FactorTester.resolve_group_calendar_freq_from_factor_freqs(
            all_factor_freqs,
            'auto' if auto_group_calendar_freq else requested_group_calendar_freq,
        )
    except ValueError as exc:
        return False, {'success': False, 'error': str(exc), 'status': 400}
    _progress(
        f"calendar resolve done effective_freq={effective_group_calendar_freq} "
        f"factor_freq_count={len(all_factor_freqs)}"
    )
    for submission_id, factor_aliases in factor_aliases_by_submission.items():
        tester = runtime_state.get_factor_tester(submission_id, caller='run_group_test_calendar_build')
        tester_calendar = tester.build_group_calendar_index(
            factor_aliases,
            requested_calendar_freq=effective_group_calendar_freq,
        )
        if len(tester_calendar) > 0:
            calendar_indices.append(tester_calendar)
    global_calendar_index = tester0.merge_group_calendar_indices(calendar_indices) if tester0 else pd.Index([])

    # ── Fee: resolve per-spec from group fields ──
    # Default: uniform fee=0, no closetoday
    fee_uniform = 0.0
    fee_modifications = None
    use_closetoday = False
    # Scan groups for fee config (first non-none uniform or per_product wins)
    for g in flat_groups_raw:
        fm = g.get('feeMode') or g.get('fee_mode')
        if fm == 'uniform':
            fee_uniform = float(g.get('feeRate', g.get('fee_rate', 0.0025)) or 0.0025)
            break
        elif fm == 'per_product':
            fee_uniform = 0.0
            fee_modifications = g.get('feeModifications') or g.get('fee_modifications') or None
            break
    for g in flat_groups_raw:
        if g.get('useCloseToday') or g.get('use_closetoday'):
            use_closetoday = True
            break

    # ── Run FactorGroupTester ──
    overlap_ratio = float(data.get('group_overlap_ratio', 0.35) or 0.35)
    containment_ratio = float(data.get('group_containment_ratio', 0.60) or 0.60)
    merge_cost_ratio = float(data.get('group_merge_cost_ratio', 1.15) or 1.15)
    group_tester = FactorGroupTester.from_flat_groups(
        all_flat_groups,
        spec_index_by_group=sim_index_by_group,
        ls_configs_by_index=all_ls_configs_by_index,
        start_dt=start_dt,
        end_dt=end_dt,
        calendar_index=global_calendar_index if len(global_calendar_index) > 0 else None,
        rebalance_mode=rebalance_mode,
        overlap_ratio=overlap_ratio,
        containment_ratio=containment_ratio,
        merge_cost_ratio=merge_cost_ratio,
        progress_hook=_progress,
    )
    _progress(
        f"group tester batches overlap_ratio={overlap_ratio:.2f} "
        f"containment_ratio={containment_ratio:.2f} merge_cost_ratio={merge_cost_ratio:.2f} "
        f"batches={group_tester.build_batch_labels()}"
    )
    errors = []
    try:
        raw_results = group_tester.run(
            fee=fee_uniform,
            fee_modifications=fee_modifications,
            use_closetoday=use_closetoday,
            initial_capital=initial_capital,
            rebalance_mode=rebalance_mode,
            start_dt=start_dt,
            end_dt=end_dt,
            calendar_index=global_calendar_index if len(global_calendar_index) > 0 else None,
            progress_hook=_progress,
        )
    except Exception as e:
        errors.append({'error': str(e)})
        raw_results = []

    simulated_flat_count = sum(
        len(item.get('flat_group_info') or [])
        for item in raw_results
        if isinstance(item, dict)
    )
    if simulated_flat_count != len(all_flat_groups):
        return False, {
            'success': False,
            'error': (
                f'分组数量不一致：前端传回 {len(all_flat_groups)} 个有效分组，'
                f'进入 simulate 的分组为 {simulated_flat_count} 个。'
            ),
            'simulation_errors': errors,
            'status': 500,
        }

    submission_results: list[dict | None] = [None] * sim_index
    for raw_result in raw_results:
        idx = int(raw_result.get('simulation_index', -1))
        if idx < 0 or idx >= sim_index:
            continue
        flat_info = raw_result.get('flat_group_info')
        serialized = _serialize_group_simulation_result(
            tester=raw_result['tester'],
            submission_id=str(raw_result.get('submission_id') or ''),
            factor_alias=str(raw_result.get('factor_alias') or ''),
            n_groups=int(raw_result.get('n_groups', 5)),
            ls_configs=raw_result.get('ls_configs'),
            rebalance_mode=rebalance_mode,
            simulation_result=raw_result,
            flat_group_info=flat_info if isinstance(flat_info, list) and flat_info else None,
        )
        serialized['submission_id'] = str(raw_result.get('submission_id') or '')
        serialized['factor_alias'] = str(raw_result.get('factor_alias') or '')
        serialized['n_groups_requested'] = int(raw_result.get('n_groups', 5))
        serialized['simulation_index'] = idx
        submission_results[idx] = serialized
        _progress(f"group tester accepted index={idx + 1}/{sim_index}")

    valid_results = [r for r in submission_results if r is not None]
    _progress(f"submission parallel done valid={len(valid_results)} errors={len(errors)}")
    if not valid_results:
        first_err = errors[0] if errors else {'error': '所有提交条目均失败'}
        return False, {
            'success': False,
            'error': first_err.get('error', '所有提交条目均失败'),
            'traceback': first_err.get('traceback'),
            'simulation_errors': errors,
            'status': 500,
        }

    # ── Per-entry LS configs are already computed inside each simulation result. ──
    # Future: if ls_configs legs span different specs (cross-tester LS),
    # build_overlap_batches merges those specs into one product_coverage_batch,
    # so the LS computation happens naturally inside FactorGroupTester.run().

    # ── Merge results ──
    cross_ls_groups: list[dict] = []
    cross_ls_metrics: dict = {}
    _progress(
        f"simulation merge start valid={len(valid_results)} "
        f"cross_ls={len(cross_ls_groups)}"
    )
    merged_groups = []
    merged_metrics = {}
    used_merged_keys: set[str] = set()
    multi_session_entries = []
    last_n_groups = 0
    last_multi_session = False
    last_rebalance = rebalance_mode

    for br_idx, br in enumerate(valid_results, start=1):
        _progress(
            f"simulation merge result {br_idx}/{len(valid_results)} "
            f"submission={br.get('submission_id')} factor={br.get('factor_alias')}"
        )
        # 移除 _raw 内部数据（不进入 JSON）
        br.pop('_raw', None)
        br_metrics = br.get('metrics') or {}
        consumed_metric_keys: set[str] = set()
        if br.get('groups'):
            for group in br['groups']:
                original_key = str(group.get('key') or group.get('name') or f'Group {len(merged_groups) + 1}')
                merged_key = _unique_group_key(original_key, used_merged_keys)
                if merged_key != original_key:
                    group = dict(group)
                    group['key'] = merged_key
                merged_groups.append(group)
                if original_key in br_metrics:
                    merged_metrics[merged_key] = br_metrics[original_key]
                    consumed_metric_keys.add(original_key)
        for metric_key, metric_value in br_metrics.items():
            if metric_key in consumed_metric_keys:
                continue
            merged_key = _unique_group_key(str(metric_key), used_merged_keys)
            merged_metrics[merged_key] = metric_value
        last_n_groups = br.get('n_groups', last_n_groups)
        simulation_multi_session = bool(br.get('multi_session_active', False))
        if simulation_multi_session:
            multi_session_entries.append({
                'index': br.get('simulation_index'),
                'submission_id': br.get('submission_id'),
                'factor_alias': br.get('factor_alias'),
                'tester_alias': br.get('tester_alias'),
                'n_groups': br.get('n_groups_requested') or br.get('n_groups'),
            })
        last_multi_session = simulation_multi_session or last_multi_session
        last_rebalance = br.get('rebalance_mode', last_rebalance) or last_rebalance

    # 追加跨提交条目 LS 组
    if cross_ls_groups:
        for group_idx, group in enumerate(cross_ls_groups, start=1):
            _progress(f"simulation merge cross LS group {group_idx}/{len(cross_ls_groups)}")
            original_key = str(group.get('key') or group.get('name') or 'Long-Short')
            merged_key = _unique_group_key(original_key, used_merged_keys)
            if merged_key != original_key:
                group = dict(group)
                group['key'] = merged_key
            merged_groups.append(group)
            if original_key in cross_ls_metrics:
                merged_metrics[merged_key] = cross_ls_metrics[original_key]

    _progress(
        f"group simulations request done groups={len(merged_groups)} metrics={len(merged_metrics)} "
        f"elapsed={time.perf_counter() - request_started:.2f}s"
    )
    first_valid = valid_results[0] if valid_results else {}
    return True, {
        'success': True,
        'groups': merged_groups,
        'metrics': merged_metrics,
        'metrics_meta': _get_metrics_meta(),
        'n_groups': last_n_groups,
        'multi_session_active': last_multi_session,
        'multi_session_entries': multi_session_entries,
        'rebalance_mode': last_rebalance,
        'submission_id': first_valid.get('submission_id', ''),
        'factor_alias': first_valid.get('factor_alias', ''),
        'tester_alias': first_valid.get('tester_alias', '?') if valid_results else '?',
        'tester_product_count': first_valid.get('tester_product_count', 0),
        'simulation_count': len(valid_results),
        'cross_entry_ls_count': len(cross_ls_groups),
        'errors': errors if errors else None,
    }

@sft_bp.route('/get_group_snapshot', methods=['POST'])
def get_group_snapshot():
    """获取某个时刻各分组的产品列表及与上一时刻的进出变化。
    
    请求参数：
        submission_id : 提交 ID
        timestamp_ms  : 目标时刻（UTC epoch 毫秒）
    
    返回：{
        groups: [{
            name, 
            products: [...],        // 当前持仓
            products_in: [...],     // 新进（上一时刻没有，当前有）
            products_out: [...],    // 退出（上一时刻有，当前没有）
            turnover_rate: float,   // 换手率
        }, ...]
    }
    """
    data = request.get_json()
    submission_id = data.get('submission_id')
    timestamp_ms  = data.get('timestamp_ms')
    if not submission_id or not timestamp_ms:
        return jsonify({'success': False, 'error': '缺少 submission_id 或 timestamp_ms'}), 400

    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='get_group_snapshot')

        group_result = _latest_group_result(tester)
        valid_cols_raw = group_result.valid_cols if group_result is not None else None
        index_list = list(getattr(group_result, 'index_list', []) or [])
        if group_result is None or not _safe_bool(valid_cols_raw) or not index_list:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400

        time_entries = index_list

        def _epoch_seconds(value):
            ts = _signal_time(value)
            if isinstance(ts, pd.Timestamp):
                return float(to_epoch_ms(ts, display_timezone) / 1000.0)
            if hasattr(ts, 'timestamp'):
                return float(to_epoch_ms(pd.Timestamp(ts), display_timezone) / 1000.0)
            return float(ts)

        display_timezone = _snapshot_display_timezone(group_result, list(valid_cols_raw or []))
        time_epochs = np.array([_epoch_seconds(idx_entry) for idx_entry in time_entries], dtype=float)

        # 前端传来的 UTC epoch 毫秒
        target_epoch = float(timestamp_ms) / 1000.0

        # 找最近的
        best_pos = int(np.argmin(np.abs(time_epochs - target_epoch)))
        best_idx_entry = time_entries[best_pos]

        # 找到上一时刻 — 用 all_times 的 epoch 排序（避免 tuple/array 直接比较）
        # 用 enumerate 添加位置索引作为 tiebreaker，防止 sorted 回退到 tuple 比较
        # （idx_entry 可能为包含 numpy 类型的 tuple，其 __eq__ 会触发 ambiguous truth value）
        sorted_pos = np.argsort(time_epochs, kind='stable')
        current_pos = int(np.flatnonzero(sorted_pos == best_pos)[0]) if sorted_pos.size else 0
        prev_entry = time_entries[int(sorted_pos[current_pos - 1])] if current_pos > 0 else None

        # (ts_epoch, idx_entry) 对列表，供 all_timestamps_ms 构建和前/后导航使用
        all_times = list(zip(time_epochs, time_entries))

        fee_rates_by_name = _product_fee_rates_by_name(group_result)
        positions = getattr(group_result, 'position_quantities_np', None)
        hold_np = getattr(group_result, 'hold_amounts_np', None)
        capital_diagnostics = _build_zero_position_diagnostics(group_result)
        t_idx = None
        if index_list:
            try:
                t_idx = index_list.index(best_idx_entry)
            except ValueError:
                t_idx = None
        prev_t_idx = None
        if prev_entry is not None:
            try:
                prev_t_idx = index_list.index(prev_entry)
            except ValueError:
                prev_t_idx = None

        valid_cols_list = list(group_result.valid_cols) if group_result.valid_cols else []
        matrices = _build_snapshot_matrices(group_result, valid_cols_list, fee_rates_by_name, t_idx, prev_t_idx, capital_diagnostics)

        # 统计当前真实持仓变动，作为顶部摘要
        active_matrix = matrices[0] if matrices else {'columns': []}
        total_changed = 0
        total_prod_count = 0
        for g_idx in range(len(active_matrix.get('columns', []))):
            col = active_matrix['columns'][g_idx]
            total_prod_count += int(col.get('count', 0) or 0)
            if t_idx is not None and positions is not None and t_idx < positions.shape[0] and g_idx < positions.shape[1]:
                cur_pos = positions[t_idx, g_idx]
                prev_pos = positions[prev_t_idx, g_idx] if prev_t_idx is not None and prev_t_idx < positions.shape[0] else None
                current_active = int(np.sum(np.abs(cur_pos) > 1e-12))
                prev_active = int(np.sum(np.abs(prev_pos) > 1e-12)) if prev_pos is not None else 0
                total_changed += abs(current_active - prev_active)
        avg_turnover = total_changed / max(total_prod_count, 1) * 100.0 if total_prod_count > 0 else 0.0

        # 所有时间点（epoch 毫秒），用于前/后导航
        all_timestamps_ms = sorted(set(
            int(ts_epoch * 1000) for ts_epoch, _idx in all_times
        ))
        # 用最接近的 all_timestamps_ms 条目（而非前端传来的不精确 timestamp_ms）
        closest_ms = min(all_timestamps_ms, key=lambda x: abs(x - int(timestamp_ms)))
        current_index = all_timestamps_ms.index(closest_ms)
        change_indices = _snapshot_change_indices(group_result)
        change_timestamps_ms = [
            int(time_epochs[idx] * 1000)
            for idx in change_indices
            if 0 <= idx < len(time_epochs)
        ]
        prev_change_ms = None
        next_change_ms = None
        for change_ms in change_timestamps_ms:
            if change_ms < closest_ms:
                prev_change_ms = change_ms
            elif change_ms > closest_ms and next_change_ms is None:
                next_change_ms = change_ms

        # ── 附加元信息供前端按 shortAlias 分层渲染 (refs #100) ──
        _raw_group_names = getattr(group_result, 'group_names', None) or {}
        snapshot_group_names = {}
        for k, v in _raw_group_names.items():
            try:
                snapshot_group_names[int(k)] = str(v)
            except (TypeError, ValueError):
                snapshot_group_names[str(k)] = str(v)

        return jsonify({
            'success': True,
            'matrices': matrices,
            'default_matrix_key': 'raw',
            'timestamp_ms': closest_ms,
            'has_prev': prev_entry is not None,
            'has_next': current_index >= 0 and current_index < len(all_timestamps_ms) - 1,
            'all_timestamps_ms': all_timestamps_ms,
            'display_timezone': display_timezone,
            'change_timestamps_ms': change_timestamps_ms,
            'prev_change_timestamp_ms': prev_change_ms,
            'next_change_timestamp_ms': next_change_ms,
            'has_prev_change': prev_change_ms is not None,
            'has_next_change': next_change_ms is not None,
            'group_names': snapshot_group_names,
            'capital_warning': capital_diagnostics['warning'] if capital_diagnostics else None,
            'capital_diagnostics': capital_diagnostics,
            'summary': {
                'avg_turnover': round(avg_turnover, 1),
                'total_changed': int(total_changed),
                'total_prod_count': int(total_prod_count),
            },
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/get_group_detail', methods=['POST'])
def get_group_detail():
    """Return first-phase detail analytics for one group from the latest run."""
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    group_index = data.get('group_index')
    if submission_id is None or group_index is None:
        return jsonify({'success': False, 'error': '缺少 submission_id 或 group_index'}), 400
    try:
        group_index = int(group_index)
        tester = runtime_state.get_factor_tester(submission_id, caller='get_group_detail')
        group_result = _latest_group_result(tester)
        products = group_result.get_products_by_group() if group_result is not None else None
        returns_np = group_result.returns_np if group_result is not None else None
        product_contrib_np = group_result.product_gross_contrib_np if group_result is not None else None
        gross_returns_np = group_result.gross_returns_np if group_result is not None else None
        trade_notional_np = group_result.trade_notional_ratio_np if group_result is not None else None
        valid_cols = group_result.valid_cols if group_result is not None else None
        index_list = group_result.index_list if group_result is not None else None
        if not products or returns_np is None or not index_list:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        if group_index < 0 or group_index >= returns_np.shape[1]:
            return jsonify({'success': False, 'error': '分组索引无效'}), 400
        metrics = group_result.report_df if group_result is not None else None
        summary = {}
        if isinstance(metrics, pd.DataFrame) and group_index in metrics.index:
            summary = {
                str(key): _safe_float(value)
                for key, value in metrics.loc[group_index].to_dict().items()
            }
        detail = build_group_detail(
            group_index, products, returns_np, index_list, summary,
            product_contrib_np, valid_cols, gross_returns_np, trade_notional_np,
            group_result.fee_costs_np if group_result is not None else None,
            group_result.open_ratio_vec if group_result is not None else None,
            group_result.close_ratio_vec if group_result is not None else None,
            group_result.close_today_ratio_vec if group_result is not None else None,
        )
        return jsonify({'success': True, 'detail': detail})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})



@sft_bp.route('/get_group_ranking_detail', methods=['POST'])
def get_group_ranking_detail():
    """Return second-phase whole-test ranking analytics from the latest run."""
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    if submission_id is None:
        return jsonify({'success': False, 'error': '缺少 submission_id'}), 400
    try:
        tester = runtime_state.get_factor_tester(submission_id, caller='get_group_ranking_detail')
        group_result = _latest_group_result(tester)
        returns_np = group_result.returns_np if group_result is not None else None
        index_list = group_result.index_list if group_result is not None else None
        if returns_np is None:
            return jsonify({'success': False, 'error': '未找到最近的分组测试结果，请先运行分组测试'}), 400
        return jsonify({'success': True, 'detail': build_group_ranking_detail(returns_np, index_list)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/get_tester_session_info', methods=['POST'])
def get_tester_session_info():
    """返回测试器会话摘要信息（供第3层策略通知表格使用）。

    请求：{submission_ids: [str, ...]}  或  {submission_id: str}

    返回：{
        testers: [{
            submission_id, tester_alias, product_count,
            factors: [{
                alias, name, freq,
                n_groups: int,   // 上次分组测试用的组数
                rebalance_mode,  // 上次使用的再平衡模式
                has_results: bool,
            }]
        }]
    }
    """
    data = request.get_json() or {}
    ids = data.get('submission_ids') or []
    if not ids and data.get('submission_id'):
        ids = [data['submission_id']]
    if not ids:
        return jsonify({'success': False, 'error': '缺少 submission_ids'}), 400

    testers_info = []
    for sid in ids:
        try:
            tester = runtime_state.find_factor_tester(str(sid), allow_suffix=True)
            if tester is None:
                testers_info.append({'submission_id': str(sid), 'error': '未找到测试器实例'})
                continue
            factors_info = []
            for f in (getattr(tester, 'factors', None) or []):
                info = {
                    'alias': getattr(f, 'alias', None) or getattr(f, 'name', '?'),
                    'name': getattr(f, 'name', '?'),
                    'freq': f.freq.name if hasattr(f, 'freq') and f.freq else None,
                }
                # 如果该因子有上次分组测试的结果
                result = tester.results.get(f) if hasattr(tester, 'results') else None
                if result is not None and result.group_result is not None:
                    gr = result.group_result
                    info['n_groups'] = gr.returns_np.shape[1] if hasattr(gr, 'returns_np') and gr.returns_np is not None else None
                    info['rebalance_mode'] = getattr(gr, 'rebalance_mode', None)
                    info['has_results'] = True
                else:
                    info['has_results'] = False
                factors_info.append(info)
            testers_info.append({
                'submission_id': str(sid),
                'tester_alias': getattr(tester, 'alias', '?'),
                'product_count': len(tester.products) if hasattr(tester, 'products') else 0,
                'factors': factors_info,
            })
        except Exception as e:
            testers_info.append({'submission_id': str(sid), 'error': str(e)})

    return jsonify({'success': True, 'testers': testers_info})


# ═══════════════════════════════════════════════════
#  SSE 流式端点
# ═══════════════════════════════════════════════════

@sft_bp.route('/run_group_test_stream', methods=['POST'])
def run_group_test_stream():
    """SSE 流式分组测试——推送 batch/membership/simulate 进度 + 最终结果。"""
    import threading
    import json as _json
    from flask import Response, stream_with_context
    from server.services.sse_progress import SSEProgressEmitter
    from tools.factors.backtest_progress import BacktestProgressRegistry
    from tools.factors.tests.single_factor_test.group.core import (
        register_group_progress,
        unregister_group_progress,
    )

    data = request.get_json(silent=True) or {}

    # ── 在主线程中完成 data 校验 ──
    flat_groups_raw = data.get('groups')
    if not isinstance(flat_groups_raw, list) or not flat_groups_raw:
        def _early_err():
            yield f"event: error\ndata: {_json.dumps({'success': False, 'error': 'groups 必须是非空数组'}, default=str)}\n\n"
        return Response(_early_err(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    # ── Resolve factor_family_alias from page_uuid ──
    page_uuid = str(data.get('page_uuid') or '')
    factor_family_alias = ''
    if page_uuid:
        try:
            page_state = runtime_state.get_page_state(page_uuid)
            factor_family_alias = str(getattr(page_state, 'factor_family_alias', '') or '')
        except Exception:
            pass
    # Allow override from request
    req_family = data.get('factor_family_alias')
    if req_family:
        factor_family_alias = str(req_family)
    if factor_family_alias:
        try:
            factor_family = get_factor_family_instance(
                factor_family_alias,
                username=runtime_state.current_user(),
            )
            data = dict(data)
            data['_group_owner_username'] = runtime_state.current_user()
            data['_group_factor_params_list'] = runtime_state.get_session_params(
                factor_family_alias,
                factor_family,
            )
        except Exception as exc:
            def _early_factor_err():
                yield f"event: error\ndata: {_json.dumps({'success': False, 'error': f'准备分组测试因子参数失败: {exc}'}, default=str)}\n\n"
            return Response(_early_factor_err(), mimetype='text/event-stream',
                            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    emitter = SSEProgressEmitter()
    registry = BacktestProgressRegistry()

    # ── 将 registry 的三个生命周期回调桥接到 SSE emitter ──
    registry.register_before(
        lambda total, groups, phase, extra: emitter.emit_start(
            total=total, groups=groups, phase=phase, **extra,
        )
    )
    registry.register_phase(
        lambda phase, message, completed, total, extra: emitter.emit_progress(
            completed=completed, total=total, phase=phase, message=message, **extra,
        )
    )
    registry.register_after(
        lambda success, data: emitter.emit_result(data) if success else emitter.emit_error(
            data.get('error', '未知错误'),
            traceback=data.get('traceback', ''),
        )
    )

    def _compute_and_emit():
        try:
            # ── 将 registry 桥接到 core.py 的全局注册 ──
            last_progress = {'completed': 0, 'total': 0}
            last_progress_by_batch: dict[int, dict[str, int]] = {}

            def _progress_bridge(phase: str, message: str, extra: dict):
                progress_extra = dict(extra)
                completed = extra.get('completed')
                total = extra.get('total', extra.get('total_batches'))
                product_coverage_batch_index = extra.get('product_coverage_batch_index')
                has_progress_count = completed is not None and total is not None
                if phase == 'init':
                    # init 阶段：发送 start 事件，携带 phases 元数据
                    total_val = total or 0
                    _phases = extra.get('phases', [])
                    # 从 extra 中剥离已显式传递的 kwarg，避免与 emit_start 的显式参数冲突
                    for k in ('total', 'groups', 'phase', 'phases'):
                        progress_extra.pop(k, None)
                    registry.emit_start(
                        total=total_val, groups=extra.get('total_groups', 0),
                        phase='product_coverage_batch',
                        phases=_phases,
                        **progress_extra,
                    )
                elif has_progress_count:
                    last_progress['completed'] = completed
                    last_progress['total'] = total
                    if product_coverage_batch_index is not None:
                        last_progress_by_batch[int(product_coverage_batch_index)] = {
                            'completed': completed,
                            'total': total,
                        }
                    # 剥离已显式传递的参数，避免与 emit_phase 的 keyword 参数冲突
                    for k in ('completed', 'total', 'phase'):
                        progress_extra.pop(k, None)
                    # 所有带进度计数的 phase 直接 emit（包括 factor_eval, returns_eval 等）
                    registry.emit_phase(
                        phase, message=message,
                        completed=completed, total=total,
                        **progress_extra,
                    )
                elif phase == 'info':
                    # info 是信息性消息，转换为当前批次的 progress 事件
                    batch_progress = None
                    if product_coverage_batch_index is not None:
                        batch_progress = last_progress_by_batch.get(int(product_coverage_batch_index))
                    progress = batch_progress or last_progress
                    if progress['completed'] != 0 or progress['total'] != 0:
                        completed = progress['completed']
                        total = progress['total']
                        for k in ('completed', 'total', 'phase'):
                            progress_extra.pop(k, None)
                        registry.emit_phase(
                            phase, message=message,
                            completed=completed, total=total,
                            **progress_extra,
                        )

            register_group_progress(_progress_bridge)

            success, result = _run_group_test_core(data)
            if success:
                registry.emit_result(result)
            else:
                registry.emit_error(
                    result.get('error', '未知错误'),
                    traceback=result.get('traceback', ''),
                )
        except Exception as e:
            import traceback as _tb
            registry.emit_error(str(e), traceback=_tb.format_exc())
        finally:
            unregister_group_progress()
            registry.cleanup()
            emitter.close()

    threading.Thread(target=_compute_and_emit, daemon=True).start()
    return emitter.get_response()
