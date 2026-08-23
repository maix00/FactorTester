"""MarketDataModule — owns market data observations and the forward-filled
market price view derived from them.

Market data can arrive either as an explicit `raw_market_data` payload (legacy
test/adaptor path) or through this module's resolved load plan. The load plan
is strategy-scoped up to the coverage stage and becomes a concrete
product/frequency/source list before raw tables are read. The
``causal_valuation`` flow then turns the already-loaded, possibly-gappy
raw_prices frame into a forward-filled, no-lookahead market price lookup.

The ffill'd table itself is stored in `state.market_data_store` (not `ctx`)
because it's computed once in PRE_REPLAY but needs to survive into every later
PER_EVENT dispatch — `ctx` is scoped to a single dispatch batch and is
discarded right after, while BacktestRunState-owned stores live for the whole run.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, ClassVar, cast

import numpy as np
import pandas as pd

from tools.data.types import DataColumn, DataTime
from tools.data.types.time_freq import DataFreq
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, FlowBinding, FlowDefinition, Phase
from tools.testers.backtest.modules.custom_product import CustomProductModule, apply_custom_product_fields
from tools.testers.backtest.modules.engine import EngineModule, engine_mode_for
from tools.testers.backtest.modules.factor import FactorModule, factors_for_config
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.run_window import RunWindowModule
from tools.testers.backtest.modules.term_structure import TermStructureExpandModule
from tools.testers.backtest.modules.time_index_lookup import (
    TableRowLocator,
    row_at,
    row_at_index_key,
    signal_timestamps,
)
from tools.data.types.time_index import DataIndex
from tools.products.AdjustableTermStructure import TERM_RANK_COL
from tools.data.field_history import (
    HistoricalFieldLookupError,
    HistoricalFieldFallbackPolicy,
    MissingHistoricalField,
    FieldHistoryProvider,
    TradingDayResolver,
    TimestampTradingDayResolver,
    TRANSACTION_FEE_FIELD_NAMES,
    TRANSACTION_FEE_SOURCE_EXCHANGE,
    _normalise_transaction_fee_source,
    build_trading_day_resolver_from_market_data,
    historical_fields_frame_for_products,
    load_market_rule_field_provider,
    resolve_historical_fields_for_product,
)
from tools.data.providers.DataProviderProductTS import DataProviderProductTS
from tools.data.source_catalog import data_source_declaration, data_source_declarations
from tools.traderules import (
    OrderTradeConstraint,
    exchange_order_constraints_for_snapshot,
    exchange_rule_defaults_for_product,
    exchange_tradable_status_for_snapshot,
)


_MARKET_SNAPSHOT_CACHE_LIMIT = 512
_TABLE_VALUES_CACHE_LIMIT = 2048
_HISTORICAL_FIELDS_CACHE_LIMIT = 512
_EXCHANGE_RULE_DEFAULTS_CACHE_LIMIT = 4096


def _historical_data_source_options() -> tuple[tuple[str, str], ...]:
    """Read selectable historical bundles from source-owned declarations."""
    from sources.registry import load_all_sources

    load_all_sources()
    return tuple(
        (source.key, source.label)
        for source in data_source_declarations()
        if source.execution_providers()
    )


class _BoundedLRUCache(OrderedDict):
    """Small LRU for chronological replay data that must not grow by year."""

    def __init__(self, max_entries: int) -> None:
        super().__init__()
        self.max_entries = max(1, int(max_entries))

    def get(self, key, default=None):
        try:
            value = super().pop(key)
        except KeyError:
            return default
        super().__setitem__(key, value)
        return value

    def __setitem__(self, key, value) -> None:
        if key in self:
            super().__delitem__(key)
        super().__setitem__(key, value)
        while len(self) > self.max_entries:
            self.popitem(last=False)


@dataclass
class MarketDataStore:
    _guarded_write_fields: ClassVar[frozenset[str]] = frozenset({
        "raw_prices_table",
        "current_prices_table",
        "market_price_tables",
        "factor_field_tables",
        "volume_table",
        "included_products",
        "historical_field_provider",
        "historical_field_policy",
        "historical_field_names",
        "historical_field_frames",
        "dmtm_event_table",
    })

    raw_input: dict[str, Any] = field(default_factory=dict)
    request: dict[str, Any] = field(default_factory=dict)
    load_plan: list[Any] = field(default_factory=list)
    required_data_source_by_strategy: dict[Any, tuple[str, ...]] = field(default_factory=dict)
    required_frequency_by_strategy: dict[Any, DataFreq] = field(default_factory=dict)
    required_factor_columns_by_strategy: dict[Any, tuple[str, ...]] = field(default_factory=dict)
    daily_signal_close_time: str | None = None
    excluded_out_of_range: tuple[Any, ...] = ()
    series_by_product: dict[Any, Any] = field(default_factory=dict)
    raw_prices_table: Any = None
    current_prices_table: Any = None
    market_price_tables: dict[str, Any] = field(default_factory=dict)
    factor_field_tables: dict[str, Any] = field(default_factory=dict)
    volume_table: Any = None
    dmtm_event_table: Any = None
    included_products: frozenset[Any] | None = None
    historical_field_provider: Any = None
    trading_day_resolver: Any = None
    historical_field_policy: str | None = None
    historical_field_names: tuple[Any, ...] = ()
    historical_field_frames: Any = None
    market_snapshot_cache: dict[Any, dict[str, dict[Any, float]]] = field(
        default_factory=lambda: _BoundedLRUCache(_MARKET_SNAPSHOT_CACHE_LIMIT)
    )
    table_values_cache: dict[Any, dict[Any, float]] = field(
        default_factory=lambda: _BoundedLRUCache(_TABLE_VALUES_CACHE_LIMIT)
    )
    table_event_index_cache: dict[int, tuple[pd.Index, TableRowLocator]] = field(default_factory=dict)
    execution_price_index_cache: dict[tuple[int, int | None], pd.DatetimeIndex] = field(
        default_factory=dict
    )
    execution_price_column_position_cache: dict[int, dict[int, tuple[Any, int | None]]] = field(
        default_factory=dict
    )
    execution_frequency_cache: dict[int, tuple[pd.DataFrame, Any]] = field(
        default_factory=dict
    )
    historical_fields_cache: dict[Any, dict[Any, dict[str, object]]] = field(
        default_factory=lambda: _BoundedLRUCache(_HISTORICAL_FIELDS_CACHE_LIMIT)
    )
    # In the event-driven field-state path, historical fields change only when
    # a FIELD_CHANGE event is applied.  LEDGER timestamps can still be unique
    # per product/order, so caching solely by timestamp repeats the same
    # product walk for every event.  Keep one resolved mapping for the current
    # field-state generation and invalidate it when a field-change event is
    # actually processed.
    field_state_generation: int = 0
    field_state_resolved_cache: tuple[int, tuple[object, ...], Any, dict[Any, dict[str, object]]] | None = None
    # Exchange clearing defaults are product/rule inputs, not timestamp-varying
    # observations.  Keep one run-scoped bounded cache so every historical-field
    # snapshot does not rebuild the same defaults mapping for every product.
    exchange_rule_defaults_cache: dict[
        tuple[int, tuple[str, ...]], tuple[Any, dict[str, object]]
    ] = field(
        default_factory=lambda: _BoundedLRUCache(_EXCHANGE_RULE_DEFAULTS_CACHE_LIMIT)
    )
    historical_field_frame_column_cache: dict[tuple[str, tuple[str, ...]], object | None] = field(default_factory=dict)
    historical_field_frame_column_map_cache: dict[Any, list[tuple[Any, int]]] = field(default_factory=dict)
    historical_field_frame_row_cache: dict[Any, dict[Any, dict[str, object]]] = field(default_factory=dict)
    historical_field_frame_index_cache: dict[int, tuple[pd.Index, Any]] = field(default_factory=dict)
    historical_field_frame_values_cache: dict[int, tuple[pd.DataFrame, Any]] = field(default_factory=dict)
    historical_field_latest_available_warning_keys: set[tuple[str, str, Any]] = field(default_factory=set)
    runtime_info_excluded_product_sets: list[tuple[Any, ...]] = field(default_factory=list)
    field_state_store: dict[str, dict[str, object]] = field(default_factory=dict)
    _guarded_writes_enabled: bool = field(default=False, init=False, repr=False)
    _guarded_write_depth: int = field(default=0, init=False, repr=False)
    """Current snapshot of market-rule field values, keyed by product_name then field_name.
    Populated by initialize_field_state (PRE_REPLAY) and updated by handle_field_changes
    (PER_EVENT/FIELD_CHANGE). Replaces the old per-timestamp historical_field_frames DataFrames.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        if (
            name in self._guarded_write_fields
            and getattr(self, "_guarded_writes_enabled", False)
            and getattr(self, "_guarded_write_depth", 0) <= 0
        ):
            raise RuntimeError(
                f"MarketDataStore.{name} is guarded during step/audit runs; "
                "write it through a named publish_* method and mirror the value "
                "through a declared FlowContext output when it is flow-visible."
            )
        super().__setattr__(name, value)

    @contextmanager
    def _unguarded_write(self):
        self._guarded_write_depth += 1
        try:
            yield
        finally:
            self._guarded_write_depth -= 1

    def set_guarded_writes_enabled(self, enabled: bool) -> None:
        self._guarded_writes_enabled = bool(enabled)

    def publish_raw(self, raw: dict[str, Any]) -> None:
        with self._unguarded_write():
            self.raw_prices_table = raw.get("raw_prices")
            self.market_price_tables = raw.get("price_tables") or {"close": raw.get("raw_prices")}
            self.factor_field_tables = raw.get("factor_field_tables") or {}
            self.historical_field_provider = raw.get("historical_field_provider")
            self.trading_day_resolver = raw.get("trading_day_resolver")
            included_products = raw.get("included_products")
            self.included_products = frozenset(included_products) if included_products is not None else None
            self.excluded_out_of_range = tuple(raw.get("excluded_out_of_range_products", ()))
            self.historical_field_names = tuple(raw.get("historical_field_names", ()))
            self.volume_table = raw.get("volume")
            self.dmtm_event_table = raw.get("dmtm_event_table")
        self.market_snapshot_cache.clear()
        self.table_values_cache.clear()
        self.table_event_index_cache.clear()
        self.execution_price_index_cache.clear()
        self.execution_price_column_position_cache.clear()
        self.execution_frequency_cache.clear()
        self.historical_fields_cache.clear()
        self.field_state_generation += 1
        self.field_state_resolved_cache = None
        self.exchange_rule_defaults_cache.clear()
        self.historical_field_frame_column_cache.clear()
        self.historical_field_frame_column_map_cache.clear()
        self.historical_field_frame_row_cache.clear()
        self.historical_field_frame_index_cache.clear()
        self.historical_field_frame_values_cache.clear()
        self.historical_field_latest_available_warning_keys.clear()
        self.prepare_execution_price_indexes()

    def publish_coverage_seed(self, raw: dict[str, Any]) -> None:
        with self._unguarded_write():
            raw_prices = raw.get("raw_prices")
            self.series_by_product = {
                product: raw_prices[product]
                for product in getattr(raw_prices, "columns", [])
            }
            self.market_price_tables = raw.get("price_tables") or {"close": raw_prices}
            self.excluded_out_of_range = tuple(raw.get("excluded_out_of_range_products", ()))
            self.dmtm_event_table = raw.get("dmtm_event_table")
        self.execution_price_index_cache.clear()
        self.execution_price_column_position_cache.clear()
        self.execution_frequency_cache.clear()
        self.field_state_generation += 1
        self.field_state_resolved_cache = None
        self.exchange_rule_defaults_cache.clear()

    def publish_historical_field_policy(self, policy: str) -> None:
        with self._unguarded_write():
            self.historical_field_policy = policy

    def publish_causal_valuation(self, current_prices_table: Any) -> None:
        with self._unguarded_write():
            self.current_prices_table = current_prices_table
        self.market_snapshot_cache.clear()
        self.table_values_cache.clear()
        self.table_event_index_cache.clear()
        self.execution_price_index_cache.clear()
        self.execution_price_column_position_cache.clear()
        self.execution_frequency_cache.clear()

    def prepare_execution_price_indexes(self) -> None:
        """Build immutable per-product execution axes for loaded price tables."""
        for table in self.market_price_tables.values():
            if not isinstance(table, pd.DataFrame) or table.empty:
                continue
            event_index = signal_timestamps(table)
            self.execution_price_index_cache[(id(table), None)] = event_index
            column_positions: dict[int, tuple[Any, int | None]] = {}
            for product in table.columns:
                location = table.columns.get_loc(product)
                column_positions[id(product)] = (
                    product,
                    int(location) if isinstance(location, (int, np.integer)) else None,
                )
            self.execution_price_column_position_cache[id(table)] = column_positions
            valid = table.notna().to_numpy(dtype=bool, copy=False)
            for position in range(len(table.columns)):
                self.execution_price_index_cache[(id(table), position)] = event_index[
                    valid[:, position]
                ]

    def execution_frequency_for(self, table: pd.DataFrame) -> Any:
        """Resolve a table frequency once for execution visibility policies."""

        key = id(table)
        cached = self.execution_frequency_cache.get(key)
        if cached is not None and cached[0] is table:
            return cached[1]
        frequency = DataIndex(table.index).freq
        self.execution_frequency_cache[key] = (table, frequency)
        return frequency

    def execution_price_index(
        self,
        table: pd.DataFrame,
        product: Any | None = None,
    ) -> pd.DatetimeIndex:
        position: int | None = None
        if product is not None:
            cached_column = self.execution_price_column_position_cache.get(id(table), {}).get(id(product))
            if cached_column is not None and cached_column[0] is product:
                position = cached_column[1]
                if position is None:
                    raise ValueError(f"execution price table contains duplicate product column {product!r}")
            elif product in table.columns:
                location = table.columns.get_loc(product)
                if not isinstance(location, (int, np.integer)):
                    raise ValueError(f"execution price table contains duplicate product column {product!r}")
                position = int(location)
        key = (id(table), position)
        cached = self.execution_price_index_cache.get(key)
        if cached is not None:
            return cached
        event_index = signal_timestamps(table)
        if position is not None:
            event_index = event_index[table.iloc[:, position].notna().to_numpy()]
        self.execution_price_index_cache[key] = event_index
        return event_index


