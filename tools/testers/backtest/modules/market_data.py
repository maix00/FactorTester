"""MarketDataModule — owns market data observations and the causal
(no-lookahead) valuation series derived from them.

Market data can arrive either as an explicit `raw_market_data` payload (legacy
test/adaptor path) or through this module's resolved load plan. The load plan
is strategy-scoped up to the coverage stage and becomes a concrete
product/frequency/source list before raw tables are read. `causal_valuation`
then turns the already-loaded, possibly-gappy raw_prices frame into a ffill'd,
gap-free `current_prices` lookup.

The ffill'd table itself is stored in `state.market_data_store` (not `ctx`)
because it's computed once in PRE_REPLAY but needs to survive into every later
PER_EVENT dispatch — `ctx` is scoped to a single dispatch batch and is
discarded right after, while BacktestRunState-owned stores live for the whole run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, ClassVar, cast

import pandas as pd

from tools.data.types import DataColumn
from tools.data.types.time_freq import DataFreq
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.custom_product import CustomProductModule, apply_custom_product_fields
from tools.testers.backtest.modules.engine import EngineModule, engine_mode_for
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.run_window import RunWindowModule
from tools.testers.backtest.modules.term_structure import TermStructureExpandModule
from tools.testers.backtest.modules.time_index_lookup import row_at, signal_timestamps
from tools.data.types.time_index import DataIndex
from tools.data.field_history import (
    HistoricalFieldLookupError,
    HistoricalFieldFallbackPolicy,
    FieldHistoryProvider,
    TradingDayResolver,
    TRANSACTION_FEE_FIELD_NAMES,
    build_trading_day_resolver_from_market_data,
    historical_fields_frame_for_products,
    load_market_rule_field_provider,
    resolve_historical_fields_for_product,
)
from tools.data.providers.DataProviderProductTS import DataProviderProductTS
from tools.traderules import (
    OrderTradeConstraint,
    exchange_order_constraints_for_snapshot,
    exchange_rule_defaults_for_product,
    exchange_tradable_status_for_snapshot,
)


@dataclass
class MarketDataStore:
    raw_input: dict[str, Any] = field(default_factory=dict)
    request: dict[str, Any] = field(default_factory=dict)
    load_plan: list[Any] = field(default_factory=list)
    required_data_source_by_strategy: dict[Any, tuple[str, ...]] = field(default_factory=dict)
    required_frequency_by_strategy: dict[Any, DataFreq] = field(default_factory=dict)
    excluded_out_of_range: tuple[Any, ...] = ()
    series_by_product: dict[Any, Any] = field(default_factory=dict)
    raw_prices_table: Any = None
    current_prices_table: Any = None
    market_price_tables: dict[str, Any] = field(default_factory=dict)
    volume_table: Any = None
    included_products: frozenset[Any] | None = None
    historical_field_provider: Any = None
    trading_day_resolver: Any = None
    historical_field_policy: str | None = None
    historical_field_names: tuple[Any, ...] = ()
    historical_field_frames: Any = None
    runtime_info_excluded_product_sets: list[tuple[Any, ...]] = field(default_factory=list)

    def publish_raw(self, raw: dict[str, Any]) -> None:
        self.raw_prices_table = raw.get("raw_prices")
        self.market_price_tables = raw.get("price_tables") or {"close": raw.get("raw_prices")}
        self.historical_field_provider = raw.get("historical_field_provider")
        included_products = raw.get("included_products")
        self.included_products = frozenset(included_products) if included_products is not None else None
        self.excluded_out_of_range = tuple(raw.get("excluded_out_of_range_products", ()))
        self.historical_field_names = tuple(raw.get("historical_field_names", ()))
        self.volume_table = raw.get("volume")


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
    current_historical_fields: ClassVar[FieldRef[dict[Any, dict[str, object]]]] = FieldRef("current_historical_fields")
    current_prices: ClassVar[FieldRef[Any]] = FieldRef("current_prices")  # dict[Product, float], looked up per-timestamp
    current_market_snapshot: ClassVar[FieldRef[Any]] = FieldRef("current_market_snapshot")
        # dict[str, dict[Product, float]], looked up per timestamp. Price
        # bases (open/high/low/close/vwap/settlement/pre_settlement) and
        # volume share the same event timestamp semantics; legacy consumers
        # still read current_prices as the close-price view.
    current_tradable_status: ClassVar[FieldRef[Any]] = FieldRef("current_tradable_status")
        # dict[Product, bool] for the current event timestamp. This is the
        # market-mechanics gate ("can an order be attempted now?"), distinct
        # from factor membership. Today it is inferred from usable prices;
        # exchange-rule modules can later override/extend it with halt/limit
        # state without changing strategy modules.
    current_order_constraints: ClassVar[FieldRef[Any]] = FieldRef("current_order_constraints")
        # dict[Product, OrderTradeConstraint]. This is side-aware and is
        # consumed by order execution after buy/sell direction is known.
    data_source_mode: ClassVar[FieldRef[str]] = FieldRef("data_source_mode")
    data_source: ClassVar[FieldRef[str]] = FieldRef("data_source")
        # which raw data source the data-prep stage should load raw_prices/
        # volume/etc. from -- read by that upstream stage (via
        # strategy_config_builder), not by any Flow in this module itself
    freq_mode: ClassVar[FieldRef[str]] = FieldRef("freq_mode")
    freq_fixed: ClassVar[FieldRef[str]] = FieldRef("freq_fixed")
    frequency: ClassVar[FieldRef[str]] = FieldRef("frequency")
        # bar granularity of the underlying market data (distinct from
        # FactorSignalModule.signal_freq, which is how often the strategy
        # rebalances -- a strategy can rebalance daily on top of minute bars)
    required_data_source: ClassVar[FieldRef[Any]] = FieldRef("required_data_source")
    required_frequency: ClassVar[FieldRef[DataFreq]] = FieldRef("required_frequency")

    _fee_mode_ref: ClassVar[FieldRef[str]] = FieldRef("fee_mode", owner="FeeModule")
    _margin_mode_ref: ClassVar[FieldRef[str]] = FieldRef("margin_mode", owner="MarginModule")
    _accounting_mode_ref: ClassVar[FieldRef[str]] = FieldRef("accounting_mode", owner="TradingRuleModule")

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
            label="历史字段",
            default=str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value),
            control_template="select",
            tab="engine",
            editable_when={"engine_mode": ("custom",)},
            default_when={
                "engine_mode": {
                    "exact": str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
                    "auto": str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value),
                    "custom": str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value),
                },
            },
            chip_template="历史字段: {value}",
            tab_label="执行引擎",
            tab_order=10,
            options=(
                (str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value), "真实历史数据"),
                (str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value), "缺失历史数据由时间差最近的数据向后填充"),
            ),
        ),
        "current_historical_fields": FieldDefinition(public=False),
        "current_market_snapshot": FieldDefinition(public=False),
        "current_tradable_status": FieldDefinition(public=False),
        "current_order_constraints": FieldDefinition(public=False),
        "data_source_mode": FieldDefinition(
            public=True, label="数据源模式", default="auto", control_template="select", tab="data_source",
            options=(("auto", "自动选择"), ("list", "指定列表")),
            chip_template="数据源模式: {value}",
            tab_label="数据源",
            tab_order=35,
        ),
        "data_source": FieldDefinition(
            public=True, label="数据源", default="", control_template="select", tab="data_source",
            visible_when={"data_source_mode": ("list",)},
            options=(("", "自动"), ("Local", "Local")),
            chip_template="数据源: {value}",
            tab_label="数据源",
            tab_order=35,
        ),
        "freq_mode": FieldDefinition(
            public=True, label="频率模式", default="auto", control_template="select", tab="frequency",
            options=(("auto", "自动推断"), ("fixed", "固定频率")),
            chip_template="频率模式: {value}",
            tab_label="数据频率",
            tab_order=36,
        ),
        "freq_fixed": FieldDefinition(
            public=True, label="固定频率", default="MIN1", control_template="text", tab="frequency",
            visible_when={"freq_mode": ("fixed",)},
            chip_template="固定频率: {value}",
            tab_label="数据频率",
            tab_order=36,
        ),
        "frequency": FieldDefinition(
            public=False, label="Bar频率", default="", control_template="select", tab="frequency",
            options=(("", "自动"),),
            chip_template="Bar频率: {value}",
            tab_label="数据频率",
            tab_order=36,
        ),
        "required_frequency": FieldDefinition(public=False),
        "required_data_source": FieldDefinition(public=False),
    }

    resolve_market_data_request: ClassVar[Flow] = Flow(
        "resolve_market_data_request",
        inputs=(data_source_mode, data_source, freq_mode, freq_fixed, frequency, FactorModule.factor),
        outputs=(required_data_source, required_frequency),
        phase=Phase.PRE_REPLAY, order=37,
        after=(RunWindowModule.resolve_run_window, ProductSelectionModule.resolve_product_selection),
        compute=lambda state, ctx: _resolve_market_data_request(state, ctx),
        strategy_scoped=True,
        description="解析行情数据源与频率",
    )

    check_market_data_coverage: ClassVar[Flow] = Flow(
        "check_market_data_coverage",
        inputs=(
            required_data_source, required_frequency, ProductSelectionModule.products,
            TermStructureExpandModule.expanded_contracts, TermStructureExpandModule.contract_metadata,
        ),
        outputs=(),
        phase=Phase.PRE_REPLAY, order=38,
        after=(resolve_market_data_request, TermStructureExpandModule.expand_term_structure),
        description="检查产品覆盖期",
        compute=lambda state, ctx: _check_market_data_coverage(state, ctx),
    )
    load_raw_market_data: ClassVar[Flow] = Flow(
        "load_raw_market_data",
        inputs=(EngineModule.engine_mode, TermStructureExpandModule.contract_metadata),
        outputs=(
            raw_prices, lot_sizes, margin_ratio, settlement_price, volume, historical_field_provider,
        ),
        phase=Phase.PRE_REPLAY, order=40, after=(check_market_data_coverage,),
        description="装载行情数据",
        compute=lambda state, ctx: _load_raw_market_data(state, ctx),
    )
    build_trading_day_resolver: ClassVar[Flow] = Flow(
        "build_trading_day_resolver", inputs=(raw_prices,), outputs=(trading_day_resolver,),
        phase=Phase.PRE_REPLAY, order=43, after=(load_raw_market_data,),
        description="建立交易日映射",
        compute=lambda state, ctx: _build_trading_day_resolver(state, ctx),
    )
    load_historical_fields: ClassVar[Flow] = Flow(
        "load_historical_fields", inputs=(raw_prices, trading_day_resolver), outputs=(historical_field_policy,),
        phase=Phase.PRE_REPLAY, order=44, after=(build_trading_day_resolver,),
        description="加载历史交易规则字段",
        compute=lambda state, ctx: _load_historical_fields(state, ctx),
    )
    causal_valuation: ClassVar[Flow] = Flow(
        "causal_valuation", inputs=(raw_prices,), outputs=(),
        phase=Phase.PRE_REPLAY, order=45, after=(load_raw_market_data,),
        description="生成因果估值序列",
        compute=lambda state, ctx: _causal_valuation(state, ctx),
    )

    lookup_current_prices_on_signal: ClassVar[Flow] = Flow(
        "lookup_current_prices_on_signal", inputs=(), outputs=(current_prices, current_market_snapshot, current_tradable_status, current_order_constraints),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=1,
        description="读取信号时点价格",
        compute=lambda state, ctx: _set_current_market_snapshot(state, ctx),
    )
    lookup_current_prices_on_bar: ClassVar[Flow] = Flow(
        "lookup_current_prices_on_bar", inputs=(), outputs=(current_prices, current_market_snapshot, current_tradable_status, current_order_constraints),
        phase=Phase.PER_EVENT, event_kind=EventKind.BAR, order=1,
        description="读取行情时点价格",
        compute=lambda state, ctx: _set_current_market_snapshot(state, ctx),
    )
    lookup_current_prices_on_order: ClassVar[Flow] = Flow(
        "lookup_current_prices_on_order", inputs=(), outputs=(current_prices, current_market_snapshot, current_tradable_status, current_order_constraints),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=1,
        description="读取订单时点价格",
        compute=lambda state, ctx: _set_current_market_snapshot(state, ctx),
    )
    lookup_current_prices_on_ledger_notice: ClassVar[Flow] = Flow(
        "lookup_current_prices_on_ledger_notice", inputs=(), outputs=(current_prices, current_market_snapshot, current_tradable_status, current_order_constraints),
        phase=Phase.PER_EVENT, event_kind=EventKind.LEDGER_NOTICE, order=1,
        description="读取账本通知时点价格",
        compute=lambda state, ctx: _set_current_market_snapshot(state, ctx),
    )
    lookup_volume_on_signal: ClassVar[Flow] = Flow(
        "lookup_volume_on_signal", inputs=(), outputs=(volume,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=1,
        description="读取成交量",
        compute=lambda state, ctx: ctx.set(MarketDataModule.volume, current_volume_at(state, ctx.timestamp)),
    )
    lookup_historical_fields_on_signal: ClassVar[Flow] = Flow(
        "lookup_historical_fields_on_signal",
        inputs=(_fee_mode_ref, _margin_mode_ref, _accounting_mode_ref, CustomProductModule.custom_product_fields),
        outputs=(current_historical_fields,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=2,
        description="读取交易规则字段",
        compute=lambda state, ctx: _set_current_historical_fields(state, ctx),
    )
    lookup_historical_fields_on_order: ClassVar[Flow] = Flow(
        "lookup_historical_fields_on_order",
        inputs=(_fee_mode_ref, _margin_mode_ref, _accounting_mode_ref, CustomProductModule.custom_product_fields),
        outputs=(current_historical_fields,),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=2,
        description="读取订单交易规则字段",
        compute=lambda state, ctx: _set_current_historical_fields(state, ctx),
    )
    lookup_historical_fields_on_ledger_notice: ClassVar[Flow] = Flow(
        "lookup_historical_fields_on_ledger_notice",
        inputs=(_fee_mode_ref, _margin_mode_ref, _accounting_mode_ref, CustomProductModule.custom_product_fields),
        outputs=(current_historical_fields,),
        phase=Phase.PER_EVENT, event_kind=EventKind.LEDGER_NOTICE, order=2,
        description="读取账本通知交易规则字段",
        compute=lambda state, ctx: _set_current_historical_fields(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        resolve_market_data_request, check_market_data_coverage, load_raw_market_data, build_trading_day_resolver,
        load_historical_fields, causal_valuation,
        lookup_current_prices_on_bar, lookup_current_prices_on_signal,
        lookup_current_prices_on_order, lookup_current_prices_on_ledger_notice, lookup_volume_on_signal,
        lookup_historical_fields_on_signal, lookup_historical_fields_on_order,
        lookup_historical_fields_on_ledger_notice,
    )


_MARKET_RULE_FIELD_NAMES = (
    "VolumeMultiple",
)
_MARGIN_FIELD_NAMES = (
    "LongMarginRatioByMoney",
    "ShortMarginRatioByMoney",
    "LongMarginRatioByVolume",
    "ShortMarginRatioByVolume",
)


def _market_data_request(state) -> dict[str, Any]:
    request = getattr(state, "market_data_request", None)
    raw = getattr(state, "raw_market_data", None)
    if isinstance(raw, dict) and raw.get("raw_prices") is not None:
        return {"raw_market_data": raw}
    if not isinstance(request, dict):
        return {}
    return request


def market_data_store_for(state):
    return state.market_data_store


def raw_prices_table_for(state):
    return market_data_store_for(state).raw_prices_table


def current_prices_table_for(state):
    store = market_data_store_for(state)
    return store.current_prices_table


def volume_table_for(state):
    return market_data_store_for(state).volume_table


def market_price_tables_for(state) -> dict[str, Any]:
    return market_data_store_for(state).market_price_tables


def _resolve_market_data_request(state, ctx) -> None:
    request = _market_data_request(state)
    if "raw_market_data" in request:
        return
    frequencies_by_strategy: dict[Any, DataFreq] = {}
    sources_by_strategy: dict[Any, tuple[str, ...]] = {}
    for strategy in state.strategy_configs:
        products = list(ctx.get_for(ProductSelectionModule.products, strategy, frozenset()))
        if not products:
            continue
        config = state.config_for(strategy)
        source = _required_data_source_for_strategy(config)
        frequency = _required_frequency_for_strategy(config, products)
        sources_by_strategy[strategy] = source
        frequencies_by_strategy[strategy] = frequency
        ctx.set_for(MarketDataModule.required_data_source, strategy, source)
        ctx.set_for(MarketDataModule.required_frequency, strategy, frequency)

    store = market_data_store_for(state)
    store.required_data_source_by_strategy = dict(sources_by_strategy)
    store.required_frequency_by_strategy = dict(frequencies_by_strategy)
    unique_sources = {source for source in sources_by_strategy.values()}
    if len(unique_sources) == 1:
        ctx.set(MarketDataModule.required_data_source, next(iter(unique_sources), ()))


def _required_data_source_for_strategy(config) -> tuple[str, ...]:
    mode = str(config.get(MarketDataModule.data_source_mode, "") or "").strip().lower()
    values = _parse_data_source_values(config.get(MarketDataModule.data_source))
    if not mode:
        mode = "list" if values else "auto"
    if mode == "auto":
        return ()
    if mode != "list":
        raise ValueError(f"不支持的数据源模式: {mode!r}")
    if not values:
        raise ValueError("数据源模式为指定列表时，必须至少选择一个数据源")
    return values


def _parse_data_source_values(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        values = [str(item).strip() for item in raw]
    else:
        values = [str(raw).strip()]
    return tuple(dict.fromkeys(item for item in values if item and item != "auto"))


def _data_source_key_label(source: tuple[str, ...]) -> str:
    return "auto" if not source else "+".join(source)


def _data_source_instance_label(source: Any | None) -> str:
    if source is None:
        return "auto"
    key = getattr(source, "key", None) or getattr(source, "name", None)
    return str(key or source)


def _required_frequency_for_strategy(config, products: list[Any]) -> DataFreq:
    mode = str(config.get(MarketDataModule.freq_mode, "") or "").strip().lower()
    legacy_frequency = str(config.get(MarketDataModule.frequency, "") or "").strip()
    if not mode:
        mode = "fixed" if legacy_frequency else "auto"
    if mode == "fixed":
        return DataFreq(config.get(MarketDataModule.freq_fixed) or legacy_frequency or "MIN1")
    if mode != "auto":
        raise ValueError(f"不支持的数据频率模式: {mode!r}")
    return _infer_required_frequency_from_factor(config.get(FactorModule.factor), products)


def _infer_required_frequency_from_factor(factor: Any, products: list[Any]) -> DataFreq:
    desired_freqs = _desired_factor_frequencies(factor)
    available_set: set[DataFreq] | None = None
    for product in products:
        freqs = set(_product_available_freqs(product))
        if desired_freqs and not _has_compatible_frequency(freqs, desired_freqs):
            continue
        available_set = freqs if available_set is None else available_set & freqs
    available = sorted(available_set or set(), key=lambda item: item.value, reverse=True)
    if not available:
        raise ValueError("产品数据没有公共可用频率，无法确定 Bar 频率")
    if desired_freqs:
        frequency = next((freq for freq in available if _frequency_compatible(freq, desired_freqs)), None)
        if frequency is None:
            desired_text = ", ".join(sorted(freq.name for freq in desired_freqs))
            available_text = ", ".join(sorted(freq.name for freq in available))
            raise ValueError(f"期望频率 {{{desired_text}}} 与产品可用频率 {{{available_text}}} 不兼容")
        return frequency
    return available[-1]


def _desired_factor_frequencies(factor: Any) -> set[DataFreq]:
    factor_obj = getattr(factor, "underlying_factor", None) or getattr(factor, "_factor", None) or factor
    desired: set[DataFreq] = set()
    signal_freq = getattr(factor_obj, "freq", None) or getattr(factor_obj, "_freq", None)
    if signal_freq is not None:
        desired.add(DataFreq(signal_freq))
    expr = (
        getattr(factor_obj, "_expr", None)
        or getattr(factor_obj, "expression", None)
        or getattr(factor, "expression", None)
    )
    for const_ref in getattr(expr, "const_refs", ()) or ():
        try:
            desired.add(DataFreq(getattr(const_ref, "value")))
        except Exception:
            continue
    return desired


def _product_available_freqs(product: Any) -> list[DataFreq]:
    return [_coerce_data_freq(freq) for freq in product.list_available_freqs()]


def _frequency_compatible(available: DataFreq, desired_freqs: set[DataFreq]) -> bool:
    return all(desired.value.total_seconds() % available.value.total_seconds() == 0 for desired in desired_freqs)


def _has_compatible_frequency(available_freqs: set[DataFreq], desired_freqs: set[DataFreq]) -> bool:
    return any(_frequency_compatible(available, desired_freqs) for available in available_freqs)


def _check_market_data_coverage(state, ctx) -> None:
    request = _market_data_request(state)
    store = market_data_store_for(state)
    if "raw_market_data" in request:
        raw = request["raw_market_data"]
        store.series_by_product = {
            product: raw.get("raw_prices")[product]
            for product in getattr(raw.get("raw_prices"), "columns", [])
        }
        store.market_price_tables = raw.get("price_tables") or {"close": raw.get("raw_prices")}
        store.excluded_out_of_range = tuple(raw.get("excluded_out_of_range_products", ()))
        return
    products_by_strategy = _products_by_strategy_from_selection_context(state, ctx)
    products = _products_from_selection_context(state, ctx) or list(request.get("products") or ())
    start_dt = request.get("start_dt")
    end_dt = request.get("end_dt")
    global_required_frequency = ctx.get(MarketDataModule.required_frequency)
    global_required_source = ctx.get(MarketDataModule.required_data_source, ())
    term_structure_contracts = _term_structure_concrete_contracts(state, ctx)
    missing_products: list[str] = []
    missing_frequency_products: list[str] = []
    missing_source_products: list[str] = []
    excluded_out_of_range: list[Any] = []
    load_plan: list[tuple[Any, DataFreq, Any | None]] = []
    planned_by_product: dict[Any, tuple[DataFreq, Any | None]] = {}

    def outside_window(product: Any) -> bool:
        # A concrete contract that TermStructureExpandModule.expand_term_structure
        # produced was already filtered to intersect the run window (that's what
        # get_contract_list(start_date, end_date) does) -- the term structure
        # table is the authoritative source for "should this contract have data
        # here", not the data-file-driven heuristic _product_outside_run_window
        # uses for continuous/non-term-structure products (which infers listing/
        # delisting from a *different* catalog and can disagree). So a
        # term-structure contract is never silently excluded here: if it has no
        # data, that's a real gap and must surface as a hard error below.
        if product in term_structure_contracts:
            return False
        return _product_outside_run_window(product, start_dt, end_dt)

    def plan_product(product: Any, required_frequency: DataFreq | None, required_source: tuple[str, ...] | None) -> None:
        try:
            available_freqs = _product_available_freqs(product)
            if not available_freqs:
                if outside_window(product):
                    excluded_out_of_range.append(product)
                else:
                    missing_products.append(str(getattr(product, "name", product)))
                return
            freq = _select_required_product_frequency(product, available_freqs, required_frequency)
            if freq is None:
                if outside_window(product):
                    excluded_out_of_range.append(product)
                else:
                    missing_frequency_products.append(str(getattr(product, "name", product)))
                return
            existing = planned_by_product.get(product)
            if existing is not None and existing[0].name != freq.name:
                old_freq, old_source = existing
                raise _MarketDataPlanConflict(
                    "同一产品在同一批 native 回测中解析出多个行情请求："
                    f"{getattr(product, 'name', product)} "
                    f"{old_freq.name}/{_data_source_instance_label(old_source)} 与 "
                    f"{freq.name}/待解析数据源。"
                    "请拆分批次，或等待按产品-频率-数据源分组的价格表实现。"
                )
            source = _select_required_product_source(product, freq, required_source)
            if source is _MISSING_DATA_SOURCE:
                if outside_window(product):
                    excluded_out_of_range.append(product)
                else:
                    missing_source_products.append(str(getattr(product, "name", product)))
                return
            if existing is not None and not _same_market_data_plan(existing, (freq, source)):
                old_freq, old_source = existing
                raise _MarketDataPlanConflict(
                    "同一产品在同一批 native 回测中解析出多个行情请求："
                    f"{getattr(product, 'name', product)} "
                    f"{old_freq.name}/{_data_source_instance_label(old_source)} 与 "
                    f"{freq.name}/{_data_source_instance_label(source)}。"
                    "请拆分批次，或等待按产品-频率-数据源分组的价格表实现。"
                )
            if existing is None:
                planned_by_product[product] = (freq, source)
                load_plan.append((product, freq, source))
        except _MarketDataPlanConflict:
            raise
        except (ValueError, KeyError):
            if outside_window(product):
                excluded_out_of_range.append(product)
            else:
                missing_products.append(str(getattr(product, "name", product)))

    if products_by_strategy:
        for strategy, strategy_products in products_by_strategy.items():
            required_frequency = ctx.get_for(
                MarketDataModule.required_frequency,
                strategy,
                global_required_frequency,
            )
            required_source = ctx.get_for(
                MarketDataModule.required_data_source,
                strategy,
                global_required_source,
            )
            for product in strategy_products:
                plan_product(product, required_frequency, required_source)
    else:
        for product in products:
            plan_product(product, global_required_frequency, global_required_source)

    if missing_products:
        _raise_missing_market_data(missing_products, start_dt, end_dt)
    if missing_frequency_products:
        required = _required_frequency_label(global_required_frequency, ctx, products_by_strategy)
        raise ValueError(
            f"产品缺少所需 Bar 频率 {required}: "
            f"{'、'.join(_dedupe_names(missing_frequency_products))}"
        )
    if missing_source_products:
        required = _required_source_label(global_required_source, ctx, products_by_strategy)
        raise ValueError(
            f"产品缺少所需数据源 {required}: "
            f"{'、'.join(_dedupe_names(missing_source_products))}"
        )
    store.load_plan = load_plan
    store.excluded_out_of_range = tuple(_dedupe_products(excluded_out_of_range))
    _record_excluded_out_of_range_products(state, store.excluded_out_of_range)


def _select_required_product_frequency(
    product: Any,
    available_freqs: list[DataFreq],
    required_frequency: DataFreq | None,
) -> DataFreq | None:
    if required_frequency is None:
        current_freq = getattr(product, "current_freq", None)
        if current_freq is not None:
            current_data_freq = _coerce_data_freq(current_freq)
            if current_data_freq in available_freqs:
                return current_data_freq
        return None
    required_name = required_frequency.name
    for freq in available_freqs:
        if freq.name == required_name:
            return freq
    return None


def _coerce_data_freq(freq: Any) -> DataFreq:
    return DataFreq(freq)


_MISSING_DATA_SOURCE = object()


class _MarketDataPlanConflict(ValueError):
    pass


def _select_required_product_source(product: Any, freq: Any, required_source: tuple[str, ...] | None) -> Any | None:
    available = DataProviderProductTS.available_for_product(product, freq)
    if not required_source:
        return available[0] if available else None
    for candidate in _expand_data_source_selection(required_source):
        resolved = _resolve_candidate_data_source(candidate, product, freq, available)
        if resolved is not None:
            return resolved
    return _MISSING_DATA_SOURCE


def _expand_data_source_selection(source_keys: tuple[str, ...]) -> tuple[Any, ...]:
    result: list[Any] = []
    for key in source_keys:
        result.extend(_data_sources_for_key_or_bundle(key))
    deduped: list[Any] = []
    for source in result:
        if source not in deduped:
            deduped.append(source)
    return tuple(deduped)


def _data_sources_for_key_or_bundle(key: str) -> tuple[Any, ...]:
    try:
        return (DataProviderProductTS[key],)
    except KeyError:
        return _data_sources_for_bundle(key)


def _resolve_candidate_data_source(candidate: Any, product: Any, freq: Any, available: list[Any]) -> Any | None:
    resolve = getattr(candidate, "resolve_for_product", None)
    if callable(resolve):
        resolved = resolve(product, freq)
        if resolved in available:
            return resolved
    return candidate if candidate in available else None


def _data_sources_for_bundle(key: str) -> tuple[Any, ...]:
    try:
        from sources.Local import data_sources_for_bundle
    except Exception:
        return ()
    return data_sources_for_bundle(key)


def _tradable_universe_for_strategy(state, ctx, strategy) -> list[Any]:
    """Abstract products (needed for the pre-rollover tradability check in
    _tradable_signal_values, which still keys signal_value by the abstract
    product) UNION each of their expanded concrete contracts (needed once
    TermStructureExpandModule.resolve_tradable_target_weights rekeys a
    target to a concrete contract object -- that object needs its own loaded
    price series, distinct from its parent's continuous one). A product that
    doesn't support term structure expands to just itself (see
    _expand_product_contracts' is_identity branch), so this union is a no-op
    duplicate for the common non-futures case, not a special case to guard."""
    abstract_products = list(ctx.get_for(ProductSelectionModule.products, strategy, frozenset()))
    seen = set(abstract_products)
    universe = list(abstract_products)
    expanded_by_strategy = ctx.get_for(TermStructureExpandModule.expanded_contracts, strategy, frozenset())
    for contract in expanded_by_strategy:
        if contract not in seen:
            seen.add(contract)
            universe.append(contract)
    return universe


def _term_structure_concrete_contracts(state, ctx) -> frozenset[Any]:
    """Every concrete contract TermStructureExpandModule.expand_term_structure
    produced for any strategy in this run -- i.e. every metadata row that
    isn't the identity/no-term-structure passthrough. These are the objects
    whose data coverage must be judged against the term structure table
    (already listing-window-filtered), not against the data-file-driven
    heuristic _product_outside_run_window uses for continuous products."""
    contracts: set[Any] = set()
    strategies = ctx.active_strategies or frozenset(state.strategy_configs)
    for strategy in strategies:
        for row in ctx.get_for(TermStructureExpandModule.contract_metadata, strategy, ()):
            if row.get("is_identity"):
                continue
            contract = row.get("contract_object")
            if contract is not None:
                contracts.add(contract)
    return frozenset(contracts)


def _products_from_selection_context(state, ctx) -> list[Any]:
    products: list[Any] = []
    seen: set[Any] = set()
    for strategy in state.strategy_configs:
        for product in _tradable_universe_for_strategy(state, ctx, strategy):
            if product not in seen:
                seen.add(product)
                products.append(product)
    return products


def _products_by_strategy_from_selection_context(state, ctx) -> dict[Any, tuple[Any, ...]]:
    result: dict[Any, tuple[Any, ...]] = {}
    for strategy in state.strategy_configs:
        products = tuple(_tradable_universe_for_strategy(state, ctx, strategy))
        if products:
            result[strategy] = products
    return result


def _same_market_data_plan(
    left: tuple[DataFreq, Any | None],
    right: tuple[DataFreq, Any | None],
) -> bool:
    left_freq, left_source = left
    right_freq, right_source = right
    return left_freq.name == right_freq.name and left_source == right_source


def _required_frequency_label(
    global_frequency: Any,
    ctx,
    products_by_strategy: dict[Any, tuple[Any, ...]],
) -> str:
    if global_frequency is not None:
        return getattr(global_frequency, "name", str(global_frequency))
    labels = {
        getattr(
            ctx.get_for(MarketDataModule.required_frequency, strategy),
            "name",
            str(ctx.get_for(MarketDataModule.required_frequency, strategy)),
        )
        for strategy in products_by_strategy
        if ctx.get_for(MarketDataModule.required_frequency, strategy) is not None
    }
    return "、".join(sorted(labels)) if labels else "auto"


def _required_source_label(
    global_source: Any,
    ctx,
    products_by_strategy: dict[Any, tuple[Any, ...]],
) -> str:
    if global_source is not None:
        return _data_source_key_label(tuple(global_source or ()))
    labels = {
        _data_source_key_label(tuple(ctx.get_for(MarketDataModule.required_data_source, strategy, ()) or ()))
        for strategy in products_by_strategy
    }
    return "、".join(sorted(labels)) if labels else "auto"


def _load_raw_market_data(state, ctx) -> None:
    request = _market_data_request(state)
    if "raw_market_data" in request:
        raw = request["raw_market_data"]
        _publish_raw_market_data(state, ctx, raw)
        return
    start_dt = request.get("start_dt")
    end_dt = request.get("end_dt")
    warmup_window = _live_market_data_load_warmup_window(state)
    series_by_product: dict[Any, pd.Series] = {}
    price_columns = (
        ("open", DataColumn.OPEN.name),
        ("high", DataColumn.HIGH.name),
        ("low", DataColumn.LOW.name),
        ("close", DataColumn.CLOSE.name),
        ("vwap", DataColumn.VWAP.name),
    )
    optional_price_columns = (
        ("settlement", DataColumn.SETTLEMENT_PRICE.name),
        ("pre_settlement", DataColumn.PRE_SETTLEMENT_PRICE.name),
        ("upper_limit", DataColumn.UPPER_LIMIT_PRICE.name),
        ("lower_limit", DataColumn.LOWER_LIMIT_PRICE.name),
    )
    price_series_by_basis: dict[str, dict[Any, pd.Series]] = {
        basis: {} for basis, _column in price_columns
    }
    volume_series_by_product: dict[Any, pd.Series] = {}
    missing_products: list[str] = []
    store = market_data_store_for(state)
    term_structure_contracts = _term_structure_concrete_contracts(state, ctx)

    def outside_window(product: Any) -> bool:
        # Same reasoning as _check_market_data_coverage.outside_window: a
        # term-structure concrete contract's presence in the load plan already
        # means the term structure table says it should have data in this run
        # window, so an empty query result here is a real data gap, not a
        # legitimate "not listed yet / already delisted" exclusion.
        if product in term_structure_contracts:
            return False
        return _product_outside_run_window(product, start_dt, end_dt)

    for plan_item in store.load_plan:
        product, freq, source = _unpack_market_data_load_plan_item(plan_item)
        try:
            data_view = getattr(product, freq.name)
            df = data_view.get_and_adjust_cols(
                [column for _basis, column in price_columns] + [DataColumn.VOLUME.name],
                copy=False,
                start_dt=start_dt,
                end_dt=end_dt,
                warmup_window=warmup_window,
                source=source,
            )
        except (ValueError, KeyError):
            try:
                data_view = getattr(product, freq.name)
                df = data_view.get_and_adjust_cols(
                    [column for _basis, column in price_columns],
                    copy=False,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    warmup_window=warmup_window,
                    source=source,
                )
            except (ValueError, KeyError):
                if outside_window(product):
                    excluded: list[Any] = list(store.excluded_out_of_range)
                    excluded.append(product)
                    store.excluded_out_of_range = tuple(_dedupe_products(excluded))
                else:
                    missing_products.append(str(getattr(product, "name", product)))
                continue
        if df.empty or DataColumn.CLOSE.name not in df.columns:
            if outside_window(product):
                excluded = list(store.excluded_out_of_range)
                excluded.append(product)
                store.excluded_out_of_range = tuple(_dedupe_products(excluded))
            else:
                missing_products.append(str(getattr(product, "name", product)))
            continue
        series_by_product[product] = df[DataColumn.CLOSE.name]
        for basis, column in price_columns:
            if column in df.columns:
                price_series_by_basis[basis][product] = df[column]
        for basis, column in optional_price_columns:
            if column in df.columns:
                price_series_by_basis.setdefault(basis, {})[product] = df[column]
            else:
                _load_optional_price_column(data_view, column, basis, product, price_series_by_basis, start_dt, end_dt, warmup_window, source)
        if DataColumn.VOLUME.name in df.columns:
            volume_series_by_product[product] = df[DataColumn.VOLUME.name]
    if missing_products:
        _raise_missing_market_data(missing_products, start_dt, end_dt)
    raw_prices = pd.DataFrame(series_by_product) if series_by_product else pd.DataFrame()
    volume = pd.DataFrame(volume_series_by_product) if volume_series_by_product else None
    price_tables = {
        basis: pd.DataFrame(values)
        for basis, values in price_series_by_basis.items()
        if values
    }
    if "close" not in price_tables:
        price_tables["close"] = raw_prices
    raw = {
        "raw_prices": raw_prices,
        "price_tables": price_tables,
        "settlement_price": price_tables.get("settlement"),
        "historical_field_provider": load_market_rule_field_provider(),
        "historical_field_policy": request.get("policy", "latest_available"),
        "historical_field_names": _required_market_rule_field_names(state),
        "included_products": tuple(series_by_product.keys()),
        "excluded_out_of_range_products": tuple(store.excluded_out_of_range),
        "volume": volume,
    }
    _publish_raw_market_data(state, ctx, raw)


def _unpack_market_data_load_plan_item(plan_item: Any) -> tuple[Any, Any, Any | None]:
    if isinstance(plan_item, tuple) and len(plan_item) == 3:
        return plan_item
    product, freq = plan_item
    return product, freq, None


def _load_optional_price_column(
    data_view: Any,
    column: str,
    basis: str,
    product: Any,
    price_series_by_basis: dict[str, dict[Any, pd.Series]],
    start_dt: Any,
    end_dt: Any,
    warmup_window: pd.Timedelta | None,
    source: Any,
) -> None:
    try:
        frame = data_view.get_and_adjust_cols(
            [column],
            copy=False,
            start_dt=start_dt,
            end_dt=end_dt,
            warmup_window=warmup_window,
            source=source,
        )
    except (ValueError, KeyError):
        return
    if column in frame.columns:
        price_series_by_basis.setdefault(basis, {})[product] = frame[column]


def _live_market_data_load_warmup_window(state) -> pd.Timedelta | None:
    """Warm-up data span needed by live factor BAR replay.

    This is an I/O superset, not an state-level strategy setting: individual
    strategies still clip BAR events with their own warm-up window later.
    Precomputed factors do not use this path; their warm-up is passed to
    factor.evaluate().
    """
    from tools.testers.backtest.modules.factor import FactorModule
    from tools.testers.backtest.modules.run_window import warmup_window_for_strategy

    windows: list[pd.Timedelta] = []
    for strategy in getattr(state, "strategy_configs", {}):
        config = state.config_for(strategy)
        if not config.uses_flow("signal_live"):
            continue
        window = warmup_window_for_strategy(config, config.get(FactorModule.factor))
        if window > pd.Timedelta(0):
            windows.append(window)
    return max(windows) if windows else None


def _build_trading_day_resolver(state, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    provider = ctx.get(MarketDataModule.historical_field_provider)
    store = market_data_store_for(state)
    if provider is None:
        ctx.set(MarketDataModule.trading_day_resolver, None)
        store.trading_day_resolver = None
        return
    if raw_prices is None or raw_prices.empty:
        ctx.set(MarketDataModule.trading_day_resolver, None)
        store.trading_day_resolver = None
        return
    resolver = build_trading_day_resolver_from_market_data(raw_prices)
    ctx.set(MarketDataModule.trading_day_resolver, resolver)
    store.trading_day_resolver = resolver


def _load_historical_fields(state, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    resolver = ctx.get(MarketDataModule.trading_day_resolver)
    store = market_data_store_for(state)
    raw_policy = _market_data_request(state).get("policy", store.historical_field_policy)
    policy = _historical_field_policy_for_engine(state, raw_policy)
    ctx.set(MarketDataModule.historical_field_policy, policy)
    store.historical_field_policy = policy
    field_names = tuple(store.historical_field_names or _MARKET_RULE_FIELD_NAMES)
    store.historical_field_names = field_names
    if raw_prices is None or raw_prices.empty or resolver is None:
        store.historical_field_frames = None
        return
    store.historical_field_frames = historical_field_frames_for_market_data(
        list(raw_prices.columns),
        signal_timestamps(raw_prices),
        provider=cast(FieldHistoryProvider, store.historical_field_provider),
        trading_day_resolver=resolver,
        field_names=field_names,
        policy=policy,
    )


def _publish_raw_market_data(state, ctx, raw: dict[str, Any]) -> None:
    ctx.set(MarketDataModule.raw_prices, raw.get("raw_prices"))
    ctx.set(MarketDataModule.lot_sizes, raw.get("lot_sizes", {}))
    ctx.set(MarketDataModule.margin_ratio, raw.get("margin_ratio", {}))
    ctx.set(MarketDataModule.settlement_price, raw.get("settlement_price"))
    ctx.set(MarketDataModule.volume, raw.get("volume"))
    ctx.set(MarketDataModule.historical_field_provider, raw.get("historical_field_provider"))
    store = market_data_store_for(state)
    store.publish_raw(raw)
    _record_excluded_out_of_range_products(state, store.excluded_out_of_range)
    # volume_table is not ffill'd -- a gap means zero
                                                # traded volume, not "carry the last
                                                # observed value forward"


def _record_excluded_out_of_range_products(state, products: tuple[Any, ...]) -> None:
    if not products:
        return
    seen_sets = market_data_store_for(state).runtime_info_excluded_product_sets
    product_tuple = tuple(products)
    if product_tuple in seen_sets:
        return
    seen_sets.append(product_tuple)
    displays = [_product_display(product) for product in products]
    sample = "、".join(_product_display_text(item) for item in displays[:12])
    if len(displays) > 12:
        sample += f" 等 {len(displays)} 个"
    row = {
        "type": "产品路径",
        "status": "已移除",
        "level": "warning",
        "code": "market_data_out_of_range_products_removed",
        "message": f"产品路径已移除 {len(displays)} 个超出行情覆盖期的产品",
        "detail": (
            "以下产品不在当前回测时间范围的可交易覆盖期内，进入回测前已从产品路径候选池移除："
            f"{sample}"
        ),
        "details": {
            "product_displays": displays,
            "product_names": [item["name"] for item in displays],
        },
    }
    runtime_rows = getattr(state, "runtime_info_rows", None)
    if isinstance(runtime_rows, list):
        runtime_rows.append(row)
    sink = getattr(state, "runtime_info_sink", None)
    emit = getattr(sink, "emit_runtime_info", None)
    if callable(emit):
        emit(row["message"], level=row["level"], code=row["code"], details=row["details"], row=row)


def _dedupe_products(products: list[Any]) -> list[Any]:
    result: list[Any] = []
    for product in products:
        if product not in result:
            result.append(product)
    return result


def _dedupe_names(names: list[str]) -> list[str]:
    result: list[str] = []
    for name in names:
        if name not in result:
            result.append(name)
    return result


def _product_display(product: Any) -> dict[str, str]:
    name = str(getattr(product, "name", product) or "")
    desc = ""
    for attr in ("desc", "description", "display_name", "label"):
        value = getattr(product, attr, None)
        if value:
            desc = str(value)
            break
    return {"name": name, "desc": desc}


def _product_display_text(item: dict[str, str]) -> str:
    name = str(item.get("name") or "")
    desc = str(item.get("desc") or "")
    return f"{name}({desc})" if desc and desc != name else name


def _raise_missing_market_data(missing_products: list[str], start_dt: Any, end_dt: Any) -> None:
    sample = ", ".join(sorted(set(missing_products))[:20])
    suffix = "" if len(set(missing_products)) <= 20 else f" 等 {len(set(missing_products))} 个"
    start_text = getattr(start_dt, "ts", start_dt)
    end_text = getattr(end_dt, "ts", end_dt)
    raise ValueError(
        "回测产品池存在本地行情缺口，不能静默跳过或按 0 估值："
        f"{sample}{suffix}；窗口={start_text} 到 {end_text}。"
        "请检查产品路径是否包含已退市/无分钟数据品种，或先补齐对应行情数据。"
    )


def _product_outside_run_window(product: Any, start_dt: Any, end_dt: Any) -> bool:
    if not _supports_local_cnfutures_coverage(product):
        return False
    coverage = _product_data_coverage(product) or _local_cnfutures_lifecycle_coverage(product)
    if coverage is None:
        return False
    data_start, data_end = coverage
    start_key = _datetime_sort_key(getattr(start_dt, "sort_key", lambda: None)())
    end_key = _datetime_sort_key(getattr(end_dt, "sort_key", lambda: None)())
    if start_key is not None and data_end is not None and data_end < start_key:
        return True
    if end_key is not None and data_start is not None and data_start > end_key:
        return True
    return False


def _local_cnfutures_lifecycle_coverage(product: Any) -> tuple[pd.Timestamp | None, pd.Timestamp | None] | None:
    """Catalog lifecycle fallback for LocalCNFutures products without price files.

    Versioned legacy products such as FU.SHF@1 can have no separate local
    minute/day parquet but still have a catalog standard end date.  In auto
    mode they should be removed before the price matrix is built when the
    whole run window is after that end date.
    """
    try:
        from sources.LocalCNFutures.CNFutures import (
            _data,
            code_col_name,
            enddate_col_name,
            exchange_code_col_name,
            exchange_map,
            version_col_name,
        )
    except Exception:
        return None

    code = str(getattr(product, "code", "") or "").strip().upper()
    version = getattr(product, "version", None)
    if version in (None, ""):
        return None
    alias = str(getattr(product, "alias", getattr(product, "name", "")) or "")
    exchange_short = alias.split(".", 1)[1].upper() if "." in alias else ""
    exchange_full = {v.upper(): k.upper() for k, v in exchange_map.items()}.get(
        exchange_short,
        exchange_short,
    )
    if not code:
        return None

    frame = cast(pd.DataFrame, _data)
    code_series = cast(pd.Series, frame[code_col_name])
    rows = frame.loc[code_series.astype(str).str.upper() == code]
    if exchange_full:
        exchange_series = cast(pd.Series, rows[exchange_code_col_name])
        rows = rows.loc[exchange_series.astype(str).str.upper() == exchange_full]
    version_series = cast(pd.Series, rows[version_col_name])
    rows = rows.loc[version_series.astype(str) == str(version)]
    if rows.empty:
        return None
    end_values = [
        parsed
        for value in rows[enddate_col_name].tolist()
        if value is not None and not pd.isna(value) and str(value).strip()
        for parsed in (_datetime_sort_key(value),)
        if parsed is not None
    ]
    if not end_values:
        return None
    return None, max(end_values)


def _supports_local_cnfutures_coverage(product: Any) -> bool:
    try:
        from sources.LocalCNFutures.CNFutures import CNFutures, CNFuturesContract
        return isinstance(product, (CNFutures, CNFuturesContract))
    except Exception:
        return False


def _product_data_coverage(product: Any) -> tuple[pd.Timestamp | None, pd.Timestamp | None] | None:
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    try:
        freqs = list(product.list_available_freqs())
    except Exception:
        return None
    for freq in freqs:
        try:
            data = getattr(product, freq.name).get_data(copy=False)
        except Exception:
            continue
        if data is None or data.empty:
            continue
        try:
            index = DataIndex(data.index).signal_index
        except Exception:
            try:
                index = DataIndex.event_timestamps_from_index(data.index)
            except Exception:
                index = pd.DatetimeIndex(data.index)
        if len(index) == 0:
            continue
        start_key = _datetime_sort_key(index.min())
        end_key = _datetime_sort_key(index.max())
        if start_key is not None:
            starts.append(start_key)
        if end_key is not None:
            ends.append(end_key)
    if not starts or not ends:
        return None
    return min(starts), max(ends)


def _datetime_sort_key(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    if isinstance(value, tuple) and value:
        value = value[-1]
    try:
        ts = pd.Timestamp(cast(Any, value))
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return cast(pd.Timestamp, ts)


def _historical_field_policy_for_engine(state, raw_policy: object | None) -> str:
    mode = "auto"
    configs = getattr(state, "strategy_configs", None)
    if configs:
        mode = engine_mode_for(next(iter(configs.values())))
    if mode == "exact":
        return str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value)
    fee_ref = FieldRef("fee_mode", owner="FeeModule")
    for config in getattr(state, "strategy_configs", {}).values():
        if str(config.get(fee_ref, "") or "") == "exact":
            return str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value)
    if mode in {"auto", "custom"}:
        return str(raw_policy or HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value)
    return str(raw_policy or HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value)


def _required_market_rule_field_names(state) -> tuple[str, ...]:
    fields: list[str] = list(_MARKET_RULE_FIELD_NAMES)
    fee_ref = FieldRef("fee_mode", owner="FeeModule")
    margin_ref = FieldRef("margin_mode", owner="MarginModule")
    allocation_ref = FieldRef("allocation_policy", owner="GroupMembershipModule")
    for config in getattr(state, "strategy_configs", {}).values():
        from tools.testers.backtest.modules.fee import _resolve_fee_mode
        from tools.testers.backtest.modules.trading_rule import _effective_accounting_mode

        fee_mode = _resolve_fee_mode(config)
        if fee_mode not in {"zero", "none"}:
            fields.extend(TRANSACTION_FEE_FIELD_NAMES)
        if fee_mode == "exact" or engine_mode_for(config) == "exact":
            fields.append("CostBasisMethod")
        accounting_mode = _effective_accounting_mode(config)
        if accounting_mode == "Auto":
            fields.extend(TRANSACTION_FEE_FIELD_NAMES)
            fields.extend(("CostBasisMethod", "SettlementPrice", "PreSettlementPrice", "LastSettlementPrice", "MoneyCalculationPolicy"))
        if engine_mode_for(config) == "exact":
            fields.extend(("CostBasisMethod", "SettlementPrice", "PreSettlementPrice", "LastSettlementPrice", "MoneyCalculationPolicy"))
        if accounting_mode == "Custom" and str(config.get(FieldRef("cost_basis_method", owner="TradingRuleModule"), "") or "") == "DailyMarkToMarket":
            fields.extend(("SettlementPrice", "PreSettlementPrice", "LastSettlementPrice", "MoneyCalculationPolicy"))
        margin_mode = str(config.get(margin_ref, "auto") or "auto")
        allocation = str(config.get(allocation_ref, "") or "")
        if margin_mode not in {"none", "zero"} or allocation == "equal_margin":
            fields.extend(_MARGIN_FIELD_NAMES)
    return tuple(dict.fromkeys(fields))


def _causal_valuation(state, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    market_data_store_for(state).current_prices_table = raw_prices.ffill()


def _set_current_market_snapshot(state, ctx) -> None:
    snapshot = current_market_snapshot_at(state, ctx.timestamp)
    close_prices = snapshot.get("close", {})
    ctx.set(MarketDataModule.current_market_snapshot, snapshot)
    ctx.set(MarketDataModule.current_prices, close_prices)
    ctx.set(MarketDataModule.current_tradable_status, tradable_status_from_snapshot(snapshot))
    ctx.set(MarketDataModule.current_order_constraints, order_constraints_from_snapshot(snapshot))


def _set_current_historical_fields(state, ctx) -> None:
    base_fields = current_historical_fields_at(state, ctx.timestamp)
    ctx.set(MarketDataModule.current_historical_fields, base_fields)
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        fields = _historical_fields_for_strategy(base_fields, config, ctx.timestamp)
        if fields is base_fields:
            # No customization applies to this strategy -- every consumer
            # reads via ctx.get_for(ref, strategy, ctx.get(ref, {})), so
            # simply not writing a per-strategy entry makes it transparently
            # reference the same shared base_fields already set above,
            # instead of writing back an identical copy under a redundant key.
            continue
        ctx.set_for(MarketDataModule.current_historical_fields, strategy, fields)


def _historical_fields_for_strategy(
    base_fields: dict[Any, dict[str, object]],
    strategy_config,
    timestamp: pd.Timestamp,
) -> dict[Any, dict[str, object]]:
    if engine_mode_for(strategy_config) != "custom":
        return base_fields
    if not _custom_historical_fields_enabled(strategy_config):
        return base_fields
    return apply_custom_product_fields(base_fields, strategy_config, timestamp)


def _custom_historical_fields_enabled(strategy_config) -> bool:
    from tools.testers.backtest.modules.fee import _resolve_fee_mode
    from tools.testers.backtest.modules.margin import _resolve_margin_mode
    from tools.testers.backtest.modules.trading_rule import _effective_accounting_mode

    return (
        _resolve_fee_mode(strategy_config) == "custom"
        or _resolve_margin_mode(strategy_config) == "custom"
        or _effective_accounting_mode(strategy_config) == "Custom"
    )


def current_prices_at(state, timestamp: pd.Timestamp) -> dict:
    """Look up the per-product price dict at `timestamp` from the ffill'd
    table on `state` — never indexes past `timestamp` (no-lookahead is
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
    table = current_prices_table_for(state)
    row = row_at(table, timestamp, asof=True)
    prices: dict[Any, float] = {}
    for product in table.columns:
        value = row[product]
        if pd.isna(value):
            continue
        prices[product] = float(cast(Any, value))
    return prices


def current_market_snapshot_at(state, timestamp: pd.Timestamp) -> dict[str, dict[Any, float]]:
    """Return the complete market observation snapshot for an event timestamp.

    ``close`` is the legacy no-lookahead valuation view and is ffilled through
    gaps. Other price bases come from the raw basis tables at/as-of the event
    timestamp. Volume is not ffilled: a missing row means no observed volume
    for that event bar. Settlement/pre-settlement are included when the data
    source exposes them; daily settlement flows are responsible for only using
    them on ledger-notice timestamps registered after a trading day's final bar.
    """
    snapshot: dict[str, dict[Any, float]] = {"close": current_prices_at(state, timestamp)}
    for basis, table in market_price_tables_for(state).items():
        if basis == "close" or not isinstance(table, pd.DataFrame) or table.empty:
            continue
        values = _table_values_at(table, timestamp, asof=True)
        if values:
            snapshot[basis] = values
    volume = current_volume_at(state, timestamp)
    if volume:
        snapshot["volume"] = volume
    return snapshot


def tradable_status_from_snapshot(snapshot: dict[str, dict[Any, float]]) -> dict[Any, bool]:
    return exchange_tradable_status_for_snapshot(snapshot)


def order_constraints_from_snapshot(snapshot: dict[str, dict[Any, float]]) -> dict[Any, OrderTradeConstraint]:
    return exchange_order_constraints_for_snapshot(snapshot)


def is_product_tradable(tradable_status: dict[Any, bool] | None, product: Any, prices: dict[Any, float] | None = None) -> bool:
    if tradable_status is not None:
        return bool(tradable_status.get(product, False))
    if prices is None:
        return True
    return _usable_price(prices.get(product))


def _usable_price(value: object) -> bool:
    try:
        return value is not None and not pd.isna(cast(Any, value)) and float(cast(Any, value)) > 0.0
    except (TypeError, ValueError):
        return False


def _table_values_at(table: pd.DataFrame, timestamp: pd.Timestamp, *, asof: bool) -> dict[Any, float]:
    try:
        row = row_at(table, timestamp, asof=asof)
    except KeyError:
        return {}
    values: dict[Any, float] = {}
    for product in table.columns:
        value = row[product]
        if pd.isna(value):
            continue
        values[product] = float(cast(Any, value))
    return values


def current_volume_at(state, timestamp: pd.Timestamp) -> dict:
    """Look up this bar's traded volume per product — no ffill (a gap means
    zero volume traded, not "carry the last observed volume forward")."""
    table = volume_table_for(state)
    if table is None:
        return {}
    return _table_values_at(table, timestamp, asof=False)


def current_historical_fields_at(state, timestamp: pd.Timestamp) -> dict[Any, dict[str, object]]:
    """按事件时间查当前历史字段。

    MarketDataModule 只消费公共 FieldHistoryProvider，不关心字段来自 Guosen、
    OpenCTP 还是未来别的数据源。严格真实数据模式下，缺产品/缺交易日/缺字段会
    由 provider 直接抛出 MissingHistoricalField 或 MissingTradingDay。
    """
    store = market_data_store_for(state)
    provider = cast(FieldHistoryProvider | None, store.historical_field_provider)
    if provider is None:
        return {}
    resolver = cast(TradingDayResolver | None, store.trading_day_resolver)
    if resolver is None:
        from tools.data.field_history import MissingTradingDay
        raise MissingTradingDay("trading_day_resolver is required for MarketDataModule historical fields")
    policy = str(
        getattr(
            store,
            "historical_field_policy",
            str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
        )
    )
    field_names = cast(tuple[object, ...], tuple(store.historical_field_names))
    if not field_names:
        return {}
    table = current_prices_table_for(state)
    instruments = list(table.columns) if table is not None else []
    frames = store.historical_field_frames
    if isinstance(frames, dict):
        frame_result = _historical_fields_at_from_frames(frames, instruments, timestamp)
        return _apply_exchange_rule_defaults(frame_result, instruments, field_names)
    resolved_result: dict[Any, dict[str, object]] = {}
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
        resolved_result[instrument] = values
    return _apply_exchange_rule_defaults(resolved_result, instruments, field_names)


def historical_field_frames_for_market_data(
    products: list[Any],
    index: pd.Index,
    *,
    provider: FieldHistoryProvider,
    trading_day_resolver: TradingDayResolver,
    field_names: tuple[object, ...],
    policy: str,
) -> dict[str, pd.DataFrame]:
    runtime_provider = _runtime_field_history_provider()
    return historical_fields_frame_for_products(
        products,
        index,
        provider=runtime_provider,
        trading_day_resolver=trading_day_resolver,
        field_names=field_names,
        fallback=policy,
    )


@lru_cache(maxsize=1)
def _runtime_field_history_provider() -> FieldHistoryProvider:
    from sources.FieldHistory.views.Unified import load_unified_provider

    return load_unified_provider()


def _historical_fields_at_from_frames(
    frames: dict[str, pd.DataFrame],
    instruments: list[Any],
    timestamp: pd.Timestamp,
) -> dict[Any, dict[str, object]]:
    result: dict[Any, dict[str, object]] = {instrument: {} for instrument in instruments}
    for field_name, frame in frames.items():
        # FieldHistoryProvider stores its frames tz-naive (it normalises
        # every lookup key via _normalise_timestamp_key); event timestamps
        # here are tz-aware, so align via DataIndex before indexing. These
        # fields are effective-time states, so an ORDER event shifted by a
        # causal epsilon should read the latest rule row at or before it.
        lookup_timestamp = DataIndex(frame.index).tz_align(timestamp)
        row_pos = _historical_field_frame_asof_position(frame.index, lookup_timestamp)
        if row_pos is None:
            continue
        row = frame.iloc[row_pos]
        for instrument in instruments:
            column = _historical_field_frame_column_for(frame, instrument)
            if column is not None:
                result[instrument][str(field_name)] = row[str(column)]
    return result


def _apply_exchange_rule_defaults(
    result: dict[Any, dict[str, object]],
    instruments: list[Any],
    field_names: tuple[object, ...],
) -> dict[Any, dict[str, object]]:
    for instrument in instruments:
        values = result.setdefault(instrument, {})
        defaults = exchange_rule_defaults_for_product(instrument, field_names)
        for field_name, value in defaults.items():
            values.setdefault(str(field_name), value)
    return result


def _historical_field_frame_asof_position(index: pd.Index, timestamp: pd.Timestamp) -> int | None:
    if len(index) == 0:
        return None
    index_ns = cast(Any, pd.DatetimeIndex(pd.DatetimeIndex(index).astype("datetime64[ns]"))).asi8
    pos = int(index_ns.searchsorted(timestamp.value, side="right") - 1)
    if pos < 0:
        return None
    return pos


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


def historical_fields_for_product(
    historical_fields: dict[Any, dict[str, object]] | None,
    product: Any,
) -> dict[str, object]:
    """Return current historical fields for a runtime Product object.

    FieldHistory/database identifiers are normalised back to Product keys at
    the MarketDataModule boundary. Downstream modules should not guess string
    aliases such as name/symbol/code.
    """
    if not historical_fields:
        return {}
    values = historical_fields.get(product)
    if isinstance(values, dict):
        return values
    product_keys = _historical_field_product_keys(product)
    for instrument, values in historical_fields.items():
        if not isinstance(values, dict):
            continue
        if product_keys & _historical_field_product_keys(instrument):
            return values
    return {}


def _historical_field_product_keys(product: Any) -> set[str]:
    keys: set[str] = set()
    if product is None:
        return keys
    for value in (
        str(product),
        getattr(product, "name", None),
        getattr(product, "alias", None),
        getattr(product, "symbol", None),
        getattr(product, "code", None),
    ):
        if value is not None and str(value).strip():
            keys.add(str(value).strip())
    return keys


def contract_multiplier_from_fields(
    historical_fields: dict[Any, dict[str, object]] | None,
    product: Any,
    *,
    default: float = 1.0,
) -> float:
    fields = historical_fields_for_product(historical_fields, product)
    value = fields.get("VolumeMultiple", default)
    if value in (None, ""):
        return default
    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return default
    return default if number != number else number


def contract_notional(
    price: float,
    quantity: float,
    historical_fields: dict[Any, dict[str, object]] | None,
    product: Any,
) -> float:
    return float(quantity) * float(price) * contract_multiplier_from_fields(historical_fields, product)
