"""Execute one prepared group-membership plan on the selected framework."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
import threading
import uuid

import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataIndex

from ..workers import EngineWorkerDispatcher, WorkerRequest
from ..workers.runners.native import run_group_strategy as run_native_group_strategy
from ..cancellation import BacktestCancelled


def execute_group_plan(
    group_tester,
    *,
    engine: str,
    settings_by_group: Mapping[str, Mapping[str, Any]],
    initial_capital: float,
    long_short_configs: list[Mapping[str, Any]] | None = None,
    progress: Callable[[str, str, int, int, Mapping[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Build raw membership input once; strategy targets remain engine-owned."""

    def _check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise BacktestCancelled()

    _check_cancelled()
    plans = group_tester.build_batch_execution_plans()
    _check_cancelled()
    if len(plans) != 1:
        raise ValueError(
            f"event backtest requires one unified plan, received {len(plans)} plans"
        )
    fallback_policies = {
        str(values.get("market_rule_fallback") or "latest_available")
        for values in settings_by_group.values()
    }
    if len(fallback_policies) != 1:
        raise ValueError("market_rule_fallback is local-only and must match all groups")
    market_rule_fallback = next(iter(fallback_policies))
    plan = group_tester.enrich_batch_execution_plan(
        plans[0],
        fee=0.0,
        fee_modifications=None,
        use_closetoday=False,
        market_rule_fallback=market_rule_fallback,
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
    owner_index_by_group_id = {
        str(owner.get("group_id") or ""): index
        for index, owner in enumerate(plan.group_owner)
        if owner.get("group_id")
    }

    def _resolve_ls_leg_indices(legs: Any, label: str, position: int) -> tuple[int, ...]:
        result: list[int] = []
        for leg in legs or ():
            if not isinstance(leg, Mapping):
                continue
            group_id = str(leg.get("group_id") or leg.get("groupId") or "")
            if group_id:
                if group_id not in owner_index_by_group_id:
                    raise ValueError(
                        f"Long-Short #{position + 1} {label} group_id={group_id!r} "
                        "is not part of this run"
                    )
                result.append(owner_index_by_group_id[group_id])
                continue
            if "group" in leg:
                result.append(int(leg["group"]))
        return tuple(result)

    for position, config in enumerate(long_short_configs or []):
        long_indices = _resolve_ls_leg_indices(config.get("long"), "long", position)
        short_indices = _resolve_ls_leg_indices(config.get("short"), "short", position)
        source_index = long_indices[0] if long_indices else -1
        if source_index < 0 or source_index >= len(plan.group_owner):
            raise ValueError(f"Long-Short #{position + 1} has no valid long group")
        if any(index < 0 or index >= len(plan.group_owner) for index in short_indices):
            raise ValueError(f"Long-Short #{position + 1} has no valid short group")
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
        "signal_kind": "group_membership",
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
            "provenance": spec.rule_provenance or {},
        },
    }
    if any(
        str(config.get("liquidity_mode") or "infinite") == "volume_participation"
        for config in strategy_configs
    ):
        if not plan.trade_products:
            raise ValueError("volume participation requires resolved trade products")
        volume_values = _load_bar_volumes(
            plan.trade_products,
            pd.DatetimeIndex(timestamps),
            plan.entries[0].shared_inputs.source_freq,
        )
        payload["volumes"] = {
            name: volume_values[:, column].tolist()
            for column, name in enumerate(plan.trade_product_names)
        }
    engine_label = {
        "native": "Native",
        "backtrader": "Backtrader",
        "qlib": "Qlib",
        "zipline": "Zipline",
        "rqalpha": "RQAlpha",
    }.get(engine, engine)
    if progress is not None:
        progress(
            "framework_execution",
            f"{engine_label} 开始计算策略 target 并执行事件回测",
            0,
            1,
            {"engine": engine},
        )
    def _event_progress(completed, total, timestamp) -> None:
        _check_cancelled()
        if progress is not None:
            progress(
                "event_replay",
                f"{engine_label} 回放至 {timestamp.isoformat()}",
                completed,
                total,
                {"engine": engine, "event_timestamp": timestamp.isoformat()},
            )

    if engine == "native":
        result = run_native_group_strategy(payload, progress=_event_progress)
    elif engine in {"backtrader", "qlib", "zipline", "rqalpha"}:
        result = EngineWorkerDispatcher().dispatch(
            WorkerRequest(payload["run_id"], engine, "run_group_strategy", payload),
            timeout_seconds=600,
            progress=lambda item: _event_progress(
                int(item["completed"]),
                int(item["total"]),
                pd.Timestamp(item["event_timestamp"]),
            ),
            cancel_event=cancel_event,
        ).result
    else:
        raise ValueError(f"unsupported backtest engine: {engine}")
    if progress is not None:
        progress(
            "framework_execution",
            f"{engine_label} 事件回测完成",
            1,
            1,
            {"engine": engine},
        )
    return {
        "engine_result": result,
        "payload": payload,
        "group_owner": execution_owners,
        "settings_by_strategy": settings_by_strategy,
        "simulation_count": len(plan.entries),
        "signal_kind": "group_membership",
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


def _load_bar_volumes(products, timestamps: pd.DatetimeIndex, source_freq) -> np.ndarray:
    """Aggregate observed contract volume into consecutive decision intervals."""

    result = np.zeros((len(timestamps), len(products)), dtype=float)
    for column, product in enumerate(products):
        data_meta = getattr(product, source_freq.name)
        frame = data_meta.get_and_adjust_cols([DataColumn.VOLUME.name], copy=False)
        if frame.empty or DataColumn.VOLUME.name not in frame.columns:
            raise ValueError(
                f"{getattr(product, 'name', product)} has no observed volume at {source_freq.name}"
            )
        signal_index = pd.DatetimeIndex(DataIndex(frame.index).signal_index)
        values = pd.to_numeric(
            frame[DataColumn.VOLUME.name], errors="coerce"
        ).fillna(0.0).to_numpy(dtype=float)
        valid = np.isfinite(values) & (values >= 0)
        cumulative = np.concatenate([[0.0], np.cumsum(np.where(valid, values, 0.0))])
        right = np.searchsorted(signal_index, timestamps, side="right")
        left = np.concatenate([[0], right[:-1]])
        result[:, column] = cumulative[right] - cumulative[left]
    return result