class MarketDataModule(ExecutableModule):
    key: ClassVar[str] = "market_data"
    label: ClassVar[str] = "市场数据"

    raw_prices: ClassVar[FieldRef[Any]] = FieldRef("raw_prices")          # close pd.DataFrame, index=ts, columns=Product, may have NaN gaps
    price_tables: ClassVar[FieldRef[Any]] = FieldRef("price_tables")      # dict[basis, pd.DataFrame] for open/high/low/close/vwap/settlement/etc.
    lot_sizes: ClassVar[FieldRef[Any]] = FieldRef("lot_sizes")            # dict[Product, float]
    margin_ratio: ClassVar[FieldRef[Any]] = FieldRef("margin_ratio")      # dict[Product, float]
    settlement_price: ClassVar[FieldRef[Any]] = FieldRef("settlement_price")  # pd.DataFrame, index=ts, columns=Product
    volume: ClassVar[FieldRef[Any]] = FieldRef("volume")                  # dict[Product, float], this bar's traded volume
    historical_field_provider: ClassVar[FieldRef[Any]] = FieldRef("historical_field_provider")
    trading_day_resolver: ClassVar[FieldRef[Any]] = FieldRef("trading_day_resolver")
    historical_field_policy: ClassVar[FieldRef[str]] = FieldRef("historical_field_policy")
    field_state_baseline: ClassVar[FieldRef[Any]] = FieldRef("field_state_baseline")
    field_change_events: ClassVar[FieldRef[Any]] = FieldRef("field_change_events")
    causal_valuation_table: ClassVar[FieldRef[Any]] = FieldRef("causal_valuation_table")
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
    required_data_source: ClassVar[FieldRef[Any]] = FieldRef("required_data_source")
    required_frequency: ClassVar[FieldRef[DataFreq]] = FieldRef("required_frequency")
    required_factor_columns: ClassVar[FieldRef[Any]] = FieldRef("required_factor_columns")
    market_data_load_plan: ClassVar[FieldRef[Any]] = FieldRef("market_data_load_plan")
    excluded_out_of_range_products: ClassVar[FieldRef[Any]] = FieldRef("excluded_out_of_range_products")

    _fee_mode_ref: ClassVar[FieldRef[str]] = FieldRef("fee_mode", owner="FeeModule")
    _fixed_fee_rate_ref: ClassVar[FieldRef[float]] = FieldRef("fixed_fee_rate", owner="FeeModule")
    _margin_mode_ref: ClassVar[FieldRef[str]] = FieldRef("margin_mode", owner="MarginModule")
    _fixed_margin_ratio_ref: ClassVar[FieldRef[float]] = FieldRef("fixed_margin_ratio", owner="MarginModule")
    _accounting_mode_ref: ClassVar[FieldRef[str]] = FieldRef("accounting_mode", owner="TradingRuleModule")
    _cost_basis_method_ref: ClassVar[FieldRef[str]] = FieldRef("cost_basis_method", owner="TradingRuleModule")
    _daily_mark_to_market_enabled_ref: ClassVar[FieldRef[bool]] = FieldRef("daily_mark_to_market_enabled", owner="TradingRuleModule")
    _transaction_fee_source_ref: ClassVar[FieldRef[str]] = FieldRef("transaction_fee_source", owner="FeeModule")
    _warmup_mode_ref: ClassVar[FieldRef[str]] = FieldRef("warmup_mode", owner="FactorSignalModule")
    _warmup_window_ref: ClassVar[FieldRef[Any]] = FieldRef("warmup_window", owner="FactorSignalModule")
    _execution_price_basis_ref: ClassVar[FieldRef[str]] = FieldRef("execution_price_basis", owner="OrderExecutionModule")
    _allocation_policy_ref: ClassVar[FieldRef[str]] = FieldRef("allocation_policy", owner="GroupMembershipModule")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "raw_prices": FieldDefinition(public=False, display_value_kind="market_data_sample"),
        "price_tables": FieldDefinition(public=False, display_value_kind="market_data_sample"),
        "lot_sizes": FieldDefinition(public=False),
        "margin_ratio": FieldDefinition(public=False),
        "settlement_price": FieldDefinition(public=False, display_value_kind="market_data_sample"),
        "volume": FieldDefinition(public=False, display_value_kind="market_data_sample"),
        "historical_field_provider": FieldDefinition(public=False),
        "trading_day_resolver": FieldDefinition(public=False),
        "field_state_baseline": FieldDefinition(public=False, display_value_kind="historical_field_state"),
        "field_change_events": FieldDefinition(public=False),
        "causal_valuation_table": FieldDefinition(public=False, display_value_kind="market_data_sample"),
        "historical_field_policy": FieldDefinition(
            public=True,
            label="历史字段",
            default="auto",
            editor="select",
            tab="engine",
            editable_if={"engine_mode": ("custom",)},
            default_if={
                "engine_mode": {
                    "exact": "auto",
                    "auto": "auto",
                    "custom": "auto",
                },
            },
            chip_template="历史字段: {value}",
            tab_label="执行引擎",
            tab_order=10,
            options=(
                ("auto", "按执行模式自动选择"),
                (str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value), "真实历史数据"),
                (str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value), "缺失历史数据由时间差最近的数据向后填充"),
            ),
        ),
        "current_historical_fields": FieldDefinition(public=False, display_value_kind="market_snapshot"),
        "current_prices": FieldDefinition(public=False, display_value_kind="market_snapshot"),
        "current_market_snapshot": FieldDefinition(public=False, display_value_kind="market_snapshot"),
        "current_tradable_status": FieldDefinition(public=False, display_value_kind="market_snapshot"),
        "current_order_constraints": FieldDefinition(public=False, display_value_kind="market_snapshot"),
        "data_source_mode": FieldDefinition(
            public=True, label="数据源模式", default="auto", editor="select", tab="data_source",
            options=(("auto", "自动选择"), ("list", "指定列表")),
            chip_template="数据源模式: {value}",
            tab_label="数据源",
            tab_order=35,
        ),
        "data_source": FieldDefinition(
            public=True, label="数据源", default=[], editor="custom", tab="data_source",
            visible_if={"data_source_mode": ("list",)},
            options=_historical_data_source_options(),
            chip_template="数据源: {value}",
            tab_label="数据源",
            tab_order=35,
            serialization={"kind": "data_source_selection", "multi": True},
        ),
        "freq_mode": FieldDefinition(
            public=True, label="频率模式", default="auto", editor="select", tab="frequency",
            options=(("auto", "自动推断"), ("fixed", "固定频率")),
            chip_template="频率模式: {value}",
            tab_label="数据频率",
            tab_order=36,
        ),
        "freq_fixed": FieldDefinition(
            public=True, label="固定频率", default="MIN1", editor="text", tab="frequency",
            visible_if={"freq_mode": ("fixed",)},
            chip_template="固定频率: {value}",
            tab_label="数据频率",
            tab_order=36,
        ),
        "required_frequency": FieldDefinition(public=False),
        "required_data_source": FieldDefinition(public=False, display_value_kind="auto_when_empty"),
        "required_factor_columns": FieldDefinition(public=False),
        "market_data_load_plan": FieldDefinition(public=False),
        "excluded_out_of_range_products": FieldDefinition(public=False),
    }

    resolve_market_data_request: ClassVar[Flow] = Flow(
        "resolve_market_data_request",
        inputs=(
            data_source_mode, data_source, freq_mode, freq_fixed,
            FactorModule.factor, ProductSelectionModule.products,
        ),
        outputs=(required_data_source, required_frequency, required_factor_columns),
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
        outputs=(market_data_load_plan, excluded_out_of_range_products),
        phase=Phase.PRE_REPLAY, order=38,
        after=(resolve_market_data_request, TermStructureExpandModule.expand_term_structure),
        description="检查产品覆盖期",
        compute=lambda state, ctx: _check_market_data_coverage(state, ctx),
    )
    load_raw_market_data: ClassVar[Flow] = Flow(
        "load_raw_market_data",
        inputs=(
            EngineModule.engine_mode,
            ProductSelectionModule.products,
            required_data_source,
            required_frequency,
            required_factor_columns,
            FactorModule.factor,
            _warmup_mode_ref,
            _warmup_window_ref,
            _fee_mode_ref,
            _fixed_fee_rate_ref,
            _margin_mode_ref,
            _fixed_margin_ratio_ref,
            _accounting_mode_ref,
            _cost_basis_method_ref,
            _daily_mark_to_market_enabled_ref,
            _transaction_fee_source_ref,
            _allocation_policy_ref,
            TermStructureExpandModule.contract_metadata,
        ),
        outputs=(
            raw_prices, price_tables, lot_sizes, margin_ratio, settlement_price, volume, historical_field_provider,
        ),
        phase=Phase.PRE_REPLAY, order=40, after=(check_market_data_coverage,),
        description="装载行情数据",
        compute=lambda state, ctx: _load_raw_market_data(state, ctx),
    )
    build_trading_day_resolver: ClassVar[Flow] = Flow(
        "build_trading_day_resolver",
        inputs=(raw_prices, historical_field_provider), outputs=(trading_day_resolver,),
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
    initialize_field_state: ClassVar[Flow] = Flow(
        "initialize_field_state",
        inputs=(
            raw_prices,
            trading_day_resolver,
            historical_field_policy,
            EngineModule.engine_mode,
            _fee_mode_ref,
            _fixed_fee_rate_ref,
            _margin_mode_ref,
            _fixed_margin_ratio_ref,
            _accounting_mode_ref,
            _cost_basis_method_ref,
            _daily_mark_to_market_enabled_ref,
            _allocation_policy_ref,
        ),
        outputs=(historical_field_policy, field_state_baseline, field_change_events),
        phase=Phase.PRE_REPLAY, order=44, after=(build_trading_day_resolver,),
        description="初始化字段状态缓存",
        compute=lambda state, ctx: _initialize_field_state(state, ctx),
    )
    handle_field_changes: ClassVar[Flow] = Flow(
        "handle_field_changes",
        inputs=(),
        outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.FIELD_CHANGE, order=0,
        description="处理字段变更事件",
        event_payload_inputs=("field_change",),
        compute=lambda state, ctx: _handle_field_changes(state, ctx),
    )
    causal_valuation: ClassVar[Flow] = Flow(
        "causal_valuation", inputs=(raw_prices,), outputs=(causal_valuation_table,),
        phase=Phase.PRE_REPLAY, order=45, after=(load_raw_market_data,),
        description="市场价格向前填充",
        compute=lambda state, ctx: _causal_valuation(state, ctx),
    )

    lookup_market_snapshot: ClassVar[FlowDefinition] = FlowDefinition(
        "lookup_market_snapshot",
        inputs=(_execution_price_basis_ref, price_tables),
        outputs=(
            current_prices,
            current_market_snapshot,
            current_tradable_status,
            current_order_constraints,
            volume,
            required_frequency,
            required_factor_columns,
        ),
        description="读取市场快照",
        input_materialization=True,
        compute=lambda state, ctx: _set_current_market_snapshot(state, ctx),
    )
    lookup_current_prices_on_signal: ClassVar[FlowBinding] = lookup_market_snapshot.bind(
        name="lookup_current_prices_on_signal",
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=1,
        description="读取信号时点市场快照",
    )
    lookup_current_prices_on_bar: ClassVar[FlowBinding] = lookup_market_snapshot.bind(
        name="lookup_current_prices_on_bar",
        phase=Phase.PER_EVENT, event_kind=EventKind.BAR, order=1,
        description="读取行情时点市场快照",
    )
    lookup_current_prices_on_timer: ClassVar[FlowBinding] = lookup_market_snapshot.bind(
        name="lookup_current_prices_on_timer",
        phase=Phase.PER_EVENT, event_kind=EventKind.TIMER, order=1,
        description="读取定时时点市场快照",
    )
    lookup_current_prices_on_order: ClassVar[FlowBinding] = lookup_market_snapshot.bind(
        name="lookup_current_prices_on_order",
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=1,
        description="读取订单时点市场快照",
        event_payload_inputs=("order",),
    )
    lookup_current_prices_on_trade_intent: ClassVar[FlowBinding] = lookup_market_snapshot.bind(
        name="lookup_current_prices_on_trade_intent",
        phase=Phase.PER_EVENT, event_kind=EventKind.TRADE_INTENT, order=1,
        description="读取交易意图时点市场快照",
        event_payload_inputs=("*",),
    )
    lookup_current_prices_on_ledger: ClassVar[FlowBinding] = lookup_market_snapshot.bind(
        name="lookup_current_prices_on_ledger",
        phase=Phase.PER_EVENT, event_kind=EventKind.LEDGER, order=1,
        description="读取账本事件时点市场快照",
    )
    lookup_historical_fields: ClassVar[FlowDefinition] = FlowDefinition(
        "lookup_historical_fields",
        inputs=(
            EngineModule.engine_mode,
            _fee_mode_ref,
            _fixed_fee_rate_ref,
            _margin_mode_ref,
            _fixed_margin_ratio_ref,
            _accounting_mode_ref,
            _cost_basis_method_ref,
            _daily_mark_to_market_enabled_ref,
            CustomProductModule.custom_product_fields,
        ),
        outputs=(current_historical_fields,),
        description="读取交易规则字段",
        input_materialization=True,
        compute=lambda state, ctx: _set_current_historical_fields(state, ctx),
    )
    lookup_historical_fields_on_signal: ClassVar[FlowBinding] = lookup_historical_fields.bind(
        name="lookup_historical_fields_on_signal",
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=2,
        description="读取信号交易规则字段",
    )
    lookup_historical_fields_on_order: ClassVar[FlowBinding] = lookup_historical_fields.bind(
        name="lookup_historical_fields_on_order",
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=2,
        description="读取订单交易规则字段",
        event_payload_inputs=("order",),
    )
    lookup_historical_fields_on_trade_intent: ClassVar[FlowBinding] = lookup_historical_fields.bind(
        name="lookup_historical_fields_on_trade_intent",
        phase=Phase.PER_EVENT, event_kind=EventKind.TRADE_INTENT, order=2,
        description="读取交易意图交易规则字段",
    )
    lookup_historical_fields_on_ledger: ClassVar[FlowBinding] = lookup_historical_fields.bind(
        name="lookup_historical_fields_on_ledger",
        phase=Phase.PER_EVENT, event_kind=EventKind.LEDGER, order=2,
        description="读取账本事件交易规则字段",
    )

    flows: ClassVar[tuple[Flow | FlowBinding, ...]] = (
        resolve_market_data_request, check_market_data_coverage, load_raw_market_data, build_trading_day_resolver,
        causal_valuation,
        initialize_field_state, handle_field_changes,
        lookup_current_prices_on_bar, lookup_current_prices_on_timer,
        lookup_current_prices_on_signal,
        lookup_current_prices_on_order, lookup_current_prices_on_trade_intent,
        lookup_current_prices_on_ledger,
        lookup_historical_fields_on_signal, lookup_historical_fields_on_order,
        lookup_historical_fields_on_trade_intent, lookup_historical_fields_on_ledger,
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


def dmtm_event_table_for(state):
    return market_data_store_for(state).dmtm_event_table


def market_price_tables_for(state) -> dict[str, Any]:
    return market_data_store_for(state).market_price_tables


def factor_field_tables_for(state) -> dict[str, Any]:
    return market_data_store_for(state).factor_field_tables


def _resolve_market_data_request(state, ctx) -> None:
    request = _market_data_request(state)
    if "raw_market_data" in request:
        return
    frequencies_by_strategy: dict[Any, DataFreq] = {}
    sources_by_strategy: dict[Any, tuple[str, ...]] = {}
    factor_columns_by_strategy: dict[Any, tuple[str, ...]] = {}
    daily_signal_products: list[Any] = []
    for strategy in state.strategy_configs:
        products = list(ctx.get_for(ProductSelectionModule.products, strategy, frozenset()))
        if not products:
            continue
        config = state.config_for(strategy)
        source = _required_data_source_for_strategy(config)
        frequency = _required_frequency_for_strategy(config, products)
        factor_columns = tuple(dict.fromkeys(
            column
            for factor in factors_for_config(config)
            for column in (_factor_required_columns(factor) if config.uses_flow("signal_live") else ())
        ))
        sources_by_strategy[strategy] = source
        frequencies_by_strategy[strategy] = frequency
        factor_columns_by_strategy[strategy] = factor_columns
        if _strategy_uses_daily_signal(config):
            daily_signal_products.extend(products)
        ctx.set_for(MarketDataModule.required_data_source, strategy, source)
        ctx.set_for(MarketDataModule.required_frequency, strategy, frequency)
        ctx.set_for(MarketDataModule.required_factor_columns, strategy, factor_columns)

    store = market_data_store_for(state)
    store.required_data_source_by_strategy = dict(sources_by_strategy)
    store.required_frequency_by_strategy = dict(frequencies_by_strategy)
    store.required_factor_columns_by_strategy = dict(factor_columns_by_strategy)
    if daily_signal_products:
        _expand_market_data_request_to_complete_trading_days(request)
    unique_sources = {source for source in sources_by_strategy.values()}
    if len(unique_sources) == 1:
        ctx.set(MarketDataModule.required_data_source, next(iter(unique_sources), ()))


def _strategy_uses_daily_signal(config: Any) -> bool:
    if not config.uses_flow("signal_live") and not config.uses_flow("signal_precomputed"):
        return False
    from tools.testers.backtest.modules.factor_signal import _effective_signal_frequency

    try:
        return DataFreq(_effective_signal_frequency(config)).is_day_multiple()
    except (TypeError, ValueError):
        return False


def _product_daily_signal_close_time(product: Any) -> str | None:
    current = product
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        value = getattr(current, "trading_day_close_time", None)
        if value not in (None, ""):
            return str(value)
        parent_getter = getattr(current, "get_parent_product", None)
        current = parent_getter() if callable(parent_getter) else None
    return None


def _normalise_daily_signal_close_time(value: Any) -> str:
    text = str(value)
    try:
        parsed = pd.Timestamp(f"2000-01-01 {text}")
    except (TypeError, ValueError):
        return text
    if parsed.microsecond:
        return parsed.strftime("%H:%M:%S.%f").rstrip("0")
    if parsed.second:
        return parsed.strftime("%H:%M:%S")
    return parsed.strftime("%H:%M")


def _inferred_daily_signal_close_times(
    products: list[Any],
    raw_prices: Any,
    *,
    timezone: str | None,
) -> dict[Any, str]:
    if not isinstance(raw_prices, pd.DataFrame) or raw_prices.empty:
        return {}
    inferred: dict[Any, str] = {}
    for product in products:
        if product not in raw_prices.columns:
            continue
        series = raw_prices[product].dropna()
        if series.empty:
            continue
        last_events = DataIndex.trading_day_last_event_times_from_index(series.index)
        event_times = pd.DatetimeIndex(last_events.to_list())
        if event_times.tz is not None and timezone is not None:
            event_times = event_times.tz_convert(timezone)
        closes = {
            _normalise_daily_signal_close_time(timestamp.time())
            for timestamp in event_times
        }
        if len(closes) != 1:
            name = str(getattr(product, "name", product))
            raise ValueError(
                "DAY1 信号要求每个产品各交易日具有稳定的最后行情事件时间；"
                f"{name} 实际为 {', '.join(sorted(closes))}"
            )
        if closes:
            inferred[product] = next(iter(closes))
    return inferred


def _common_daily_signal_close_time(
    products: list[Any],
    *,
    inferred: dict[Any, str] | None = None,
) -> str:
    inferred = inferred or {}
    by_close: dict[str, list[str]] = {}
    missing: list[str] = []
    for product in dict.fromkeys(products):
        name = str(getattr(product, "name", product))
        close = _product_daily_signal_close_time(product)
        if close is None:
            close = inferred.get(product)
        if close is None:
            missing.append(name)
            continue
        close = _normalise_daily_signal_close_time(close)
        by_close.setdefault(close, []).append(name)
    if missing:
        raise ValueError(
            "DAY1 信号需要产品已存储的 trading_day close，"
            "或可从完整行情交易日推断的最后事件时间；缺失: "
            + "、".join(sorted(missing))
        )
    if len(by_close) != 1:
        details = "; ".join(
            f"{close}: {'、'.join(sorted(names))}"
            for close, names in sorted(by_close.items())
        )
        raise ValueError(
            "DAY1 信号当前要求所有参与回测的产品具有相同 trading_day close；"
            f"实际为 {details}"
        )
    return next(iter(by_close))


def _active_daily_signal_products(
    state: Any,
    ctx: Any,
    *,
    included: set[Any] | None = None,
    excluded: set[Any] | None = None,
) -> list[Any]:
    excluded = excluded or set()
    products: list[Any] = []
    for strategy in state.strategy_configs:
        if not _strategy_uses_daily_signal(state.config_for(strategy)):
            continue
        for product in ctx.get_for(ProductSelectionModule.products, strategy, frozenset()):
            if product in excluded or (included is not None and product not in included):
                continue
            products.append(product)
    return list(dict.fromkeys(products))


def _resolve_daily_signal_close_after_coverage(
    state: Any,
    ctx: Any,
    *,
    included: set[Any] | None = None,
    excluded: set[Any] | None = None,
) -> None:
    products = _active_daily_signal_products(
        state,
        ctx,
        included=included,
        excluded=excluded,
    )
    store = market_data_store_for(state)
    if not products:
        store.daily_signal_close_time = None
        return
    inferred = _inferred_daily_signal_close_times(
        [
            product
            for product in products
            if _product_daily_signal_close_time(product) is None
        ],
        store.raw_prices_table,
        timezone=_market_data_event_timezone(state),
    )
    store.daily_signal_close_time = _common_daily_signal_close_time(
        products,
        inferred=inferred,
    )


def _expand_market_data_request_to_complete_trading_days(request: dict[str, Any]) -> None:
    for key in ("start_dt", "end_dt"):
        value = request.get(key)
        if not isinstance(value, DataTime) or not value.is_set:
            continue
        request[key] = DataTime.parse(value.date_str, precision="trading_day")


def resolved_bar_frequency_for_strategy(state, strategy: Any | None = None) -> DataFreq | None:
    """Return the PRE_REPLAY-resolved bar frequency for scheduling.

    MarketDataModule owns data-frequency resolution. Event scheduling should
    consume that result rather than re-inferring frequency from the index on
    every BAR/SIGNAL.  ``None`` is returned for raw/legacy paths that have not
    run ``resolve_market_data_request``; callers can then use their local
    fallback.
    """
    frequencies = market_data_store_for(state).required_frequency_by_strategy
    if strategy is not None:
        frequency = frequencies.get(strategy)
        if frequency is not None:
            return frequency
    unique = {frequency.name: frequency for frequency in frequencies.values()}
    if len(unique) == 1:
        return next(iter(unique.values()))
    return None


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
    if not mode:
        mode = "auto"
    if mode == "fixed":
        fixed = str(config.get(MarketDataModule.freq_fixed, "") or "").strip()
        if not fixed:
            raise ValueError("数据频率模式为固定时，必须提供 freq_fixed")
        return DataFreq(fixed)
    if mode != "auto":
        raise ValueError(f"不支持的数据频率模式: {mode!r}")
    return _infer_required_frequency_from_factors(factors_for_config(config), products)


def _infer_required_frequency_from_factor(factor: Any, products: list[Any]) -> DataFreq:
    return _infer_required_frequency_from_factors((factor,), products)


def _infer_required_frequency_from_factors(factors: tuple[Any, ...], products: list[Any]) -> DataFreq:
    desired_freqs = set().union(*(_desired_factor_frequencies(factor) for factor in factors)) if factors else set()
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
    desired: set[DataFreq] = set()
    signal_freq = getattr(factor, "freq", None) or getattr(factor, "_freq", None)
    if signal_freq is not None:
        desired.add(DataFreq(signal_freq))
    expr = (
        getattr(factor, "_expr", None)
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
        store.publish_coverage_seed(raw)
        ctx.set(MarketDataModule.market_data_load_plan, _market_data_coverage_seed_summary(raw))
        ctx.set(MarketDataModule.excluded_out_of_range_products, _market_data_excluded_products_summary(store.excluded_out_of_range))
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
    ctx.set(MarketDataModule.market_data_load_plan, _market_data_load_plan_summary(store.load_plan))
    ctx.set(MarketDataModule.excluded_out_of_range_products, _market_data_excluded_products_summary(store.excluded_out_of_range))
    _record_excluded_out_of_range_products(state, store.excluded_out_of_range)


def _market_data_load_plan_summary(load_plan: list[Any]) -> dict[str, Any]:
    items: dict[str, dict[str, str]] = {}
    for plan_item in load_plan:
        product, freq, source = _unpack_market_data_load_plan_item(plan_item)
        items[str(getattr(product, "name", product))] = {
            "frequency": str(getattr(freq, "name", freq)),
            "data_source": _data_source_instance_label(source),
        }
    return {"type": "MarketDataLoadPlan", "items": items, "count": len(items)}


def _market_data_coverage_seed_summary(raw: dict[str, Any]) -> dict[str, Any]:
    products: list[str] = []
    raw_prices = raw.get("raw_prices")
    raw_price_columns = getattr(raw_prices, "columns", None)
    for product in list(raw_price_columns) if raw_price_columns is not None else []:
        product_text = str(product)
        if product_text not in products:
            products.append(product_text)
    price_tables = raw.get("price_tables")
    if isinstance(price_tables, dict):
        for table in price_tables.values():
            table_columns = getattr(table, "columns", None)
            for product in list(table_columns) if table_columns is not None else []:
                product_text = str(product)
                if product_text not in products:
                    products.append(product_text)
    items = {
        product: {"frequency": "provided", "data_source": "raw_market_data"}
        for product in products
    }
    return {"type": "MarketDataLoadPlan", "items": items, "count": len(items)}


def _market_data_excluded_products_summary(products: tuple[Any, ...]) -> dict[str, Any]:
    rows = [
        {"product": str(getattr(product, "name", product))}
        for product in products
    ]
    return {"type": "MarketDataExcludedProducts", "rows": rows, "count": len(rows)}


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
        if freq.name != required_name and _frequency_compatible(freq, {required_frequency}):
            return freq
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
    declaration = data_source_declaration(key)
    return declaration.execution_providers() if declaration is not None else ()


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
    factor_columns = _live_factor_required_columns(state)
    price_series_by_basis: dict[str, dict[Any, pd.Series]] = {
        basis: {} for basis, _column in price_columns
    }
    volume_series_by_product: dict[Any, pd.Series] = {}
    factor_series_by_column: dict[str, dict[Any, pd.Series]] = {
        column: {} for column in factor_columns
    }
    missing_products: list[str] = []
    trading_day_mapping: dict[pd.Timestamp, pd.Timestamp] = {}
    store = market_data_store_for(state)
    term_structure_contracts = _term_structure_concrete_contracts(state, ctx)
    event_timezone = _market_data_event_timezone(state)

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
        required_columns = list(dict.fromkeys(
            [column for _basis, column in price_columns] + list(factor_columns)
        ))
        requested_columns = (
            required_columns
            + [column for _basis, column in optional_price_columns]
            + [DataColumn.VOLUME.name]
        )
        try:
            data_view = getattr(product, freq.name)
            df = data_view.get_and_adjust_cols(
                requested_columns,
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
                    required_columns,
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
        event_index = _event_index_for_frame(df, timezone=event_timezone)
        trading_days = _trading_days_for_frame(df)
        trading_day_mapping.update(_trading_day_mapping_from_market_data(
            df,
            event_timestamps=event_index,
            trading_days=trading_days,
        ))
        series_cache: dict[str, pd.Series] = {}

        def series_for(column: str) -> pd.Series:
            cached = series_cache.get(column)
            if cached is None:
                cached = _series_on_prepared_event_index(df[column], event_index)
                series_cache[column] = cached
            return cached

        series_by_product[product] = series_for(DataColumn.CLOSE.name)
        for basis, column in price_columns:
            if column in df.columns:
                price_series_by_basis[basis][product] = series_for(column)
        for basis, column in optional_price_columns:
            if column in df.columns:
                if basis == "settlement":
                    price_series_by_basis.setdefault(basis, {})[product] = _settlement_series_on_last_event(
                        df,
                        column,
                        timezone=event_timezone,
                        event_times=event_index,
                        trading_days=trading_days,
                    )
                else:
                    price_series_by_basis.setdefault(basis, {})[product] = series_for(column)
        for column in factor_columns:
            if column in df.columns:
                factor_series_by_column[column][product] = series_for(column)
            else:
                missing_products.append(
                    f"{getattr(product, 'name', product)}(缺少因子字段 {column})"
                )
        if DataColumn.VOLUME.name in df.columns:
            volume_series_by_product[product] = series_for(DataColumn.VOLUME.name)
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
    factor_field_tables = {
        column: pd.DataFrame(values)
        for column, values in factor_series_by_column.items()
        if values
    }
    raw = {
        "raw_prices": raw_prices,
        "price_tables": price_tables,
        "factor_field_tables": factor_field_tables,
        "settlement_price": price_tables.get("settlement"),
        "historical_field_provider": load_market_rule_field_provider(
            transaction_fee_source=_transaction_fee_source_for_state(state),
        ),
        "trading_day_resolver": TimestampTradingDayResolver(trading_day_mapping) if trading_day_mapping else None,
        "historical_field_policy": request.get("policy", "auto"),
        "historical_field_names": _required_market_rule_field_names(state),
        "included_products": tuple(series_by_product.keys()),
        "excluded_out_of_range_products": tuple(store.excluded_out_of_range),
        "volume": volume,
        "dmtm_event_table": _dmtm_event_table_from_mapping(
            trading_day_mapping,
            timezone=event_timezone,
        ),
    }
    _publish_raw_market_data(state, ctx, raw)


def _live_factor_required_columns(state) -> tuple[str, ...]:
    """Return exact DataColumn names read by active incremental factors."""
    columns: list[str] = []
    for values in market_data_store_for(state).required_factor_columns_by_strategy.values():
        columns.extend(values)
    return tuple(dict.fromkeys(columns))


def _factor_required_columns(factor: Any) -> tuple[str, ...]:
    expression = getattr(factor, "_source_expr", factor)
    column_refs = getattr(expression, "column_refs", None)
    if column_refs is None:
        return ()
    refs = column_refs() if callable(column_refs) else column_refs
    columns: list[str] = []
    for ref in refs:
        column = getattr(ref, "column", None)
        name = getattr(column, "name", str(column or ""))
        if name:
            columns.append(str(name))
    return tuple(dict.fromkeys(columns))


def _series_on_event_index(series: pd.Series, *, timezone: str | None = None) -> pd.Series:
    return _series_on_prepared_event_index(
        series,
        _event_index_for_frame(series, timezone=timezone),
    )


def _event_index_for_frame(frame: pd.DataFrame | pd.Series, *, timezone: str | None = None) -> pd.DatetimeIndex:
    index = DataIndex.event_timestamps_from_index(frame.index)
    if timezone:
        if index.tz is None:
            return pd.DatetimeIndex(index.tz_localize(timezone))
        return pd.DatetimeIndex(index.tz_convert(timezone))
    if index.tz is not None:
        return pd.DatetimeIndex(index.tz_localize(None))
    return pd.DatetimeIndex(index)


def _series_on_prepared_event_index(series: pd.Series, event_index: pd.DatetimeIndex) -> pd.Series:
    result = series.copy(deep=False)
    result.index = event_index
    return result


def _settlement_series_on_last_event(
    frame: pd.DataFrame,
    column: str,
    *,
    timezone: str | None = None,
    event_times: pd.DatetimeIndex | None = None,
    trading_days: pd.Series | None = None,
) -> pd.Series:
    source = pd.to_numeric(frame[column], errors="coerce")
    resolved_trading_days = trading_days if trading_days is not None else _trading_days_for_frame(frame)
    resolved_event_times = event_times if event_times is not None else _event_index_for_frame(frame, timezone=timezone)
    visible = pd.Series(np.nan, index=frame.index, dtype="float64")
    groups = pd.Series(range(len(frame)), index=frame.index).groupby(resolved_trading_days)
    for _key, positions in groups:
        pos = list(positions.to_numpy())
        if not pos:
            continue
        values = source.iloc[pos]
        valid = values[(values.notna()) & (values != 0)]
        if valid.empty:
            continue
        day_event_times = resolved_event_times.take(pos)
        last_position = pos[int(np.argmax(day_event_times.to_numpy(dtype="datetime64[ns]").astype("int64", copy=False)))]
        visible.iloc[last_position] = valid.iloc[-1]
    return _series_on_prepared_event_index(visible, resolved_event_times)


def _trading_days_for_frame(frame: pd.DataFrame) -> pd.Series:
    if "trading_day" in frame.columns:
        values = pd.to_datetime(frame["trading_day"], errors="coerce").dt.normalize()
        return pd.Series(values.to_numpy(), index=frame.index)
    days = DataIndex.trading_day_index_from_index(frame.index)
    return pd.Series(days.to_numpy(), index=frame.index)


def _market_data_event_timezone(state) -> str | None:
    values = {
        str(state.config_for(strategy).get(RunWindowModule.timezone, "Asia/Shanghai") or "Asia/Shanghai")
        for strategy in getattr(state, "strategy_configs", {})
    }
    if len(values) == 1:
        return next(iter(values))
    return "Asia/Shanghai" if not values else None


def _trading_day_mapping_from_market_data(
    frame: pd.DataFrame,
    *,
    event_timestamps: pd.DatetimeIndex | None = None,
    trading_days: pd.Series | pd.DatetimeIndex | None = None,
) -> dict[pd.Timestamp, pd.Timestamp]:
    if isinstance(frame.index, pd.MultiIndex):
        days = trading_days if trading_days is not None else DataIndex.trading_day_index_from_index(frame.index)
        timestamps = event_timestamps if event_timestamps is not None else DataIndex.event_timestamps_from_index(frame.index)
    elif "trading_day" in frame.columns:
        days = trading_days if trading_days is not None else pd.DatetimeIndex(pd.to_datetime(frame["trading_day"], errors="coerce"))
        timestamps = event_timestamps if event_timestamps is not None else pd.DatetimeIndex(frame.index)
    else:
        return {}
    # The mapping is an index-to-index projection.  Converting each element
    # through ``pd.Timestamp`` in Python made PRE_REPLAY spend unnecessary
    # time boxing every bar; vectorise the timezone/normalisation work while
    # retaining the same last-row-wins dict semantics for duplicate timestamps.
    timestamp_index = pd.DatetimeIndex(timestamps)
    if timestamp_index.tz is not None:
        timestamp_index = timestamp_index.tz_localize(None)
    day_index = pd.DatetimeIndex(days).normalize()
    valid = (~timestamp_index.isna()) & (~day_index.isna())
    return dict(zip(timestamp_index[valid], day_index[valid], strict=True))


def _dmtm_event_table_from_mapping(
    mapping: Mapping[pd.Timestamp, pd.Timestamp],
    *,
    timezone: str | None,
) -> pd.DataFrame | None:
    """Build an index-only table that retains the source trading-day axis.

    Causal price tables intentionally flatten their MultiIndex to event time.
    DMTM cannot group that flattened index by calendar date because a night
    event and the following day session can belong to one exchange day.  The
    source mapping is already collected while loading the market data, so keep
    it as a small private table for ledger-event scheduling.
    """
    if not mapping:
        return None
    rows = sorted(mapping.items(), key=lambda item: item[0])
    timestamps = pd.DatetimeIndex([item[0] for item in rows])
    if timezone:
        timestamps = timestamps.tz_localize(timezone)
    trading_days = pd.DatetimeIndex([
        pd.Timestamp(item[1]).normalize() for item in rows
    ])
    index = pd.MultiIndex.from_arrays(
        [trading_days, timestamps],
        names=["DAY1", "MIN1"],
    )
    return pd.DataFrame({"_DMTM_EVENT": 1.0}, index=index)


def _unpack_market_data_load_plan_item(plan_item: Any) -> tuple[Any, Any, Any | None]:
    if isinstance(plan_item, tuple) and len(plan_item) == 3:
        return plan_item
    product, freq = plan_item
    return product, freq, None


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
    if store.trading_day_resolver is not None:
        ctx.set(MarketDataModule.trading_day_resolver, store.trading_day_resolver)
        return
    if raw_prices is None or raw_prices.empty:
        ctx.set(MarketDataModule.trading_day_resolver, None)
        store.trading_day_resolver = None
        return
    resolver = build_trading_day_resolver_from_market_data(raw_prices)
    ctx.set(MarketDataModule.trading_day_resolver, resolver)
    store.trading_day_resolver = resolver


def _initial_historical_fields_frame_for_products(
    products: list[Any],
    timestamps: pd.DatetimeIndex,
    *,
    provider: FieldHistoryProvider,
    trading_day_resolver: TradingDayResolver,
    field_names: tuple[object, ...],
    fallback: HistoricalFieldFallbackPolicy | str,
    strict_field_names: tuple[object, ...] = (),
) -> dict[str, pd.DataFrame]:
    """Resolve causal product history over exchange clearing baselines."""
    resolved: dict[str, pd.DataFrame] = {}
    strict_names = {str(name) for name in strict_field_names}
    normalized_fields = tuple(dict.fromkeys(str(name) for name in field_names))
    if not normalized_fields:
        return resolved

    # The query-frame construction resolves each product's identity once per
    # call.  Keep fields with the same fallback policy together so that the
    # common path does not rebuild those identical query frames for every
    # field.  The fallback path below deliberately remains field-by-field: a
    # batch may fail because one strict field is missing, and the old behavior
    # then retries that field per product and applies exchange defaults.
    defaults_by_product = {
        id(product): exchange_rule_defaults_for_product(product, normalized_fields)
        for product in products
    }
    fields_by_fallback: OrderedDict[str, list[str]] = OrderedDict()
    fallback_by_field: dict[str, HistoricalFieldFallbackPolicy | str] = {}
    for field_name in normalized_fields:
        has_exchange_baseline = all(
            field_name in defaults_by_product[id(product)]
            for product in products
        )
        field_fallback: HistoricalFieldFallbackPolicy | str = (
            HistoricalFieldFallbackPolicy.STRICT_HISTORICAL
            if field_name in strict_names or has_exchange_baseline
            else fallback
        )
        fallback_by_field[field_name] = field_fallback
        fallback_key = str(getattr(field_fallback, "value", field_fallback))
        fields_by_fallback.setdefault(fallback_key, []).append(field_name)

    for grouped_fields in fields_by_fallback.values():
        grouped_fallback = fallback_by_field[grouped_fields[0]]
        try:
            batch = historical_fields_frame_for_products(
                products,
                timestamps,
                provider=provider,
                trading_day_resolver=trading_day_resolver,
                field_names=tuple(grouped_fields),
                fallback=grouped_fallback,
            )
            for field_name in grouped_fields:
                resolved[field_name] = batch[field_name]
            continue
        except MissingHistoricalField:
            pass

        for field_name in grouped_fields:
            field_fallback = fallback_by_field[field_name]
            try:
                batch = historical_fields_frame_for_products(
                    products,
                    timestamps,
                    provider=provider,
                    trading_day_resolver=trading_day_resolver,
                    field_names=(field_name,),
                    fallback=field_fallback,
                )
                resolved[field_name] = batch[field_name]
                continue
            except MissingHistoricalField:
                pass

            columns: dict[str, pd.Series] = {}
            for product in products:
                product_name = str(getattr(product, "name", product) or "")
                try:
                    single = historical_fields_frame_for_products(
                        [product],
                        timestamps,
                        provider=provider,
                        trading_day_resolver=trading_day_resolver,
                        field_names=(field_name,),
                        fallback=field_fallback,
                    )[field_name]
                    columns[product_name] = single.iloc[:, 0].set_axis(timestamps)
                except MissingHistoricalField:
                    defaults = defaults_by_product[id(product)]
                    if field_name not in defaults:
                        raise
                    columns[product_name] = pd.Series(
                        [defaults[field_name]] * len(timestamps),
                        index=timestamps,
                        dtype=object,
                    )
            resolved[field_name] = pd.DataFrame(columns, index=timestamps)
    # Preserve the caller's field order even though the batched execution is
    # grouped by fallback policy internally.
    return {field_name: resolved[field_name] for field_name in normalized_fields}


def _initialize_field_state(state, ctx) -> None:
    """Populate field_state_store with baseline values at run_window start.
    Uses batch FieldHistory frame query (single timestamp) instead of per-product queries."""
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    resolver = ctx.get(MarketDataModule.trading_day_resolver)
    store = market_data_store_for(state)
    provider = cast(FieldHistoryProvider | None, store.historical_field_provider)
    if raw_prices is None or raw_prices.empty or resolver is None or provider is None:
        return
    raw_policy = getattr(store, "historical_field_policy", None) or "auto"
    policy = _historical_field_policy_for_engine(state, raw_policy)
    ctx.set(MarketDataModule.historical_field_policy, policy)
    store.publish_historical_field_policy(policy)
    field_names = tuple(store.historical_field_names or _MARKET_RULE_FIELD_NAMES)
    strict_field_names: tuple[object, ...] = ()
    if policy != HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value:
        from tools.testers.backtest.modules.fee import _resolve_fee_mode

        if any(
            _resolve_fee_mode(
                config,
                state.ledger_config_for(state.ledger_for_strategy(strategy)),
            ) == "exact"
            for strategy, config in getattr(state, "strategy_configs", {}).items()
        ):
            strict_field_names = tuple(TRANSACTION_FEE_FIELD_NAMES)
    instruments = list(raw_prices.columns)
    all_timestamps = signal_timestamps(raw_prices)
    if len(all_timestamps) == 0:
        return
    first_ts = all_timestamps[0]
    
    # Collect parent product objects (contracts resolve to parent, base products stay)
    # and initialize each parent at its first observed market-data timestamp.
    # Newly listed products can appear inside a long run after the run's first
    # timestamp; querying FieldHistory for them at global run start would create
    # a false missing-baseline error.
    parent_objects: dict[str, Any] = {}
    product_to_parent_key: dict[str, str] = {}
    parent_first_timestamps: dict[str, pd.Timestamp] = {}
    for instrument in instruments:
        inst_name = str(getattr(instrument, "name", instrument) or "")
        parent = getattr(instrument, "parent_product", None)
        if parent is not None and parent is not instrument:
            pname = str(getattr(parent, "name", parent) or "")
            product_to_parent_key[inst_name] = pname
            if pname not in parent_objects:
                parent_objects[pname] = parent
        else:
            product_to_parent_key[inst_name] = inst_name
            if inst_name not in parent_objects:
                parent_objects[inst_name] = instrument
        first_observed = _first_valid_market_data_timestamp(raw_prices, instrument)
        if first_observed is not None:
            existing = parent_first_timestamps.get(product_to_parent_key[inst_name])
            if existing is None or first_observed < existing:
                parent_first_timestamps[product_to_parent_key[inst_name]] = first_observed
    
    parent_baselines: dict[str, dict[str, object]] = {}
    for pname in parent_objects:
        parent_baselines[pname] = {}
    parents_by_timestamp: dict[pd.Timestamp, list[str]] = {}
    for pname in parent_objects:
        ts = parent_first_timestamps.get(pname)
        if ts is not None:
            parents_by_timestamp.setdefault(ts, []).append(pname)
    for timestamp, parent_names in parents_by_timestamp.items():
        products_for_timestamp = [parent_objects[pname] for pname in parent_names]
        frame_result = _initial_historical_fields_frame_for_products(
            products_for_timestamp,
            pd.DatetimeIndex([timestamp]),
            provider=provider,
            trading_day_resolver=resolver,
            field_names=field_names,
            fallback=policy,
            strict_field_names=strict_field_names,
        )
        for pname in parent_names:
            for fname in field_names:
                fn = str(fname)
                fdf = frame_result.get(fn)
                if fdf is not None and not fdf.empty:
                    val = fdf.iloc[0].get(pname)
                    if val is not None and not (isinstance(val, float) and (pd.isna(val) or val == float("inf") or val == float("-inf"))):
                        parent_baselines[pname][fn] = val
    
    # Populate store  
    for instrument in instruments:
        inst_name = str(getattr(instrument, "name", instrument) or "")
        pname = product_to_parent_key.get(inst_name, inst_name)
        store.field_state_store[inst_name] = dict(parent_baselines.get(pname, {}))
    ctx.set(MarketDataModule.field_state_baseline, {
        inst_name: dict(values)
        for inst_name, values in store.field_state_store.items()
        if inst_name in product_to_parent_key
    })
    # Register FIELD_CHANGE events from FieldHistory provider's record frame
    # This replaces the old per-timestamp bulk query with incremental events
    ctx.set(MarketDataModule.field_change_events, [])
    try:
        provider_frame = provider.frame
        if provider_frame is not None and not provider_frame.empty:
            from tools.testers.backtest.engines.native.events import EventDraft
            import pandas as _pd
            
            # Determine run window bounds from raw_prices index
            all_ts = signal_timestamps(raw_prices)
            if len(all_ts) > 1:
                run_start = _pd.Timestamp(all_ts[0])
                run_end = _pd.Timestamp(all_ts[-1])
            elif len(all_ts) == 1:
                run_start = _pd.Timestamp(all_ts[0])
                run_end = run_start
            else:
                run_start = run_end = None
            
            if run_start is not None and run_end is not None:
                # Build product code set from instruments.  The event
                # materialisation below used to re-scan every instrument for
                # every FieldHistory row.  Resolve the (small) code-to-product
                # relation once; this keeps the matching semantics identical
                # while making the hot path proportional to matching rows
                # instead of ``rows * instruments``.
                import re as _re

                instrument_names = tuple(
                    str(getattr(inst, "name", inst) or "")
                    for inst in instruments
                )
                product_codes: set[str] = set()
                for inst_name in instrument_names:
                    code = inst_name.split('.')[0].split('|')[0]
                    # Extract base code (strip contract suffix like 2605)
                    base_code = _re.sub(r'[0-9]+$', '', code)
                    if base_code:
                        product_codes.add(base_code)
                    product_codes.add(code)
                
                # Query provider frame for matching records in the run window
                # ``provider_frame`` is immutable for the lifetime of this
                # replay, so copying thousands of rows here only adds fixed
                # allocation and refcount work.
                pf = provider_frame
                pf_instrument = pf['instrument'].astype(str)
                pf_field = pf['field_name'].astype(str)
                pf_ts = pf['effective_timestamp']
                
                mask = pf_instrument.isin(product_codes)
                mask &= pf_field.isin([str(f) for f in field_names])
                mask &= pf_ts.notna()
                mask &= (pf_ts >= run_start) & (pf_ts <= run_end)
                
                change_records = pf[mask]
                field_change_drafts: list[dict[str, object]] = []
                if not change_records.empty:
                    matched_products_by_code = {
                        code: tuple(
                            inst_name
                            for inst_name in instrument_names
                            if (
                                inst_name.startswith(code + '.')
                                or inst_name == code
                                or inst_name.startswith(code)
                            )
                        )
                        for code in {
                            str(value)
                            for value in change_records['instrument'].tolist()
                        }
                    }
                    # Group by timestamp then by instrument
                    for (change_ts,), ts_group in change_records.groupby('effective_timestamp'):
                        changes: dict[str, dict[str, object]] = {}
                        for row in ts_group.itertuples(index=False):
                            code = str(row.instrument)
                            field = str(row.field_name)
                            value = row.value
                            # Match code to full product names using the
                            # precomputed relation above.  Tuple iteration
                            # also avoids constructing a Series per row.
                            for product_key in matched_products_by_code.get(code, ()):
                                changes.setdefault(product_key, {})[field] = value
                        if changes:
                            field_change_drafts.append({
                                "timestamp": str(_pd.Timestamp(change_ts)),
                                "products": changes,
                            })
                            for strategy in getattr(state, "strategy_configs", {}):
                                ctx._event_queue.push_event(EventDraft(
                                    kind=EventKind.FIELD_CHANGE,
                                    timestamp=_pd.Timestamp(change_ts),
                                    strategy=strategy,
                                    payload={"changes": changes},
                                ))
                ctx.set(MarketDataModule.field_change_events, field_change_drafts)
    except Exception:
        import traceback
        ctx.set(MarketDataModule.historical_field_policy, "fallback")


def _first_valid_market_data_timestamp(raw_prices: pd.DataFrame, instrument: Any) -> pd.Timestamp | None:
    try:
        values = raw_prices[instrument]
    except Exception:
        return None
    if isinstance(values, pd.DataFrame):
        valid_index = values.index[values.notna().any(axis=1)]
    else:
        valid_index = cast(pd.Series, values).dropna().index
    if len(valid_index) == 0:
        return None
    events = DataIndex(valid_index).event_timestamps()
    if len(events) == 0:
        return None
    return pd.Timestamp(events[0])



def _handle_field_changes(state, ctx) -> None:
    """Process FIELD_CHANGE events: update field_state_store with new values."""
    store = market_data_store_for(state)
    changed = False
    for strategy in ctx.active_strategies:
        for payload in ctx.payloads_for(strategy, kind="field_change"):
            if not isinstance(payload, dict):
                continue
            changes = payload.get("changes", {})
            if not isinstance(changes, dict):
                continue
            for product_name, fields in changes.items():
                if not isinstance(fields, dict):
                    continue
                if product_name not in store.field_state_store:
                    store.field_state_store[product_name] = {}
                store.field_state_store[product_name].update(fields)
                changed = True
    if changed:
        # A FIELD_CHANGE event is the only supported mutation point for the
        # event-driven field-state path.  Clear both caches so a repeated
        # timestamp cannot observe the previous snapshot.
        store.field_state_generation += 1
        store.field_state_resolved_cache = None
        store.historical_fields_cache.clear()


def _load_historical_fields(state, ctx) -> None:
    # Obsoleted by initialize_field_state.  Kept as a no-op placeholder
    # so existing flow-registration and manifest references don't break;
    # the actual historical-field state is now managed via field_state_store
    # + FIELD_CHANGE events.
    pass


def _transaction_fee_source_for_state(state) -> str:
    sources: list[str] = []
    strategies = getattr(state, "strategy_configs", {})
    if not strategies:
        return TRANSACTION_FEE_SOURCE_EXCHANGE
    for strategy in strategies:
        ledger = state.ledger_for_strategy(strategy)
        ledger_config = state.ledger_config_for(ledger)
        source = _transaction_fee_source_for_ledger_config(ledger_config)
        if source not in sources:
            sources.append(source)
    if len(sources) > 1:
        raise ValueError(
            "同一次 native 回测只能使用一个交易费来源；"
            f"当前解析到 {', '.join(sources)}。请拆分回测或统一 CounterParty。"
        )
    return sources[0] if sources else TRANSACTION_FEE_SOURCE_EXCHANGE


def _transaction_fee_source_for_ledger_config(ledger_config=None) -> str:
    return _normalise_transaction_fee_source(
        getattr(ledger_config, "transaction_fee_source", None) or TRANSACTION_FEE_SOURCE_EXCHANGE
    )

def _publish_raw_market_data(state, ctx, raw: dict[str, Any]) -> None:
    ctx.set(MarketDataModule.raw_prices, raw.get("raw_prices"))
    ctx.set(MarketDataModule.price_tables, raw.get("price_tables") or {"close": raw.get("raw_prices")})
    ctx.set(MarketDataModule.lot_sizes, raw.get("lot_sizes", {}))
    ctx.set(MarketDataModule.margin_ratio, raw.get("margin_ratio", {}))
    ctx.set(MarketDataModule.settlement_price, raw.get("settlement_price"))
    ctx.set(MarketDataModule.volume, raw.get("volume"))
    ctx.set(MarketDataModule.historical_field_provider, raw.get("historical_field_provider"))
    store = market_data_store_for(state)
    store.publish_raw(raw)
    included = set(store.included_products) if store.included_products is not None else None
    _resolve_daily_signal_close_after_coverage(
        state,
        ctx,
        included=included,
        excluded=set(store.excluded_out_of_range),
    )
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
    policy = str(raw_policy or "auto").strip().lower()
    if policy in {"", "auto", "automatic"}:
        return str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value)
    if policy not in {
        str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value),
        str(HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value),
    }:
        raise ValueError(f"unsupported historical_field_policy: {raw_policy!r}")
    return policy


def _required_market_rule_field_names(state) -> tuple[str, ...]:
    fields: list[str] = list(_MARKET_RULE_FIELD_NAMES)
    allocation_ref = FieldRef("allocation_policy", owner="GroupMembershipModule")
    for strategy, config in getattr(state, "strategy_configs", {}).items():
        from tools.testers.backtest.modules.fee import _resolve_fee_mode
        from tools.testers.backtest.modules.margin import _resolve_margin_mode
        from tools.testers.backtest.modules.trading_rule import (
            _configured_tristate_bool,
            _effective_accounting_mode,
        )

        ledger = state.ledger_for_strategy(strategy)
        ledger_config = state.ledger_config_for(ledger)
        fee_mode = _resolve_fee_mode(config, ledger_config)
        if fee_mode != "zero":
            fields.extend(TRANSACTION_FEE_FIELD_NAMES)
        if fee_mode == "exact" or engine_mode_for(config) == "exact":
            fields.append("CostBasisMethod")
        accounting_mode = _effective_accounting_mode(config, ledger_config)
        if accounting_mode == "Auto":
            if fee_mode != "zero":
                fields.extend(TRANSACTION_FEE_FIELD_NAMES)
            fields.extend(("CostBasisMethod", "SettlementPrice", "PreSettlementPrice", "LastSettlementPrice", "MoneyCalculationPolicy"))
        if engine_mode_for(config) == "exact":
            fields.extend(("CostBasisMethod", "SettlementPrice", "PreSettlementPrice", "LastSettlementPrice", "MoneyCalculationPolicy"))
        if accounting_mode == "Custom" and _configured_tristate_bool(
            getattr(ledger_config, "daily_mark_to_market_enabled", None),
        ) is not False:
            fields.extend(("SettlementPrice", "PreSettlementPrice", "LastSettlementPrice", "MoneyCalculationPolicy"))
        margin_mode = _resolve_margin_mode(config, ledger_config)
        allocation = str(config.get(allocation_ref, "") or "")
        if margin_mode not in {"none", "zero"}:
            fields.extend(_MARGIN_FIELD_NAMES)
    return tuple(dict.fromkeys(fields))


def _causal_valuation(state, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    store = market_data_store_for(state)
    causal_prices = raw_prices.ffill()
    store.publish_causal_valuation(causal_prices)
    ctx.set(MarketDataModule.causal_valuation_table, causal_prices)


def _set_current_market_snapshot(state, ctx) -> None:
    if _inert_margin_check_batch(state, ctx):
        ctx.set(MarketDataModule.current_market_snapshot, {})
        ctx.set(MarketDataModule.current_prices, {})
        ctx.set(MarketDataModule.volume, {})
        ctx.set(MarketDataModule.current_tradable_status, {})
        ctx.set(MarketDataModule.current_order_constraints, {})
        return
    snapshot = _market_snapshot_for_event(state, ctx)
    prices = _current_prices_for_event(state, snapshot, ctx)
    ctx.set(MarketDataModule.current_market_snapshot, snapshot)
    ctx.set(MarketDataModule.current_prices, prices)
    ctx.set(MarketDataModule.volume, snapshot.get("volume", {}))
    store = market_data_store_for(state)
    for strategy in ctx.active_strategies:
        frequency = store.required_frequency_by_strategy.get(strategy)
        if frequency is not None:
            ctx.set_for(MarketDataModule.required_frequency, strategy, frequency)
        columns = store.required_factor_columns_by_strategy.get(strategy)
        if columns is not None:
            ctx.set_for(MarketDataModule.required_factor_columns, strategy, columns)
    if getattr(ctx, "event_kind", None) is EventKind.LEDGER:
        ctx.set(MarketDataModule.current_tradable_status, {})
        ctx.set(MarketDataModule.current_order_constraints, {})
    else:
        # Both fields are projections of the same side-aware constraints.  Do
        # the exchange-rule walk once per event; calling the two public
        # helpers independently would resolve every product twice while
        # producing the same values.
        constraints = order_constraints_from_snapshot(snapshot)
        ctx.set(MarketDataModule.current_order_constraints, constraints)
        ctx.set(
            MarketDataModule.current_tradable_status,
            {product: constraint.tradable for product, constraint in constraints.items()},
        )


def _current_prices_for_event(state, snapshot: dict[str, dict[Any, float]], ctx) -> dict[Any, float]:
    if getattr(ctx, "event_kind", None) is EventKind.BAR:
        basis = _bar_event_basis(ctx)
        if basis and basis != "close":
            basis_prices = snapshot.get(basis)
            if basis_prices:
                return basis_prices
    if getattr(ctx, "event_kind", None) is EventKind.ORDER:
        requested_bases = _order_event_price_bases(state, ctx)
        for basis in requested_bases:
            prices = snapshot.get(basis)
            if prices:
                return prices
        return {}
    return snapshot.get("close", {})


def _inert_margin_check_batch(state, ctx) -> bool:
    """Whether a LEDGER batch has no observable work or market-data demand.

    Margin notices are registered ahead of replay because a ledger may acquire
    a position later.  At dispatch time, however, a notice for a ledger with no
    position and an already-cleared margin state cannot affect cash, risk, or
    emitted events.  Detect that narrow case before touching the market tables.
    Other LEDGER payloads (DMTM, settlement, etc.) always keep the full path.
    """
    if getattr(ctx, "event_kind", None) is not EventKind.LEDGER:
        return False
    ledger_keys = tuple(getattr(ctx, "active_ledgers", ()) or ())
    if not ledger_keys:
        return False

    from tools.testers.backtest.engines.native.ledger import ledger_identity
    from tools.testers.backtest.modules.ledger_module import LedgerModule
    from tools.testers.backtest.modules.margin import MarginModule

    margin_state_refs = (
        MarginModule.margin_requirement,
        MarginModule.margin_reserved,
        MarginModule.margin_deficit,
        MarginModule.margin_excess,
        MarginModule.margin_utilization,
        MarginModule.margin_limit_excess,
    )
    for ledger_key in ledger_keys:
        payloads = ctx.payloads_for_ledger(ledger_key)
        if not payloads or any(
            not isinstance(payload, dict) or payload.get("kind") != "margin_check"
            for payload in payloads
        ):
            return False
        ledger = state.ledgers.get(ledger_identity(ledger_key))
        if ledger is None:
            return False
        positions = ledger.get(LedgerModule.positions, {}) or {}
        if any(abs(float(getattr(entry, "quantity", 0.0) or 0.0)) > 1e-12 for entry in positions.values()):
            return False
        if any(abs(float(ledger.get(ref, 0.0) or 0.0)) > 1e-12 for ref in margin_state_refs):
            return False
    return True


def _bar_event_basis(ctx) -> str | None:
    strategies = list(getattr(ctx, "active_strategies", ()) or ())
    if not strategies:
        return None
    try:
        draft = ctx.draft_for(strategies[0])
    except Exception:
        return None
    payload = getattr(draft, "payload", None)
    if not isinstance(payload, dict):
        return None
    basis = payload.get("bar_basis")
    return str(basis).lower() if basis else None


def _market_snapshot_for_event(state, ctx) -> dict[str, dict[Any, float]]:
    if getattr(ctx, "event_kind", None) is EventKind.BAR:
        strategies = list(getattr(ctx, "active_strategies", ()) or ())
        if strategies:
            try:
                draft = ctx.draft_for(strategies[0])
            except Exception:
                draft = None
            if draft is not None and draft.index_key is not None:
                return market_snapshot_for_index_key(state, draft.index_key)
    if getattr(ctx, "event_kind", None) is EventKind.ORDER:
        price_timestamp = _order_event_price_timestamp(ctx)
        return order_market_snapshot_at(
            state,
            ctx.timestamp,
            price_timestamp=price_timestamp,
            bases=_order_event_price_bases(state, ctx),
        )
    if getattr(ctx, "event_kind", None) is EventKind.SIGNAL:
        return signal_market_snapshot_at(state, ctx.timestamp)
    if getattr(ctx, "event_kind", None) is EventKind.LEDGER:
        return ledger_market_snapshot_at(state, ctx.timestamp)
    if (
        getattr(ctx, "event_kind", None) is EventKind.TRADE_INTENT
        and _margin_liquidation_payloads_only(ctx)
    ):
        return ledger_market_snapshot_at(state, ctx.timestamp)
    return current_market_snapshot_at(state, ctx.timestamp)


def _margin_liquidation_payloads_only(ctx) -> bool:
    payloads: list[Any] = []
    for strategy in getattr(ctx, "active_strategies", ()) or ():
        payloads.extend(ctx.payloads_for(strategy))
    for ledger in getattr(ctx, "active_ledgers", ()) or ():
        payloads.extend(ctx.payloads_for_ledger(ledger))
    if not payloads:
        return False
    return all(
        isinstance(payload, dict) and payload.get("kind") == "margin_liquidation"
        for payload in payloads
    )


def _order_event_price_timestamp(ctx) -> pd.Timestamp | None:
    for strategy in getattr(ctx, "active_strategies", ()) or ():
        for order in ctx.payloads_for(strategy):
            raw = order.get("price_timestamp", None) if hasattr(order, "get") else None
            if raw is not None:
                return pd.Timestamp(raw)
    return None


def _order_event_price_bases(state, ctx) -> tuple[str, ...]:
    bases: list[str] = []
    from tools.testers.backtest.modules.order_execution import OrderExecutionModule

    for strategy in getattr(ctx, "active_strategies", ()) or ():
        try:
            config = state.config_for(strategy)
        except Exception:
            continue
        basis = str(config.get(OrderExecutionModule.execution_price_basis, "open") or "open").lower()
        if basis not in bases:
            bases.append(basis)
    return tuple(bases or ("open",))


def order_market_snapshot_at(
    state,
    timestamp: pd.Timestamp,
    *,
    price_timestamp: pd.Timestamp | None = None,
    bases: tuple[str, ...] = ("open",),
) -> dict[str, dict[Any, float]]:
    """Minimal ORDER snapshot.

    ORDER handling consumes two distinct market-data views: event-time causal
    close for ledger/equity valuation, and the selected execution price basis
    at each order's price timestamp. Building the full market snapshot for
    every ORDER event scans settlement/etc. tables that do not affect the
    current order policy.
    """
    store = market_data_store_for(state)
    normalized_bases = tuple(dict.fromkeys(str(basis).lower() for basis in bases if basis))
    basis_timestamp = price_timestamp if price_timestamp is not None else timestamp
    cache_key = (
        "order",
        normalized_bases,
        _event_lookup_cache_key(timestamp),
        _event_lookup_cache_key(basis_timestamp),
    )
    cached = store.market_snapshot_cache.get(cache_key)
    if cached is not None:
        return cached
    snapshot: dict[str, dict[Any, float]] = {"close": current_prices_at(state, timestamp)}
    tables = market_price_tables_for(state)
    for basis in (*normalized_bases, "upper_limit", "lower_limit"):
        if basis == "close":
            continue
        table = tables.get(basis) if isinstance(tables, dict) else None
        if isinstance(table, pd.DataFrame) and not table.empty:
            values = _table_values_at_cached(state, table, basis_timestamp, asof=True)
            if values:
                snapshot[basis] = values
    store.market_snapshot_cache[cache_key] = snapshot
    return snapshot


def signal_market_snapshot_at(state, timestamp: pd.Timestamp) -> dict[str, dict[Any, float]]:
    """Minimal SIGNAL snapshot.

    Signal-time flows consume the causal close view for valuation/membership,
    exact observed close for orderability, volume for liquidity caps, and limit
    fields for tradable status. Other price bases are only needed by
    BAR/ORDER/LEDGER policies.
    """
    store = market_data_store_for(state)
    cache_key = ("signal", _event_lookup_cache_key(timestamp))
    cached = store.market_snapshot_cache.get(cache_key)
    if cached is not None:
        return cached
    snapshot: dict[str, dict[Any, float]] = {"close": current_prices_at(state, timestamp)}
    close_table = None
    tables = market_price_tables_for(state)
    if isinstance(tables, dict):
        candidate = tables.get("close")
        if isinstance(candidate, pd.DataFrame) and not candidate.empty:
            close_table = candidate
    if close_table is None:
        candidate = raw_prices_table_for(state)
        if isinstance(candidate, pd.DataFrame) and not candidate.empty:
            close_table = candidate
    if isinstance(close_table, pd.DataFrame) and not close_table.empty:
        exact_close = _table_values_at_cached(state, close_table, timestamp, asof=False)
        snapshot["tradable_close"] = exact_close
    for basis in ("upper_limit", "lower_limit"):
        table = tables.get(basis) if isinstance(tables, dict) else None
        if isinstance(table, pd.DataFrame) and not table.empty:
            values = _table_values_at_cached(state, table, timestamp, asof=True)
            if values:
                snapshot[basis] = values
    volume = current_volume_at(state, timestamp)
    if volume:
        snapshot["volume"] = volume
    store.market_snapshot_cache[cache_key] = snapshot
    return snapshot


def ledger_market_snapshot_at(state, timestamp: pd.Timestamp) -> dict[str, dict[Any, float]]:
    """Minimal LEDGER snapshot.

    Ledger lifecycle flows consume close for valuation and settlement when
    available for daily mark-to-market/margin checks. Tradability, volume and
    execution bases are irrelevant here and are intentionally not loaded.
    """
    store = market_data_store_for(state)
    cache_key = ("ledger", _event_lookup_cache_key(timestamp))
    cached = store.market_snapshot_cache.get(cache_key)
    if cached is not None:
        return cached
    snapshot: dict[str, dict[Any, float]] = {"close": current_prices_at(state, timestamp)}
    tables = market_price_tables_for(state)
    settlement = tables.get("settlement") if isinstance(tables, dict) else None
    if isinstance(settlement, pd.DataFrame) and not settlement.empty:
        values = _table_values_at_cached(state, settlement, timestamp, asof=True)
        if values:
            snapshot["settlement"] = values
    store.market_snapshot_cache[cache_key] = snapshot
    return snapshot


def _set_current_historical_fields(state, ctx) -> None:
    if _inert_margin_check_batch(state, ctx):
        ctx.set(MarketDataModule.current_historical_fields, {})
        return
    base_fields = current_historical_fields_at(state, ctx.timestamp)
    ctx.set(MarketDataModule.current_historical_fields, base_fields)
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        ledger = state.ledger_for_strategy(strategy)
        ledger_config = state.ledger_config_for(ledger)
        fields = _historical_fields_for_strategy(
            base_fields,
            config,
            ctx.timestamp,
            ledger_config=ledger_config,
        )
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
    *,
    ledger_config=None,
) -> dict[Any, dict[str, object]]:
    if engine_mode_for(strategy_config) != "custom":
        return base_fields
    if not _custom_historical_fields_enabled(strategy_config, ledger_config):
        return base_fields
    return apply_custom_product_fields(base_fields, strategy_config, timestamp)


def _custom_historical_fields_enabled(strategy_config, ledger_config=None) -> bool:
    from tools.testers.backtest.modules.fee import _resolve_fee_mode
    from tools.testers.backtest.modules.margin import _resolve_margin_mode
    from tools.testers.backtest.modules.trading_rule import _effective_accounting_mode

    return (
        _resolve_fee_mode(strategy_config, ledger_config) == "custom"
        or _resolve_margin_mode(strategy_config, ledger_config) == "custom"
        or _effective_accounting_mode(strategy_config, ledger_config) == "Custom"
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
    return _table_values_at_cached(state, table, timestamp, asof=True)


def current_market_snapshot_at(state, timestamp: pd.Timestamp) -> dict[str, dict[Any, float]]:
    """Return the complete market observation snapshot for an event timestamp.

    ``close`` is the legacy no-lookahead valuation view and is ffilled through
    gaps. Other price bases come from the raw basis tables at/as-of the event
    timestamp. Volume is not ffilled: a missing row means no observed volume
    for that event bar. Settlement/pre-settlement are included when the data
    source exposes them; daily settlement flows are responsible for only using
    them on ledger-notice timestamps registered after a trading day's final bar.
    """
    store = market_data_store_for(state)
    cache_key = _event_lookup_cache_key(timestamp)
    cached = store.market_snapshot_cache.get(cache_key)
    if cached is not None:
        return cached
    snapshot: dict[str, dict[Any, float]] = {"close": current_prices_at(state, timestamp)}
    for basis, table in market_price_tables_for(state).items():
        if basis == "close" or not isinstance(table, pd.DataFrame) or table.empty:
            continue
        values = _table_values_at_cached(state, table, timestamp, asof=True)
        if values:
            snapshot[basis] = values
    for column, table in factor_field_tables_for(state).items():
        if not isinstance(table, pd.DataFrame) or table.empty:
            continue
        values = _table_values_at_cached(state, table, timestamp, asof=True)
        if values:
            snapshot[column] = values
    volume = current_volume_at(state, timestamp)
    if volume:
        snapshot["volume"] = volume
    term_curves = _term_structure_curves_for_snapshot(snapshot, timestamp)
    if term_curves:
        snapshot["TERM_STRUCTURE"] = term_curves
    store.market_snapshot_cache[cache_key] = snapshot
    return snapshot


def market_snapshot_for_index_key(state, index_key: object) -> dict[str, dict[Any, float]]:
    """Return a market snapshot for an exact original market-data row key."""
    store = market_data_store_for(state)
    cache_key = ("index_key", repr(index_key))
    cached = store.market_snapshot_cache.get(cache_key)
    if cached is not None:
        return cached
    close_table = current_prices_table_for(state)
    if close_table is None:
        return {}
    snapshot: dict[str, dict[Any, float]] = {"close": _table_values_at_index_key(close_table, index_key)}
    for basis, table in market_price_tables_for(state).items():
        if basis == "close" or not isinstance(table, pd.DataFrame) or table.empty:
            continue
        values = _table_values_at_index_key(table, index_key)
        if values:
            snapshot[basis] = values
    for column, table in factor_field_tables_for(state).items():
        if not isinstance(table, pd.DataFrame) or table.empty:
            continue
        values = _table_values_at_index_key(table, index_key)
        if values:
            snapshot[column] = values
    volume_table = volume_table_for(state)
    if isinstance(volume_table, pd.DataFrame) and not volume_table.empty:
        values = _table_values_at_index_key(volume_table, index_key)
        if values:
            snapshot["volume"] = values
    term_curves = _term_structure_curves_for_snapshot(snapshot, _trading_day_from_index_key(index_key))
    if term_curves:
        snapshot["TERM_STRUCTURE"] = term_curves
    store.market_snapshot_cache[cache_key] = snapshot
    return snapshot


def _term_structure_curves_for_snapshot(
    snapshot: dict[str, dict[Any, Any]],
    trading_day: Any,
) -> dict[Any, pd.DataFrame]:
    products = snapshot.get("close", {}) or {}
    curves: dict[Any, pd.DataFrame] = {}
    day = _normalize_term_structure_trading_day(trading_day)
    for product in products:
        supports = getattr(product, "supports_term_structure", None)
        if callable(supports) and not supports():
            continue
        getter = getattr(product, "get_term_structure", None)
        if not callable(getter):
            continue
        try:
            curve = getter(day)
        except Exception:
            continue
        if isinstance(curve, pd.DataFrame) and not curve.empty:
            if TERM_RANK_COL in curve.columns:
                curve = curve.sort_values(TERM_RANK_COL)
            curves[product] = curve.reset_index(drop=True)
    return curves


def _normalize_term_structure_trading_day(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tz is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _trading_day_from_index_key(index_key: object) -> pd.Timestamp:
    if isinstance(index_key, tuple):
        for part in index_key:
            try:
                return _normalize_term_structure_trading_day(part)
            except Exception:
                continue
    return _normalize_term_structure_trading_day(index_key)


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


def _table_values_at_cached(state, table: pd.DataFrame, timestamp: pd.Timestamp, *, asof: bool) -> dict[Any, float]:
    store = market_data_store_for(state)
    cache_key = (id(table), bool(asof), _event_lookup_cache_key(timestamp))
    cached = store.table_values_cache.get(cache_key)
    if cached is not None:
        return cached
    index_entry = store.table_event_index_cache.get(id(table))
    if index_entry is None or index_entry[0] is not table.index:
        locator = TableRowLocator.for_table(table)
        store.table_event_index_cache[id(table)] = (table.index, locator)
    else:
        locator = index_entry[1]
    values = _table_values_at(table, timestamp, asof=asof, locator=locator)
    store.table_values_cache[cache_key] = values
    return values


def _table_values_at(
    table: pd.DataFrame,
    timestamp: pd.Timestamp,
    *,
    asof: bool,
    locator: TableRowLocator | None = None,
) -> dict[Any, float]:
    try:
        if locator is not None:
            row = locator.row_values_at(table, timestamp, asof=asof)
        else:
            row = row_at(table, timestamp, asof=asof)
    except KeyError:
        return {}
    return _numeric_row_values(table.columns, row)


def _table_values_at_index_key(table: pd.DataFrame, index_key: object) -> dict[Any, float]:
    try:
        row = row_at_index_key(table, index_key)
    except KeyError:
        return {}
    return _numeric_row_values(table.columns, row)


def _numeric_row_values(columns: pd.Index, row: pd.Series | np.ndarray) -> dict[Any, float]:
    raw = row if isinstance(row, np.ndarray) else row.to_numpy(copy=False)
    missing = pd.isna(raw)
    return {
        product: float(cast(Any, value))
        for product, value, is_missing in zip(columns, raw, missing, strict=True)
        if not bool(is_missing)
    }


def current_volume_at(state, timestamp: pd.Timestamp) -> dict:
    """Look up this bar's traded volume per product — no ffill (a gap means
    zero volume traded, not "carry the last observed volume forward")."""
    table = volume_table_for(state)
    if table is None:
        return {}
    return _table_values_at_cached(state, table, timestamp, asof=False)


def current_historical_fields_at(state, timestamp: pd.Timestamp) -> dict[Any, dict[str, object]]:
    """按事件时间查当前历史字段。

    MarketDataModule 只消费公共 FieldHistoryProvider，不关心字段来自 Guosen、
    OpenCTP 还是未来别的数据源。严格真实数据模式下，缺产品/缺交易日/缺字段会
    由 provider 直接抛出 MissingHistoricalField 或 MissingTradingDay。
    """
    store = market_data_store_for(state)
    cache_key = _event_lookup_cache_key(timestamp)
    cached = store.historical_fields_cache.get(cache_key)
    if cached is not None:
        return cached
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
    
    # Primary path: field_state_store (event-driven).  The state is stable
    # between FIELD_CHANGE events, so do not rebuild the product mapping for
    # every unique LEDGER timestamp.  Keep the timestamp cache above for
    # legacy frame/provider paths where values are genuinely time-dependent.
    if store.field_state_store:
        cached_state = store.field_state_resolved_cache
        if (
            cached_state is not None
            and cached_state[0] == store.field_state_generation
            and cached_state[1] == field_names
            and cached_state[2] is table
        ):
            resolved = cached_state[3]
            store.historical_fields_cache[cache_key] = resolved
            return resolved
        result: dict[Any, dict[str, object]] = {}
        for inst in instruments:
            inst_name = str(getattr(inst, "name", inst) or "")
            result[inst] = store.field_state_store.get(inst_name, {})
        resolved = _apply_exchange_rule_defaults(state, result, instruments, field_names, timestamp)
        store.field_state_resolved_cache = (
            store.field_state_generation,
            field_names,
            table,
            resolved,
        )
        store.historical_fields_cache[cache_key] = resolved
        return resolved
    
    # Fallback: query FieldHistory per product (legacy path, no pre-loaded frames).
    frames = store.historical_field_frames
    if isinstance(frames, dict):
        frame_result = _historical_fields_at_from_frames(
            frames,
            instruments,
            timestamp,
            column_cache=store.historical_field_frame_column_cache,
            column_map_cache=store.historical_field_frame_column_map_cache,
            row_cache=store.historical_field_frame_row_cache,
            index_cache=store.historical_field_frame_index_cache,
            values_cache=store.historical_field_frame_values_cache,
        )
        resolved = _apply_exchange_rule_defaults(state, frame_result, instruments, field_names, timestamp)
        _record_latest_available_historical_field_warnings(
            state,
            instruments,
            field_names,
            timestamp,
            provider=provider,
            resolver=resolver,
            policy=policy,
        )
        store.historical_fields_cache[cache_key] = resolved
        return resolved
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
    resolved = _apply_exchange_rule_defaults(state, resolved_result, instruments, field_names, timestamp)
    _record_latest_available_historical_field_warnings(
        state,
        instruments,
        field_names,
        timestamp,
        provider=provider,
        resolver=resolver,
        policy=policy,
    )
    store.historical_fields_cache[cache_key] = resolved
    return resolved


def _record_latest_available_historical_field_warnings(
    state,
    instruments: list[Any],
    field_names: tuple[object, ...],
    timestamp: pd.Timestamp,
    *,
    provider: FieldHistoryProvider,
    resolver: TradingDayResolver,
    policy: str,
) -> None:
    if str(policy) != HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value:
        return
    store = market_data_store_for(state)
    for instrument in instruments:
        instrument_name = str(getattr(instrument, "name", instrument) or "")
        for raw_field in field_names:
            field = str(raw_field)
            cache_key = (instrument_name, field, _event_lookup_cache_key(pd.Timestamp(timestamp)))
            if cache_key in store.historical_field_latest_available_warning_keys:
                continue
            store.historical_field_latest_available_warning_keys.add(cache_key)
            try:
                provider.resolve_at(
                    instrument,
                    field,
                    timestamp,
                    trading_day_resolver=resolver,
                    fallback=HistoricalFieldFallbackPolicy.STRICT_HISTORICAL,
                )
                continue
            except HistoricalFieldLookupError:
                pass
            try:
                resolved = provider.resolve_at(
                    instrument,
                    field,
                    timestamp,
                    trading_day_resolver=resolver,
                    fallback=HistoricalFieldFallbackPolicy.LATEST_AVAILABLE,
                )
            except HistoricalFieldLookupError:
                continue
            if not resolved.approximated:
                continue
            _record_latest_available_historical_field_warning(state, instrument, timestamp, field, resolved)


def _record_latest_available_historical_field_warning(
    state,
    product: Any,
    timestamp: pd.Timestamp,
    field_name: str,
    resolved: Any,
) -> None:
    from tools.testers.backtest.modules.runtime_info import record_runtime_fallback_interval

    effective = getattr(resolved, "effective_timestamp", None) or getattr(resolved, "effective_trading_day", None)
    value = getattr(resolved, "value", None)
    notice = getattr(resolved, "source_notice_id", "") or getattr(resolved, "source_key", "")
    record_runtime_fallback_interval(
        state,
        code="historical_field_latest_available_backfill",
        type="历史交易字段",
        status="已向前回填",
        product=product,
        timestamp=timestamp,
        source=field_name,
        fallback=f"latest_available:{effective}:{value}",
        reason="查询时间早于该字段首条权威历史记录，auto 模式使用最近可得规则",
        extra={
            "field_name": field_name,
            "effective": str(effective),
            "value": value,
            "source_notice_id": str(notice),
        },
    )


def _event_lookup_cache_key(timestamp: pd.Timestamp) -> Any:
    # Native event ordering uses nanosecond epsilons to keep SIGNAL/ORDER/LEDGER
    # causally ordered on the same bar. Market snapshots and historical rule
    # fields are bar/effective-time states, so those epsilon variants should hit
    # the same lookup cache entry instead of repeating expensive table joins.
    ts = pd.Timestamp(timestamp)
    return ((ts.value // 1_000) * 1_000, str(ts.tz))


def historical_field_frames_for_market_data(
    products: list[Any],
    index: pd.Index,
    *,
    provider: FieldHistoryProvider,
    trading_day_resolver: TradingDayResolver,
    field_names: tuple[object, ...],
    policy: str,
) -> dict[str, pd.DataFrame]:
    cache_key = _historical_fields_frame_cache_key(products, index, field_names, policy, provider)
    cached = _HISTORICAL_FIELDS_FRAME_CACHE.get(cache_key)
    if cached is not None:
        _HISTORICAL_FIELDS_FRAME_CACHE.move_to_end(cache_key)
        return cached
    frames = historical_fields_frame_for_products(
        products,
        index,
        provider=provider,
        trading_day_resolver=trading_day_resolver,
        field_names=field_names,
        fallback=policy,
    )
    return _store_historical_fields_frame_cache(cache_key, frames)


_HISTORICAL_FIELDS_FRAME_CACHE_MAX = 8
_HISTORICAL_FIELDS_FRAME_CACHE: OrderedDict[Any, dict[str, pd.DataFrame]] = OrderedDict()


def _historical_fields_frame_cache_key(
    products: list[Any],
    index: pd.Index,
    field_names: tuple[object, ...],
    policy: str,
    provider: FieldHistoryProvider,
) -> tuple[Any, ...]:
    timestamps = signal_timestamps(pd.DataFrame(index=index))
    timestamp_ns = tuple(int(pd.Timestamp(value).value) for value in timestamps)
    product_names = tuple(str(getattr(product, "name", product)) for product in products)
    return (
        tuple(product_names),
        len(timestamp_ns),
        timestamp_ns[0] if timestamp_ns else None,
        timestamp_ns[-1] if timestamp_ns else None,
        hash(timestamp_ns),
        tuple(str(field_name) for field_name in field_names),
        str(policy),
        id(provider),
    )


def _store_historical_fields_frame_cache(key: Any, value: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    _HISTORICAL_FIELDS_FRAME_CACHE[key] = value
    _HISTORICAL_FIELDS_FRAME_CACHE.move_to_end(key)
    while len(_HISTORICAL_FIELDS_FRAME_CACHE) > _HISTORICAL_FIELDS_FRAME_CACHE_MAX:
        _HISTORICAL_FIELDS_FRAME_CACHE.popitem(last=False)
    return value


@lru_cache(maxsize=1)
def _runtime_field_history_provider() -> FieldHistoryProvider:
    from sources.FieldHistory.views.Unified import load_unified_provider

    return load_unified_provider()


def _historical_fields_at_from_frames(
    frames: dict[str, pd.DataFrame],
    instruments: list[Any],
    timestamp: pd.Timestamp,
    *,
    column_cache: dict[tuple[str, tuple[str, ...]], object | None] | None = None,
    column_map_cache: dict[Any, list[tuple[Any, int]]] | None = None,
    row_cache: dict[Any, dict[Any, dict[str, object]]] | None = None,
    index_cache: dict[int, tuple[pd.Index, Any]] | None = None,
    values_cache: dict[int, tuple[pd.DataFrame, Any]] | None = None,
) -> dict[Any, dict[str, object]]:
    row_positions = _historical_field_frame_row_positions(
        frames,
        timestamp,
        index_cache=index_cache,
    )
    product_names = tuple(str(getattr(instrument, "name", instrument)) for instrument in instruments)
    cache_key = (product_names, tuple(row_positions.items()))
    if row_cache is not None:
        cached = row_cache.get(cache_key)
        if cached is not None:
            return cached
    result: dict[Any, dict[str, object]] = {instrument: {} for instrument in instruments}
    for field_name, frame in frames.items():
        # FieldHistoryProvider stores its frames tz-naive (it normalises
        # every lookup key via _normalise_timestamp_key); event timestamps
        # here are tz-aware, so align via DataIndex before indexing. These
        # fields are effective-time states, so an ORDER event shifted by a
        # causal epsilon should read the latest rule row at or before it.
        row_pos = row_positions.get(str(field_name))
        if row_pos is None:
            continue
        values = _historical_field_frame_values(frame, values_cache=values_cache)
        row_values = values[row_pos]
        for instrument, column_pos in _historical_field_frame_column_positions(
            frame,
            instruments,
            field_name=str(field_name),
            column_cache=column_cache,
            column_map_cache=column_map_cache,
        ):
            result[instrument][str(field_name)] = row_values[column_pos]
    if row_cache is not None:
        row_cache[cache_key] = result
    return result


def _historical_field_frame_column_positions(
    frame: pd.DataFrame,
    instruments: list[Any],
    *,
    field_name: str,
    column_cache: dict[tuple[str, tuple[str, ...]], object | None] | None = None,
    column_map_cache: dict[Any, list[tuple[Any, int]]] | None = None,
) -> list[tuple[Any, int]]:
    cache_key = (field_name, id(frame), tuple(id(instrument) for instrument in instruments))
    if column_map_cache is not None:
        cached = column_map_cache.get(cache_key)
        if cached is not None:
            return cached
    positions: list[tuple[Any, int]] = []
    columns = frame.columns
    for instrument in instruments:
        column = _historical_field_frame_column_for(
            frame,
            instrument,
            field_name=field_name,
            column_cache=column_cache,
        )
        if column is None:
            continue
        column_pos = columns.get_loc(cast(Any, column))
        if isinstance(column_pos, slice):
            column_pos = column_pos.start
        if isinstance(column_pos, (list, tuple)):
            column_pos = column_pos[0]
        if hasattr(column_pos, "nonzero"):
            nonzero = column_pos.nonzero()[0]
            if len(nonzero) == 0:
                continue
            column_pos = int(nonzero[0])
        positions.append((instrument, int(column_pos)))
    if column_map_cache is not None:
        column_map_cache[cache_key] = positions
    return positions


def _historical_field_frame_values(
    frame: pd.DataFrame,
    *,
    values_cache: dict[int, tuple[pd.DataFrame, Any]] | None = None,
) -> Any:
    cache_key = id(frame)
    if values_cache is not None:
        cached = values_cache.get(cache_key)
        if cached is not None and cached[0] is frame:
            return cached[1]
    values = frame.to_numpy(copy=False)
    if values_cache is not None:
        values_cache[cache_key] = (frame, values)
    return values


def _historical_field_frame_row_positions(
    frames: dict[str, pd.DataFrame],
    timestamp: pd.Timestamp,
    *,
    index_cache: dict[int, tuple[pd.Index, Any]] | None = None,
) -> dict[str, int | None]:
    if not frames:
        return {}
    items = list(frames.items())
    first_index = items[0][1].index
    if all(frame.index is first_index or frame.index.equals(first_index) for _field, frame in items):
        lookup_timestamp = _historical_field_frame_lookup_timestamp(first_index, timestamp)
        row_pos = _historical_field_frame_asof_position(
            first_index,
            lookup_timestamp,
            index_cache=index_cache,
        )
        return {str(field_name): row_pos for field_name, _frame in items}
    row_positions: dict[str, int | None] = {}
    for field_name, frame in items:
        lookup_timestamp = _historical_field_frame_lookup_timestamp(frame.index, timestamp)
        row_positions[str(field_name)] = _historical_field_frame_asof_position(
            frame.index,
            lookup_timestamp,
            index_cache=index_cache,
        )
    return row_positions


def _historical_field_frame_lookup_timestamp(index: pd.Index, timestamp: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(timestamp)
    try:
        idx_tz = pd.DatetimeIndex(index).tz
    except (TypeError, ValueError):
        return DataIndex(index).tz_align(ts)
    if idx_tz is None:
        return ts.tz_localize(None) if ts.tzinfo is not None else ts
    if ts.tzinfo is None:
        return ts.tz_localize(idx_tz)
    if ts.tzinfo == idx_tz:
        return ts
    return ts.tz_convert(idx_tz)


def _apply_exchange_rule_defaults(
    state: Any,
    result: dict[Any, dict[str, object]],
    instruments: list[Any],
    field_names: tuple[object, ...],
    timestamp: pd.Timestamp,
) -> dict[Any, dict[str, object]]:
    normalized_field_names = tuple(str(field_name) for field_name in field_names)
    defaults_cache = market_data_store_for(state).exchange_rule_defaults_cache
    for instrument in instruments:
        values = result.setdefault(instrument, {})
        cache_key = (id(instrument), normalized_field_names)
        cached = defaults_cache.get(cache_key)
        if cached is not None and cached[0] is instrument:
            defaults = cached[1]
        else:
            defaults = exchange_rule_defaults_for_product(instrument, normalized_field_names)
            defaults_cache[cache_key] = (instrument, defaults)
        for field_name, value in defaults.items():
            key = str(field_name)
            if key not in values or _is_missing_exchange_rule_value(values.get(key)):
                values[key] = value
    return result


def _is_missing_exchange_rule_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        isna = cast(Any, pd.isna)
        return bool(isna(value))
    except (TypeError, ValueError):
        return False


def _historical_field_frame_asof_position(
    index: pd.Index,
    timestamp: pd.Timestamp,
    *,
    index_cache: dict[int, tuple[pd.Index, Any]] | None = None,
) -> int | None:
    if len(index) == 0:
        return None
    index_ns = _historical_field_frame_index_ns(index, index_cache=index_cache)
    pos = int(index_ns.searchsorted(timestamp.value, side="right") - 1)
    if pos < 0:
        return None
    return pos


def _historical_field_frame_index_ns(
    index: pd.Index,
    *,
    index_cache: dict[int, tuple[pd.Index, Any]] | None = None,
) -> Any:
    cache_key = id(index)
    if index_cache is not None:
        cached = index_cache.get(cache_key)
        if cached is not None and cached[0] is index:
            return cached[1]
    index_ns = cast(Any, pd.DatetimeIndex(pd.DatetimeIndex(index).astype("datetime64[ns]"))).asi8
    if index_cache is not None:
        index_cache[cache_key] = (index, index_ns)
    return index_ns


def _historical_field_frame_column_for(
    frame: pd.DataFrame,
    instrument: Any,
    *,
    field_name: str | None = None,
    column_cache: dict[tuple[str, tuple[str, ...]], object | None] | None = None,
) -> object | None:
    cache_key: tuple[str, tuple[str, ...]] | None = None
    if column_cache is not None and field_name is not None:
        cache_key = (field_name, tuple(sorted(_historical_field_product_keys(instrument))))
        if cache_key in column_cache:
            return column_cache[cache_key]
    candidates: list[object] = [instrument, str(instrument)]
    for attr_name in ("name", "symbol", "code"):
        attr = getattr(instrument, attr_name, None)
        if attr is not None:
            candidates.append(str(attr))
    for candidate in dict.fromkeys(candidates):
        if candidate in frame.columns:
            _store_historical_field_column_cache(column_cache, cache_key, candidate)
            return candidate
    _store_historical_field_column_cache(column_cache, cache_key, None)
    return None


def _store_historical_field_column_cache(
    column_cache: dict[tuple[str, tuple[str, ...]], object | None] | None,
    cache_key: tuple[str, tuple[str, ...]] | None,
    value: object | None,
) -> None:
    if column_cache is not None and cache_key is not None:
        column_cache[cache_key] = value


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
    lookup = _historical_fields_lookup_index(historical_fields)
    for key in product_keys:
        values = lookup.get(key)
        if isinstance(values, dict):
            return values
    return {}


_HISTORICAL_FIELD_PRODUCT_KEYS_CACHE_MAX = 4096
_HISTORICAL_FIELD_PRODUCT_KEYS_CACHE: OrderedDict[int, tuple[Any, tuple[str, ...]]] = OrderedDict()
_HISTORICAL_FIELDS_LOOKUP_CACHE_MAX = 2048
_HISTORICAL_FIELDS_LOOKUP_CACHE: OrderedDict[int, tuple[dict[Any, dict[str, object]], dict[str, dict[str, object]]]] = OrderedDict()


def _historical_field_product_keys(product: Any) -> frozenset[str]:
    if product is None:
        return frozenset()
    cache_key = id(product)
    cached = _HISTORICAL_FIELD_PRODUCT_KEYS_CACHE.get(cache_key)
    if cached is not None and cached[0] is product:
        _HISTORICAL_FIELD_PRODUCT_KEYS_CACHE.move_to_end(cache_key)
        return frozenset(cached[1])
    keys: set[str] = set()
    for value in (
        str(product),
        getattr(product, "name", None),
        getattr(product, "alias", None),
        getattr(product, "symbol", None),
        getattr(product, "code", None),
    ):
        if value is not None and str(value).strip():
            keys.add(str(value).strip())
    result = tuple(sorted(keys))
    _HISTORICAL_FIELD_PRODUCT_KEYS_CACHE[cache_key] = (product, result)
    _HISTORICAL_FIELD_PRODUCT_KEYS_CACHE.move_to_end(cache_key)
    while len(_HISTORICAL_FIELD_PRODUCT_KEYS_CACHE) > _HISTORICAL_FIELD_PRODUCT_KEYS_CACHE_MAX:
        _HISTORICAL_FIELD_PRODUCT_KEYS_CACHE.popitem(last=False)
    return frozenset(result)


def _historical_fields_lookup_index(
    historical_fields: dict[Any, dict[str, object]],
) -> dict[str, dict[str, object]]:
    cache_key = id(historical_fields)
    cached = _HISTORICAL_FIELDS_LOOKUP_CACHE.get(cache_key)
    if cached is not None and cached[0] is historical_fields:
        _HISTORICAL_FIELDS_LOOKUP_CACHE.move_to_end(cache_key)
        return cached[1]
    lookup: dict[str, dict[str, object]] = {}
    for instrument, values in historical_fields.items():
        if not isinstance(values, dict):
            continue
        for key in _historical_field_product_keys(instrument):
            lookup.setdefault(key, values)
    _HISTORICAL_FIELDS_LOOKUP_CACHE[cache_key] = (historical_fields, lookup)
    _HISTORICAL_FIELDS_LOOKUP_CACHE.move_to_end(cache_key)
    while len(_HISTORICAL_FIELDS_LOOKUP_CACHE) > _HISTORICAL_FIELDS_LOOKUP_CACHE_MAX:
        _HISTORICAL_FIELDS_LOOKUP_CACHE.popitem(last=False)
    return lookup


def contract_multiplier_from_fields(
    historical_fields: dict[Any, dict[str, object]] | None,
    product: Any,
    *,
    default: float = 1.0,
    state: Any | None = None,
    timestamp: Any | None = None,
) -> float:
    fields = historical_fields_for_product(historical_fields, product)
    return contract_multiplier_from_product_fields(
        fields,
        default=default,
        state=state,
        product=product,
        timestamp=timestamp,
    )


def contract_multiplier_from_product_fields(
    fields: dict[str, object] | None,
    *,
    default: float = 1.0,
    state: Any | None = None,
    product: Any | None = None,
    timestamp: Any | None = None,
) -> float:
    """Resolve ``VolumeMultiple`` from an already selected product row.

    Runtime hot paths often already selected the historical-field row to
    resolve another product rule.  Keeping that row as an explicit input
    avoids re-running the product-key lookup while preserving the same
    fallback audit behaviour as :func:`contract_multiplier_from_fields`.
    """
    fields = fields or {}
    value = fields.get("VolumeMultiple", default)
    if value in (None, ""):
        _record_contract_multiplier_fallback(state, product, timestamp, default, "字段为空")
        return default
    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        _record_contract_multiplier_fallback(state, product, timestamp, default, "字段无法转换为数字")
        return default
    if number != number:
        _record_contract_multiplier_fallback(state, product, timestamp, default, "字段为NaN")
        return default
    return number


def _record_contract_multiplier_fallback(
    state: Any | None,
    product: Any,
    timestamp: Any | None,
    default: float,
    reason: str,
) -> None:
    if state is None or timestamp is None:
        return
    from tools.testers.backtest.modules.runtime_info import record_runtime_fallback_interval

    record_runtime_fallback_interval(
        state,
        code="contract_multiplier_default_fallback",
        type="历史交易字段",
        status="已降级",
        product=product,
        timestamp=timestamp,
        source="VolumeMultiple",
        fallback=f"default:{default:g}",
        reason=reason,
    )


def contract_notional(
    price: float,
    quantity: float,
    historical_fields: dict[Any, dict[str, object]] | None,
    product: Any,
    *,
    product_fields: dict[str, object] | None = None,
) -> float:
    fields = (
        product_fields
        if product_fields is not None
        else historical_fields_for_product(historical_fields, product)
    )
    return float(quantity) * float(price) * contract_multiplier_from_product_fields(fields)
