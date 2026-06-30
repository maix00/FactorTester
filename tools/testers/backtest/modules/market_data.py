"""MarketDataModule — owns market data observations and the causal
(no-lookahead) valuation series derived from them.

`raw_prices`/`lot_sizes`/`margin_ratio`/`settlement_price` are supplied by
the data-prep stage that runs before the engine (same division of labor as
the old payload-based runner: this engine never reads from disk/data
sources directly — wiring the real data-prep pipeline into these fields is
production rewiring, step 11). `causal_valuation` only knows how to turn an
already-loaded, possibly-gappy raw_prices frame into a ffill'd, gap-free
`current_prices` lookup — that's the part that's actually this module's own
logic, not someone else's I/O.

The ffill'd table itself is stored on `account` (not `ctx`) because it's
computed once in PRE_REPLAY but needs to survive into every later PER_EVENT
dispatch — `ctx` is scoped to a single dispatch batch and is discarded
right after, `account` is the only thing that lives for the whole run.
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

import pandas as pd

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.time_index_lookup import row_at
from tools.data.types.time_index import DataIndex
from tools.data.field_history import (
    HistoricalFieldLookupError,
    HistoricalFieldFallbackPolicy,
    FieldHistoryProvider,
    TradingDayResolver,
    TRANSACTION_FEE_FIELD_NAMES,
    historical_fields_frame_for_products,
    resolve_historical_fields_for_product,
)


class MarketDataModule(ExecutableModule):
    key: ClassVar[str] = "market_data"
    label: ClassVar[str] = "市场数据"

    raw_prices: ClassVar[FieldRef[Any]] = FieldRef("raw_prices")          # pd.DataFrame, index=ts, columns=Product, may have NaN gaps
    lot_sizes: ClassVar[FieldRef[Any]] = FieldRef("lot_sizes")            # dict[Product, float]
    margin_ratio: ClassVar[FieldRef[Any]] = FieldRef("margin_ratio")      # dict[Product, float]
    settlement_price: ClassVar[FieldRef[Any]] = FieldRef("settlement_price")  # pd.DataFrame, index=ts, columns=Product
    volume: ClassVar[FieldRef[Any]] = FieldRef("volume")                  # dict[Product, float], this bar's traded volume
    historical_field_provider: ClassVar[FieldRef[Any]] = FieldRef("historical_field_provider")
    trading_day_resolver: ClassVar[FieldRef[Any]] = FieldRef("trading_day_resolver")
    historical_field_policy: ClassVar[FieldRef[str]] = FieldRef("historical_field_policy")
    current_historical_fields: ClassVar[FieldRef[dict[str, dict[str, object]]]] = FieldRef("current_historical_fields")
    current_prices: ClassVar[FieldRef[Any]] = FieldRef("current_prices")  # dict[Product, float], looked up per-timestamp
    data_source: ClassVar[FieldRef[str]] = FieldRef("data_source")
        # which raw data source the data-prep stage should load raw_prices/
        # volume/etc. from -- read by that upstream stage (via
        # strategy_config_builder), not by any Flow in this module itself
    frequency: ClassVar[FieldRef[str]] = FieldRef("frequency")
        # bar granularity of the underlying market data (distinct from
        # FactorSignalModule.signal_freq, which is how often the strategy
        # rebalances -- a strategy can rebalance daily on top of minute bars)

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "raw_prices": FieldDefinition(public=False),
        "lot_sizes": FieldDefinition(public=False),
        "margin_ratio": FieldDefinition(public=False),
        "settlement_price": FieldDefinition(public=False),
        "volume": FieldDefinition(public=False),
        "historical_field_provider": FieldDefinition(public=False),
        "trading_day_resolver": FieldDefinition(public=False),
        "historical_field_policy": FieldDefinition(
            public=True,
            default=str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
            control_template="select",
            tab="market_rules",
            chip_template="历史字段: {value}",
            tab_label="市场规则",
            tab_order=170,
            options=(
                (str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value), "真实历史数据"),
                (str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value), "最新数据向前填充"),
            ),
        ),
        "current_historical_fields": FieldDefinition(public=False),
        "data_source": FieldDefinition(
            public=True, default="", control_template="select", tab="data_source",
            options=(("", "自动"),),
            chip_template="数据源: {value}",
            tab_label="数据源",
            tab_order=35,
        ),
        "frequency": FieldDefinition(
            public=True, default="", control_template="select", tab="frequency",
            options=(("", "自动"),),
            chip_template="Bar频率: {value}",
            tab_label="数据频率",
            tab_order=36,
        ),
    }

    load_raw_market_data: ClassVar[Flow] = Flow(
        "load_raw_market_data", inputs=(), outputs=(
            raw_prices, lot_sizes, margin_ratio, settlement_price, volume,
            historical_field_provider, trading_day_resolver, historical_field_policy,
        ),
        phase=Phase.PRE_REPLAY, order=40,
        compute=lambda account, ctx: _load_raw_market_data(account, ctx),
    )
    causal_valuation: ClassVar[Flow] = Flow(
        "causal_valuation", inputs=(raw_prices,), outputs=(),
        phase=Phase.PRE_REPLAY, order=45, after=(load_raw_market_data,),
        compute=lambda account, ctx: _causal_valuation(account, ctx),
    )

    lookup_current_prices_on_signal: ClassVar[Flow] = Flow(
        "lookup_current_prices_on_signal", inputs=(), outputs=(current_prices,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=1,
        compute=lambda account, ctx: ctx.set(MarketDataModule.current_prices, current_prices_at(account, ctx.timestamp)),
    )
    lookup_current_prices_on_bar: ClassVar[Flow] = Flow(
        "lookup_current_prices_on_bar", inputs=(), outputs=(current_prices,),
        phase=Phase.PER_EVENT, event_kind=EventKind.BAR, order=1,
        compute=lambda account, ctx: ctx.set(MarketDataModule.current_prices, current_prices_at(account, ctx.timestamp)),
    )
    lookup_current_prices_on_order: ClassVar[Flow] = Flow(
        "lookup_current_prices_on_order", inputs=(), outputs=(current_prices,),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=1,
        compute=lambda account, ctx: ctx.set(MarketDataModule.current_prices, current_prices_at(account, ctx.timestamp)),
    )
    lookup_volume_on_signal: ClassVar[Flow] = Flow(
        "lookup_volume_on_signal", inputs=(), outputs=(volume,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=1,
        compute=lambda account, ctx: ctx.set(MarketDataModule.volume, current_volume_at(account, ctx.timestamp)),
    )
    lookup_historical_fields_on_signal: ClassVar[Flow] = Flow(
        "lookup_historical_fields_on_signal", inputs=(),
        outputs=(current_historical_fields,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=2,
        compute=lambda account, ctx: ctx.set(
            MarketDataModule.current_historical_fields,
            current_historical_fields_at(account, ctx.timestamp),
        ),
    )
    lookup_historical_fields_on_order: ClassVar[Flow] = Flow(
        "lookup_historical_fields_on_order", inputs=(),
        outputs=(current_historical_fields,),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=2,
        compute=lambda account, ctx: ctx.set(
            MarketDataModule.current_historical_fields,
            current_historical_fields_at(account, ctx.timestamp),
        ),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        load_raw_market_data, causal_valuation,
        lookup_current_prices_on_bar, lookup_current_prices_on_signal,
        lookup_current_prices_on_order, lookup_volume_on_signal,
        lookup_historical_fields_on_signal, lookup_historical_fields_on_order,
    )


def _load_raw_market_data(account, ctx) -> None:
    """Pass through whatever the data-prep stage already populated on the
    account-level input — this Flow exists so the dependency graph has an
    explicit producer for these fields; it does not perform I/O itself."""
    raw = getattr(account, "raw_market_data", {})
    ctx.set(MarketDataModule.raw_prices, raw.get("raw_prices"))
    ctx.set(MarketDataModule.lot_sizes, raw.get("lot_sizes", {}))
    ctx.set(MarketDataModule.margin_ratio, raw.get("margin_ratio", {}))
    ctx.set(MarketDataModule.settlement_price, raw.get("settlement_price"))
    ctx.set(MarketDataModule.volume, raw.get("volume"))
    ctx.set(MarketDataModule.historical_field_provider, raw.get("historical_field_provider"))
    ctx.set(MarketDataModule.trading_day_resolver, raw.get("trading_day_resolver"))
    ctx.set(
        MarketDataModule.historical_field_policy,
        raw.get("historical_field_policy", str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value)),
    )
    account.historical_field_provider = raw.get("historical_field_provider")
    account.trading_day_resolver = raw.get("trading_day_resolver")
    account.historical_field_policy = raw.get(
        "historical_field_policy",
        str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
    )
    account.historical_field_names = tuple(raw.get("historical_field_names", ()))
    account.historical_field_frames = raw.get("historical_field_frames")
    account.volume_table = raw.get("volume")  # not ffill'd -- a gap means zero
                                                # traded volume, not "carry the last
                                                # observed value forward"


def _causal_valuation(account, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    account.current_prices_table = raw_prices.ffill()


def current_prices_at(account, timestamp: pd.Timestamp) -> dict:
    """Look up the per-product price dict at `timestamp` from the ffill'd
    table on `account` — never indexes past `timestamp` (no-lookahead is
    guaranteed structurally: an as-of lookup only ever reflects rows up to
    and including that timestamp, since `ffill()` only propagates forward
    from earlier rows, never backward).

    The table keeps its original (trading_day, ..., trade_time) MultiIndex
    when the underlying data is minute-level -- `row_at` resolves the actual
    timestamp level via `DataIndex` regardless of how many other levels are
    present. Real minute-level data has session gaps (lunch break, day/night
    session boundary) that a fixed signal/order schedule doesn't always land
    on exactly, so this uses an as-of lookup (last known row at or before
    `timestamp`) rather than requiring an exact hit.
    """
    table = account.current_prices_table
    row = row_at(table, timestamp, asof=True)
    return {product: float(row[product]) for product in table.columns}


def current_volume_at(account, timestamp: pd.Timestamp) -> dict:
    """Look up this bar's traded volume per product — no ffill (a gap means
    zero volume traded, not "carry the last observed volume forward")."""
    table = account.volume_table
    if table is None:
        return {}
    row = row_at(table, timestamp)
    return {product: float(row[product]) for product in table.columns}


def current_historical_fields_at(account, timestamp: pd.Timestamp) -> dict[str, dict[str, object]]:
    """按事件时间查当前历史字段。

    MarketDataModule 只消费公共 FieldHistoryProvider，不关心字段来自 Guosen、
    OpenCTP 还是未来别的数据源。严格真实数据模式下，缺产品/缺交易日/缺字段会
    由 provider 直接抛出 MissingHistoricalField 或 MissingTradingDay。
    """
    provider = cast(FieldHistoryProvider | None, getattr(account, "historical_field_provider", None))
    if provider is None:
        return {}
    resolver = cast(TradingDayResolver | None, getattr(account, "trading_day_resolver", None))
    if resolver is None:
        from tools.data.field_history import MissingTradingDay
        raise MissingTradingDay("trading_day_resolver is required for MarketDataModule historical fields")
    policy = str(
        getattr(
            account,
            "historical_field_policy",
            str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
        )
    )
    field_names = cast(tuple[object, ...], tuple(getattr(account, "historical_field_names", ())))
    if not field_names:
        return {}
    table = getattr(account, "current_prices_table", None)
    instruments = list(table.columns) if table is not None else []
    frames = getattr(account, "historical_field_frames", None)
    if isinstance(frames, dict):
        return _historical_fields_at_from_frames(frames, instruments, timestamp)
    result: dict[str, dict[str, object]] = {}
    for instrument in instruments:
        try:
            values = resolve_historical_fields_for_product(
                instrument,
                timestamp,
                provider=provider,
                trading_day_resolver=resolver,
                field_names=field_names,
                fallback=policy,
            )
        except HistoricalFieldLookupError:
            raise
        result[str(instrument)] = values
    return result


def historical_field_frames_for_market_data(
    products: list[Any],
    index: pd.Index,
    *,
    provider: FieldHistoryProvider,
    trading_day_resolver: TradingDayResolver,
    field_names: tuple[object, ...],
    policy: str,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for provider_for_fields, names in _historical_field_provider_groups(provider, field_names):
        result.update(historical_fields_frame_for_products(
            products,
            index,
            provider=provider_for_fields,
            trading_day_resolver=trading_day_resolver,
            field_names=names,
            fallback=policy,
        ))
    return result


def _historical_field_provider_groups(
    provider: FieldHistoryProvider,
    field_names: tuple[object, ...],
) -> list[tuple[FieldHistoryProvider, tuple[object, ...]]]:
    limit_order_fields = {"MinLimitOrderVolume", "MaxLimitOrderVolume", "MaxMarketOrderVolume"}
    fee_fields = set(TRANSACTION_FEE_FIELD_NAMES) | {"VolumeMultiple"}
    limit_names = tuple(name for name in field_names if str(name) in limit_order_fields)
    market_rule_names = tuple(
        name for name in field_names
        if str(name) in fee_fields and str(name) not in limit_order_fields
    )
    other_names = tuple(
        name for name in field_names
        if str(name) not in limit_order_fields and str(name) not in fee_fields
    )
    groups: list[tuple[FieldHistoryProvider, tuple[object, ...]]] = []
    if limit_names:
        from sources.FieldHistory.views.LimitOrderVolume import load_unified_provider

        groups.append((load_unified_provider(), limit_names))
    if market_rule_names:
        from sources.FieldHistory.views.TransactionFee import load_unified_provider

        groups.append((load_unified_provider(), market_rule_names))
    if other_names:
        groups.append((provider, other_names))
    return groups


def _historical_fields_at_from_frames(
    frames: dict[str, pd.DataFrame],
    instruments: list[Any],
    timestamp: pd.Timestamp,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {str(instrument): {} for instrument in instruments}
    for field_name, frame in frames.items():
        # FieldHistoryProvider stores its frames tz-naive (it normalises
        # every lookup key via _normalise_timestamp_key); event timestamps
        # here are tz-aware, so align via DataIndex before indexing.
        lookup_timestamp = DataIndex(frame.index).tz_align(timestamp)
        if lookup_timestamp not in frame.index:
            continue
        row = frame.loc[lookup_timestamp]
        for instrument in instruments:
            column = _historical_field_frame_column_for(frame, instrument)
            if column is not None:
                result[str(instrument)][str(field_name)] = row[str(column)]
    return result


def _historical_field_frame_column_for(frame: pd.DataFrame, instrument: Any) -> object | None:
    candidates: list[object] = [instrument, str(instrument)]
    for attr_name in ("name", "symbol", "code"):
        attr = getattr(instrument, attr_name, None)
        if attr is not None:
            candidates.append(str(attr))
    for candidate in dict.fromkeys(candidates):
        if candidate in frame.columns:
            return candidate
    return None
