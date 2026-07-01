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

from functools import lru_cache
from typing import Any, ClassVar, cast

import pandas as pd

from tools.data.types import DataColumn
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.custom_product import CustomProductModule, apply_custom_product_fields
from tools.testers.backtest.modules.engine import EngineModule, engine_mode_for
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
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
    data_source: ClassVar[FieldRef[str]] = FieldRef("data_source")
        # which raw data source the data-prep stage should load raw_prices/
        # volume/etc. from -- read by that upstream stage (via
        # strategy_config_builder), not by any Flow in this module itself
    frequency: ClassVar[FieldRef[str]] = FieldRef("frequency")
        # bar granularity of the underlying market data (distinct from
        # FactorSignalModule.signal_freq, which is how often the strategy
        # rebalances -- a strategy can rebalance daily on top of minute bars)

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
        "data_source": FieldDefinition(
            public=True, label="数据源", default="", control_template="select", tab="data_source",
            options=(("", "自动"),),
            chip_template="数据源: {value}",
            tab_label="数据源",
            tab_order=35,
        ),
        "frequency": FieldDefinition(
            public=True, label="Bar频率", default="", control_template="select", tab="frequency",
            options=(("", "自动"),),
            chip_template="Bar频率: {value}",
            tab_label="数据频率",
            tab_order=36,
        ),
    }

    check_market_data_coverage: ClassVar[Flow] = Flow(
        "check_market_data_coverage", inputs=(), outputs=(),
        phase=Phase.PRE_REPLAY, order=38,
        compute=lambda account, ctx: _check_market_data_coverage(account, ctx),
    )
    load_raw_market_data: ClassVar[Flow] = Flow(
        "load_raw_market_data", inputs=(EngineModule.engine_mode,), outputs=(
            raw_prices, lot_sizes, margin_ratio, settlement_price, volume, historical_field_provider,
        ),
        phase=Phase.PRE_REPLAY, order=40, after=(check_market_data_coverage,),
        compute=lambda account, ctx: _load_raw_market_data(account, ctx),
    )
    build_trading_day_resolver: ClassVar[Flow] = Flow(
        "build_trading_day_resolver", inputs=(raw_prices,), outputs=(trading_day_resolver,),
        phase=Phase.PRE_REPLAY, order=43, after=(load_raw_market_data,),
        compute=lambda account, ctx: _build_trading_day_resolver(account, ctx),
    )
    load_historical_fields: ClassVar[Flow] = Flow(
        "load_historical_fields", inputs=(raw_prices, trading_day_resolver), outputs=(historical_field_policy,),
        phase=Phase.PRE_REPLAY, order=44, after=(build_trading_day_resolver,),
        compute=lambda account, ctx: _load_historical_fields(account, ctx),
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
        "lookup_historical_fields_on_signal",
        inputs=(_fee_mode_ref, _margin_mode_ref, _accounting_mode_ref, CustomProductModule.custom_product_fields),
        outputs=(current_historical_fields,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=2,
        compute=lambda account, ctx: _set_current_historical_fields(account, ctx),
    )
    lookup_historical_fields_on_order: ClassVar[Flow] = Flow(
        "lookup_historical_fields_on_order",
        inputs=(_fee_mode_ref, _margin_mode_ref, _accounting_mode_ref, CustomProductModule.custom_product_fields),
        outputs=(current_historical_fields,),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=2,
        compute=lambda account, ctx: _set_current_historical_fields(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        check_market_data_coverage, load_raw_market_data, build_trading_day_resolver,
        load_historical_fields, causal_valuation,
        lookup_current_prices_on_bar, lookup_current_prices_on_signal,
        lookup_current_prices_on_order, lookup_volume_on_signal,
        lookup_historical_fields_on_signal, lookup_historical_fields_on_order,
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


def _market_data_request(account) -> dict[str, Any]:
    request = getattr(account, "market_data_request", None)
    raw = getattr(account, "raw_market_data", None)
    if isinstance(raw, dict) and raw.get("raw_prices") is not None:
        return {"raw_market_data": raw}
    if not isinstance(request, dict):
        return {}
    return request


def _check_market_data_coverage(account, ctx) -> None:
    request = _market_data_request(account)
    if "raw_market_data" in request:
        raw = request["raw_market_data"]
        account._market_data_series_by_product = {
            product: raw.get("raw_prices")[product]
            for product in getattr(raw.get("raw_prices"), "columns", [])
        }
        account._market_data_price_tables = raw.get("price_tables") or {"close": raw.get("raw_prices")}
        account._market_data_excluded_out_of_range = tuple(raw.get("excluded_out_of_range_products", ()))
        return
    products = _products_from_selection_context(account, ctx) or list(request.get("products") or ())
    start_dt = request.get("start_dt")
    end_dt = request.get("end_dt")
    missing_products: list[str] = []
    excluded_out_of_range: list[Any] = []
    load_plan: list[tuple[Any, Any]] = []
    for product in products:
        try:
            available_freqs = list(product.list_available_freqs())
            if not available_freqs:
                missing_products.append(str(getattr(product, "name", product)))
                continue
            current_freq = getattr(product, "current_freq", None)
            freq = cast(Any, current_freq if current_freq in available_freqs else available_freqs[0])
            load_plan.append((product, freq))
        except (ValueError, KeyError):
            if _product_outside_run_window(product, start_dt, end_dt):
                excluded_out_of_range.append(product)
            else:
                missing_products.append(str(getattr(product, "name", product)))
    if missing_products:
        _raise_missing_market_data(missing_products, start_dt, end_dt)
    account._market_data_load_plan = load_plan
    account._market_data_excluded_out_of_range = tuple(_dedupe_products(excluded_out_of_range))
    _record_excluded_out_of_range_products(account, account._market_data_excluded_out_of_range)


def _products_from_selection_context(account, ctx) -> list[Any]:
    products: list[Any] = []
    for strategy in account.strategy_configs:
        for product in ctx.get_for(ProductSelectionModule.products, strategy, frozenset()):
            if product not in products:
                products.append(product)
    return products


def _load_raw_market_data(account, ctx) -> None:
    request = _market_data_request(account)
    if "raw_market_data" in request:
        raw = request["raw_market_data"]
        _publish_raw_market_data(account, ctx, raw)
        return
    start_dt = request.get("start_dt")
    end_dt = request.get("end_dt")
    warmup_window = request.get("warmup_window")
    series_by_product: dict[Any, pd.Series] = {}
    price_columns = (
        ("open", DataColumn.OPEN.name),
        ("high", DataColumn.HIGH.name),
        ("low", DataColumn.LOW.name),
        ("close", DataColumn.CLOSE.name),
        ("vwap", DataColumn.VWAP.name),
    )
    price_series_by_basis: dict[str, dict[Any, pd.Series]] = {
        basis: {} for basis, _column in price_columns
    }
    missing_products: list[str] = []
    for product, freq in getattr(account, "_market_data_load_plan", ()):
        try:
            data_view = getattr(product, freq.name)
            df = data_view.get_and_adjust_cols(
                [column for _basis, column in price_columns],
                copy=False,
                start_dt=start_dt,
                end_dt=end_dt,
                warmup_window=warmup_window,
            )
        except (ValueError, KeyError):
            if _product_outside_run_window(product, start_dt, end_dt):
                excluded: list[Any] = list(getattr(account, "_market_data_excluded_out_of_range", ()))
                excluded.append(product)
                account._market_data_excluded_out_of_range = tuple(_dedupe_products(excluded))
            else:
                missing_products.append(str(getattr(product, "name", product)))
            continue
        if df.empty or DataColumn.CLOSE.name not in df.columns:
            if _product_outside_run_window(product, start_dt, end_dt):
                excluded: list[Any] = list(getattr(account, "_market_data_excluded_out_of_range", ()))
                excluded.append(product)
                account._market_data_excluded_out_of_range = tuple(_dedupe_products(excluded))
            else:
                missing_products.append(str(getattr(product, "name", product)))
            continue
        series_by_product[product] = df[DataColumn.CLOSE.name]
        for basis, column in price_columns:
            if column in df.columns:
                price_series_by_basis[basis][product] = df[column]
    if missing_products:
        _raise_missing_market_data(missing_products, start_dt, end_dt)
    raw_prices = pd.DataFrame(series_by_product) if series_by_product else pd.DataFrame()
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
        "historical_field_provider": load_market_rule_field_provider(),
        "historical_field_policy": request.get("policy", "latest_available"),
        "historical_field_names": _required_market_rule_field_names(account),
        "included_products": tuple(series_by_product.keys()),
        "excluded_out_of_range_products": tuple(getattr(account, "_market_data_excluded_out_of_range", ())),
    }
    _publish_raw_market_data(account, ctx, raw)


def _build_trading_day_resolver(account, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    provider = ctx.get(MarketDataModule.historical_field_provider)
    if provider is None:
        ctx.set(MarketDataModule.trading_day_resolver, None)
        account.trading_day_resolver = None
        return
    if raw_prices is None or raw_prices.empty:
        ctx.set(MarketDataModule.trading_day_resolver, None)
        account.trading_day_resolver = None
        return
    resolver = build_trading_day_resolver_from_market_data(raw_prices)
    ctx.set(MarketDataModule.trading_day_resolver, resolver)
    account.trading_day_resolver = resolver


def _load_historical_fields(account, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    resolver = ctx.get(MarketDataModule.trading_day_resolver)
    raw_policy = _market_data_request(account).get("policy", getattr(account, "historical_field_policy", None))
    policy = _historical_field_policy_for_engine(account, raw_policy)
    ctx.set(MarketDataModule.historical_field_policy, policy)
    account.historical_field_policy = policy
    field_names = tuple(getattr(account, "historical_field_names", _MARKET_RULE_FIELD_NAMES))
    account.historical_field_names = field_names
    if raw_prices is None or raw_prices.empty or resolver is None:
        account.historical_field_frames = None
        return
    account.historical_field_frames = historical_field_frames_for_market_data(
        list(raw_prices.columns),
        signal_timestamps(raw_prices),
        provider=cast(FieldHistoryProvider, getattr(account, "historical_field_provider")),
        trading_day_resolver=resolver,
        field_names=field_names,
        policy=policy,
    )


def _publish_raw_market_data(account, ctx, raw: dict[str, Any]) -> None:
    ctx.set(MarketDataModule.raw_prices, raw.get("raw_prices"))
    ctx.set(MarketDataModule.lot_sizes, raw.get("lot_sizes", {}))
    ctx.set(MarketDataModule.margin_ratio, raw.get("margin_ratio", {}))
    ctx.set(MarketDataModule.settlement_price, raw.get("settlement_price"))
    ctx.set(MarketDataModule.volume, raw.get("volume"))
    ctx.set(MarketDataModule.historical_field_provider, raw.get("historical_field_provider"))
    raw_policy = raw.get("historical_field_policy")
    account.raw_prices_table = raw.get("raw_prices")
    account.market_price_tables = raw.get("price_tables") or {"close": raw.get("raw_prices")}
    account.historical_field_provider = raw.get("historical_field_provider")
    included_products = raw.get("included_products")
    account.backtest_included_products = (
        frozenset(included_products) if included_products is not None else None
    )
    account.backtest_excluded_out_of_range_products = tuple(raw.get("excluded_out_of_range_products", ()))
    _record_excluded_out_of_range_products(account, account.backtest_excluded_out_of_range_products)
    account.historical_field_names = tuple(raw.get("historical_field_names", ()))
    account.volume_table = raw.get("volume")  # not ffill'd -- a gap means zero
                                                # traded volume, not "carry the last
                                                # observed value forward"


def _record_excluded_out_of_range_products(account, products: tuple[Any, ...]) -> None:
    if not products:
        return
    seen_sets = getattr(account, "_runtime_info_excluded_product_sets", None)
    if not isinstance(seen_sets, list):
        seen_sets = []
        account._runtime_info_excluded_product_sets = seen_sets
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
    runtime_rows = getattr(account, "runtime_info_rows", None)
    if isinstance(runtime_rows, list):
        runtime_rows.append(row)
    sink = getattr(account, "runtime_info_sink", None)
    emit = getattr(sink, "emit_runtime_info", None)
    if callable(emit):
        emit(row["message"], level=row["level"], code=row["code"], details=row["details"], row=row)


def _dedupe_products(products: list[Any]) -> list[Any]:
    result: list[Any] = []
    for product in products:
        if product not in result:
            result.append(product)
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
    coverage = _product_data_coverage(product)
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


def _historical_field_policy_for_engine(account, raw_policy: object | None) -> str:
    mode = "auto"
    configs = getattr(account, "strategy_configs", None)
    if configs:
        mode = engine_mode_for(next(iter(configs.values())))
    if mode == "exact":
        return str(HistoricalFieldFallbackPolicy.STRICT_HISTORICAL.value)
    if mode in {"auto", "custom"}:
        return str(raw_policy or HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value)
    return str(raw_policy or HistoricalFieldFallbackPolicy.LATEST_AVAILABLE.value)


def _required_market_rule_field_names(account) -> tuple[str, ...]:
    fields: list[str] = list(_MARKET_RULE_FIELD_NAMES)
    fee_ref = FieldRef("fee_mode", owner="FeeModule")
    margin_ref = FieldRef("margin_mode", owner="MarginModule")
    allocation_ref = FieldRef("allocation_policy", owner="GroupMembershipModule")
    for config in getattr(account, "strategy_configs", {}).values():
        fee_mode = str(config.get(fee_ref, "auto") or "auto")
        if fee_mode not in {"zero", "none"}:
            fields.extend(TRANSACTION_FEE_FIELD_NAMES)
        margin_mode = str(config.get(margin_ref, "auto") or "auto")
        allocation = str(config.get(allocation_ref, "") or "")
        if margin_mode not in {"none", "zero"} or allocation == "equal_margin":
            fields.extend(_MARGIN_FIELD_NAMES)
    return tuple(dict.fromkeys(fields))


def _causal_valuation(account, ctx) -> None:
    raw_prices: pd.DataFrame = ctx.get(MarketDataModule.raw_prices)
    account.current_prices_table = raw_prices.ffill()


def _set_current_historical_fields(account, ctx) -> None:
    base_fields = current_historical_fields_at(account, ctx.timestamp)
    ctx.set(MarketDataModule.current_historical_fields, base_fields)
    for strategy in ctx.active_strategies:
        config = account.config_for(strategy)
        ctx.set_for(
            MarketDataModule.current_historical_fields,
            strategy,
            _historical_fields_for_strategy(base_fields, config, ctx.timestamp),
        )


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
    return {product: float(cast(Any, row[product])) for product in table.columns}


def current_volume_at(account, timestamp: pd.Timestamp) -> dict:
    """Look up this bar's traded volume per product — no ffill (a gap means
    zero volume traded, not "carry the last observed volume forward")."""
    table = account.volume_table
    if table is None:
        return {}
    row = row_at(table, timestamp)
    return {product: float(cast(Any, row[product])) for product in table.columns}


def current_historical_fields_at(account, timestamp: pd.Timestamp) -> dict[Any, dict[str, object]]:
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
    result: dict[Any, dict[str, object]] = {}
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
        result[instrument] = values
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
        # here are tz-aware, so align via DataIndex before indexing.
        lookup_timestamp = DataIndex(frame.index).tz_align(timestamp)
        if lookup_timestamp not in frame.index:
            continue
        row = frame.loc[lookup_timestamp]
        for instrument in instruments:
            column = _historical_field_frame_column_for(frame, instrument)
            if column is not None:
                result[instrument][str(field_name)] = row[str(column)]
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
    return {}


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
