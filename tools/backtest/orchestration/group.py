"""Execute one prepared group-membership plan on the selected framework."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import uuid

import numpy as np
import pandas as pd

from ..workers import EngineWorkerDispatcher, WorkerRequest
from ..workers.runners.native import run_group_strategy as run_native_group_strategy


def execute_group_plan(
    group_tester,
    *,
    engine: str,
    settings_by_group: Mapping[str, Mapping[str, Any]],
    initial_capital: float,
    long_short_configs: list[Mapping[str, Any]] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Build raw membership input once; strategy targets remain engine-owned."""

    plans = group_tester.build_batch_execution_plans()
    if len(plans) != 1:
        raise ValueError(
            f"event backtest requires one unified plan, received {len(plans)} plans"
        )
    plan = group_tester.enrich_batch_execution_plan(
        plans[0], fee=0.0, fee_modifications=None, use_closetoday=False
    )
    if plan.merged_price_np is None or plan.merged_spec_bundle is None:
        raise ValueError("group execution plan is missing prices or market rules")
    all_timestamps = np.asarray(plan.entries[0].shared_inputs.index_list, dtype=object)
    strategy_configs = []
    execution_owners = list(plan.group_owner)
    settings_by_strategy: dict[str, dict[str, Any]] = {}
    for membership_index, owner in enumerate(plan.group_owner):
        group_id = str(owner.get("group_id") or "")
        if group_id not in settings_by_group:
            raise ValueError(
                f"missing resolved settings for group_id={group_id!r}; owner={owner}"
            )
        values = dict(settings_by_group[group_id])
        values.update({
            "strategy_id": group_id,
            "display_name": str(owner.get("group_name") or group_id),
            "group_id": group_id,
            "initial_capital": float(values.get("initial_capital") or initial_capital),
            "fee_rate": _fee_rate(values),
            "membership_index": membership_index,
        })
        strategy_configs.append(values)
        settings_by_strategy[group_id] = values
    for position, config in enumerate(long_short_configs or []):
        long_indices = tuple(int(leg["group"]) for leg in config.get("long") or ())
        short_indices = tuple(int(leg["group"]) for leg in config.get("short") or ())
        source_index = long_indices[0] if long_indices else -1
        if source_index < 0 or source_index >= len(plan.group_owner):
            raise ValueError(f"Long-Short #{position + 1} has no valid long group")
        source_group_id = str(plan.group_owner[source_index].get("group_id") or "")
        values = dict(settings_by_group[source_group_id])
        strategy_id = f"long-short:{position + 1}"
        display_name = str(config.get("name") or strategy_id)
        values.update({
            "strategy_id": strategy_id,
            "strategy_kind": "long_short",
            "display_name": display_name,
            "long_indices": list(long_indices),
            "short_indices": list(short_indices),
            "initial_capital": float(values.get("initial_capital") or initial_capital),
            "fee_rate": _fee_rate(values),
        })
        strategy_configs.append(values)
        settings_by_strategy[strategy_id] = values
        execution_owners.append({
            "simulation_index": plan.group_owner[source_index].get("simulation_index"),
            "submission_id": plan.group_owner[source_index].get("submission_id"),
            "factor_alias": plan.group_owner[source_index].get("factor_alias"),
            "requested_n_groups": plan.group_owner[source_index].get("requested_n_groups"),
            "group_index": len(execution_owners),
            "group_name": display_name,
            "group_id": strategy_id,
            "is_ls": True,
        })
    spec = plan.merged_spec_bundle
    raw_prices = np.asarray(plan.merged_price_np, dtype=float)
    available = np.isfinite(raw_prices) & (raw_prices > 0)
    replay_mask = np.any(available, axis=1)
    if np.count_nonzero(replay_mask) < 2:
        raise ValueError("group execution requires at least two observable market slices")
    timestamps = tuple(all_timestamps[replay_mask].tolist())
    execution_prices = _causal_valuation_prices(raw_prices)[replay_mask]
    payload = {
        "run_id": uuid.uuid4().hex,
        "timestamps": [value.isoformat() for value in timestamps],
        "instruments": list(plan.trade_product_names),
        "prices": {
            name: execution_prices[:, column].tolist()
            for column, name in enumerate(plan.trade_product_names)
        },
        "membership": np.asarray(
            plan.merged_membership_np[replay_mask], dtype=bool
        ).tolist(),
        "signal_updates": np.asarray(
            plan.merged_signal_update_mask[replay_mask], dtype=bool
        ).tolist(),
        "price_available": available[replay_mask].tolist(),
        "initial_cash": float(initial_capital),
        "strategy_configs": strategy_configs,
        "market_rules": {
            "multipliers": np.asarray(spec.multiplier_mat, dtype=float)[replay_mask].tolist(),
            "lot_sizes": np.asarray(spec.min_trade_quantity_mat, dtype=float)[replay_mask].tolist(),
            "margin_ratios": np.asarray(spec.long_margin_ratio_mat, dtype=float)[replay_mask].tolist(),
            "min_ticks": np.asarray(spec.min_tick_mat, dtype=float)[replay_mask].tolist(),
        },
    }
    if progress is not None:
        progress(f"{engine} 开始计算策略 target 并执行事件回测", 0, 1)
    if engine == "native":
        result = run_native_group_strategy(payload)
    elif engine in {"backtrader", "qlib", "zipline"}:
        result = EngineWorkerDispatcher().dispatch(
            WorkerRequest(payload["run_id"], engine, "run_group_strategy", payload),
            timeout_seconds=600,
        ).result
    else:
        raise ValueError(f"unsupported backtest engine: {engine}")
    if progress is not None:
        progress(f"{engine} 事件回测完成", 1, 1)
    return {
        "engine_result": result,
        "payload": payload,
        "group_owner": execution_owners,
        "settings_by_strategy": settings_by_strategy,
        "simulation_count": len(plan.entries),
    }


def _fee_rate(values: Mapping[str, Any]) -> float:
    mode = str(values.get("fee_mode") or "market")
    if mode == "none":
        return 0.0
    if mode == "custom":
        return float(values.get("custom_fee_rate") or 0.0)
    if mode == "market":
        # Historical fee matrices will be forwarded per timestamp in the next provider phase.
        return 0.0
    raise ValueError(f"unsupported fee mode: {mode}")


def _causal_valuation_prices(prices: np.ndarray) -> np.ndarray:
    """Carry only previously observed quotes; never backfill from the future."""

    frame = pd.DataFrame(np.asarray(prices, dtype=float)).where(
        np.isfinite(prices) & (prices > 0)
    )
    return frame.ffill().fillna(1.0).to_numpy(dtype=float)
