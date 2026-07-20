"""VolumeCapacityMode — caps each product's |deltas| to participation_rate *
volume for that bar as part of the default order-sizing policy.

`liquidity_mode="infinite"` (the default) means no volume-capacity constraint at
all; `liquidity_mode="volume_participation"` caps to `participation_rate *
volume`. Capacity above the cap is simply discarded for this bar, not
deferred to a later one (no queuing/recovery this round, per plan)."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.modules.market_data import MarketDataModule, current_volume_at
from tools.testers.backtest.modules.order_flow import order_flow_store_for


class VolumeCapacityMode(ExecutableModule):
    key: ClassVar[str] = "volume_capacity"
    label: ClassVar[str] = "成交量容量"

    liquidity_mode: ClassVar[FieldRef[str]] = FieldRef("liquidity_mode")
    participation_rate: ClassVar[FieldRef[float]] = FieldRef("participation_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "liquidity_mode": FieldDefinition(
            public=True, label="成交量容量", default="infinite", control_template="select", tab="volume_capacity",
            options=(("infinite", "不限制"), ("volume_participation", "按成交量占比限制")),
            chip_template="容量约束: {value}", tab_label="成交量容量", tab_order=150,
        ),
        "participation_rate": FieldDefinition(
            public=True, label="参与率", default=0.1, control_template="number", tab="volume_capacity",
            visible_when={"liquidity_mode": ("volume_participation",)},
            chip_template="参与率: {value}", tab_label="成交量容量", tab_order=150,
        ),
    }

    flows: ClassVar[tuple] = ()


def apply_volume_capacity_policy(
    state: object,
    ctx: object,
    strategy: object,
    deltas: dict[Any, float],
) -> dict[Any, float]:
    config_for = getattr(state, "config_for", None)
    config = config_for(strategy) if callable(config_for) else {}
    if config.get(VolumeCapacityMode.liquidity_mode, "infinite") != "volume_participation":
        return deltas
    volume = _current_volume_snapshot(state, ctx)
    store = order_flow_store_for(state)
    rate = config.get(VolumeCapacityMode.participation_rate, 0.1)
    missing_volume_products = [
        product
        for product, quantity in deltas.items()
        if _requires_volume_capacity(quantity) and product not in volume
    ]
    if missing_volume_products:
        _record_missing_volume_capacity_info(state, ctx, strategy, deltas, missing_volume_products)
        raise KeyError(_missing_volume_capacity_message(state, ctx, strategy, deltas, missing_volume_products))
    capped = {
        product: _cap_one(quantity, float(rate) * volume[product]) if _requires_volume_capacity(quantity) else quantity
        for product, quantity in deltas.items()
    }
    if capped != deltas:
        store.record_strategy_step(
            strategy,
            timestamp=getattr(ctx, "timestamp", None),
            step="volume_capacity_cap",
            label="按成交量容量约束截断下单量",
            details={
                "participation_rate": float(rate),
                "before": _stringify_deltas(deltas),
                "after": _stringify_deltas(capped),
            },
        )
    return capped


def _current_volume_snapshot(state: object, ctx: object) -> dict[Any, float]:
    volume = ctx.get(MarketDataModule.volume, {})
    if _is_scalar_volume_snapshot(volume):
        return {product: float(value) for product, value in volume.items()}
    timestamp = getattr(ctx, "timestamp", None)
    if timestamp is None:
        return {}
    return current_volume_at(state, timestamp)


def _is_scalar_volume_snapshot(volume: object) -> bool:
    if not isinstance(volume, dict):
        return False
    for value in volume.values():
        try:
            float(value)
        except (TypeError, ValueError):
            return False
    return True


def _cap_one(quantity: float, capacity: float) -> float:
    if abs(quantity) <= capacity:
        return quantity
    return capacity if quantity > 0 else -capacity


def _requires_volume_capacity(quantity: float) -> bool:
    return quantity != 0


def _record_missing_volume_capacity_info(
    state: object,
    ctx: object,
    strategy: object,
    deltas: dict[Any, float],
    products: list[Any],
) -> None:
    from tools.testers.backtest.modules.runtime_info import record_runtime_info

    timestamp = getattr(ctx, "timestamp", None)
    rows = [_missing_volume_product_details(state, product, deltas.get(product)) for product in products]
    product_text = ", ".join(row["product"] for row in rows)
    record_runtime_info(
        state,
        code="volume_capacity_missing_volume",
        type="成交量容量",
        status="已中止",
        level="error",
        message=f"成交量容量缺少当前 bar volume: {product_text}",
        detail=(
            "volume_participation 需要当前事件 bar 的真实成交量；"
            f"timestamp={timestamp}, strategy={getattr(strategy, 'alias', strategy)}, products={product_text}。"
            "不会使用 0、前值填充或未来成交量替代。"
        ),
        details={
            "timestamp": str(timestamp),
            "strategy": str(getattr(strategy, "alias", strategy)),
            "products": rows,
        },
    )


def _missing_volume_capacity_message(
    state: object,
    ctx: object,
    strategy: object,
    deltas: dict[Any, float],
    products: list[Any],
) -> str:
    timestamp = getattr(ctx, "timestamp", None)
    product_details = ", ".join(
        _missing_volume_product_message(state, product, deltas.get(product))
        for product in products
    )
    return (
        "volume_participation volume capacity requires MarketDataModule volume for "
        f"{product_details} at {timestamp} "
        f"(strategy={getattr(strategy, 'alias', strategy)}; "
        "no zero/ffill/future-volume fallback is allowed)"
    )


def _missing_volume_product_message(state: object, product: Any, delta: float | None) -> str:
    details = _missing_volume_product_details(state, product, delta)
    suffix = f"delta={details['delta']}"
    if details.get("last_observed_volume_timestamp"):
        suffix += f", last_observed_volume_timestamp={details['last_observed_volume_timestamp']}"
    if details.get("loaded_volume_column") is not None:
        suffix += f", loaded_volume_column={details['loaded_volume_column']}"
    return f"{details['product']} ({suffix})"


def _missing_volume_product_details(state: object, product: Any, delta: float | None) -> dict[str, Any]:
    loaded, last_timestamp = _volume_table_coverage_for_product(state, product)
    return {
        "product": str(getattr(product, "name", product)),
        "delta": None if delta is None else float(delta),
        "loaded_volume_column": loaded,
        "last_observed_volume_timestamp": None if last_timestamp is None else str(last_timestamp),
    }


def _volume_table_coverage_for_product(state: object, product: Any) -> tuple[bool | None, Any | None]:
    try:
        from tools.testers.backtest.modules.market_data import volume_table_for
    except Exception:
        return None, None
    table = volume_table_for(state)
    columns = getattr(table, "columns", None)
    if columns is None:
        return None, None
    product_name = str(getattr(product, "name", product))
    matches = [
        column
        for column in list(columns)
        if column is product or str(getattr(column, "name", column)) == product_name
    ]
    if not matches:
        return False, None
    series = table[matches[0]].dropna()
    if series.empty:
        return True, None
    return True, series.index[-1]


def _stringify_deltas(deltas: dict) -> dict[str, float]:
    return {
        str(getattr(product, "name", product)): float(quantity)
        for product, quantity in deltas.items()
    }
