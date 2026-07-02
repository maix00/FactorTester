"""Term structure expansion, rollover, and delivery-force-close modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, ClassVar, cast

import pandas as pd

from tools.data.types.time_index import DataIndex
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.run_window import RunWindowModule, run_window_envelope_for_state
from tools.testers.backtest.modules.target import TargetStrategyModule


_POSITIONS_REF = FieldRef("positions", owner="LedgerModule")
_TARGET_WEIGHTS_REF = TargetStrategyModule.target_weights
_LIFECYCLE_TS_KEYS = (
    "auto_close_ts",
    "last_trade_ts",
    "expire_ts",
    "first_notice_ts",
    "notice_ts",
    "delivery_ts",
    "maturity_ts",
)
_LIFECYCLE_DATE_KEYS = (
    "auto_close_date",
    "last_trade_date",
    "expire_date",
    "first_notice_date",
    "notice_date",
    "delivery_date",
    "maturity_date",
)


@dataclass
class TermStructureStore:
    expanded_contracts: dict[Any, Any] = field(default_factory=dict)
    contract_metadata: dict[Any, Any] = field(default_factory=dict)
    target_mapping: dict[Any, dict[str, Any]] = field(default_factory=dict)
    notices: list[dict[str, Any]] = field(default_factory=list)

    def set_expansion(self, contracts: dict[Any, Any], metadata: dict[Any, Any]) -> None:
        self.expanded_contracts = contracts
        self.contract_metadata = metadata

    def record_target_mapping(self, strategy: Any, timestamp: Any, mapping: dict[str, str | None]) -> None:
        self.target_mapping.setdefault(strategy, {})[str(timestamp)] = mapping

    def record_notice(self, payload: dict[str, Any]) -> None:
        self.notices.append(payload)


class TermStructureExpandModule(ExecutableModule):
    """Resolve term-structure metadata for the run window.

    The abstract product/continuous series is still the object used for
    coverage checks and factor signal generation.  Concrete contracts are a
    separate window-intersection view used by execution constraints, delivery
    guards, and term-structure factor helpers.
    """

    key: ClassVar[str] = "term_structure_expand"
    label: ClassVar[str] = "合约展开"
    expanded_contracts: ClassVar[FieldRef[dict[Any, frozenset]]] = FieldRef("expanded_contracts")
    contract_metadata: ClassVar[FieldRef[dict[Any, tuple[dict[str, Any], ...]]]] = FieldRef("contract_metadata")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "expanded_contracts": FieldDefinition(public=False),
        "contract_metadata": FieldDefinition(public=False),
    }

    expand_term_structure: ClassVar[Flow] = Flow(
        "expand_term_structure",
        inputs=(ProductSelectionModule.products, RunWindowModule.run_window_envelope),
        outputs=(expanded_contracts, contract_metadata),
        # order=20, not grouped with the other market_data.py PRE_REPLAY flows
        # (37-45): MarketDataModule.check_market_data_coverage/load_raw_market_data
        # need expanded_contracts to plan/load each concrete contract's own
        # price series (not just the abstract product's continuous series --
        # that's what a resolved target actually trades once rollover/force-
        # close switches TermStructureExpandModule.resolve_tradable_target_weights'
        # output to a concrete contract object), so this must run BEFORE them,
        # not after (order=39 previously sat between check_market_data_coverage
        # at 38 and load_raw_market_data at 40 -- too late for either to see it).
        phase=Phase.PRE_REPLAY, order=20,
        after=(ProductSelectionModule.resolve_product_selection,),
        description="展开期限结构",
        compute=lambda state, ctx: _expand_term_structure(state, ctx),
        strategy_scoped=True,
    )
    resolve_tradable_target_weights: ClassVar[Flow] = Flow(
        "resolve_tradable_target_weights",
        inputs=(contract_metadata, _TARGET_WEIGHTS_REF),
        outputs=(_TARGET_WEIGHTS_REF,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        order=15,
        description="解析可交易合约目标",
        compute=lambda state, ctx: _resolve_tradable_target_weights(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (expand_term_structure, resolve_tradable_target_weights)


class DeliveryForceCloseModule(ExecutableModule):
    key: ClassVar[str] = "delivery_force_close"
    label: ClassVar[str] = "交割强平"

    force_close_before_expiry: ClassVar[FieldRef[str]] = FieldRef("force_close_before_expiry")
    force_close_notices: ClassVar[FieldRef[Any]] = FieldRef("force_close_notices")
    forced_close_orders: ClassVar[FieldRef[Any]] = FieldRef("forced_close_orders")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "force_close_before_expiry": FieldDefinition(
            public=True,
            label="到期强平提前量",
            default="2d",
            control_template="text",
            tab="delivery_force_close",
            chip_template="到期强平提前量: {value}",
            tab_label="交割强平",
            tab_order=39,
            help_text="按合约生命周期基准时点向前偏移登记强平通知；可填 5min、1h、2d 等任意非负时间间隔。",
        ),
        "force_close_notices": FieldDefinition(public=False),
        "forced_close_orders": FieldDefinition(public=False),
    }

    register_force_close_notices: ClassVar[Flow] = Flow(
        "register_force_close_notices",
        inputs=(TermStructureExpandModule.contract_metadata, force_close_before_expiry),
        outputs=(force_close_notices,),
        phase=Phase.PRE_REPLAY,
        order=46,
        after=(TermStructureExpandModule.expand_term_structure,),
        description="登记交割强平通知",
        compute=lambda state, ctx: _register_force_close_notices(state, ctx),
        strategy_scoped=True,
    )
    handle_delivery_force_close_notice: ClassVar[Flow] = Flow(
        "handle_delivery_force_close_notice",
        inputs=(_POSITIONS_REF,),
        outputs=(forced_close_orders,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER_NOTICE,
        order=15,
        description="处理交割强平通知",
        compute=lambda state, ctx: _handle_delivery_force_close_notice(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (register_force_close_notices, handle_delivery_force_close_notice)


class RolloverModule(ExecutableModule):
    key: ClassVar[str] = "rollover"
    label: ClassVar[str] = "换月"

    rollover_policy: ClassVar[FieldRef[str]] = FieldRef("rollover_policy")
    rollover_before_expiry: ClassVar[FieldRef[str]] = FieldRef("rollover_before_expiry")
    rollover_notices: ClassVar[FieldRef[Any]] = FieldRef("rollover_notices")
    rollover_orders: ClassVar[FieldRef[Any]] = FieldRef("rollover_orders")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "rollover_policy": FieldDefinition(
            public=True,
            label="换月规则",
            default="date_before_expiry",
            control_template="select",
            tab="rollover",
            chip_template="换月规则: {value}",
            tab_label="换月",
            tab_order=40,
            options=(
                ("none", "不自动换月"),
                ("date_before_expiry", "到期前固定时间换月"),
            ),
            help_text="登记换月通知；换月通知不同于交割强平通知，策略可选择是否跟随换月。",
        ),
        "rollover_before_expiry": FieldDefinition(
            public=True,
            label="换月提前量",
            default="5d",
            control_template="text",
            tab="rollover",
            chip_template="换月提前量: {value}",
            tab_label="换月",
            tab_order=40,
            visible_when={"rollover_policy": ("date_before_expiry",)},
            help_text="按合约生命周期基准时点向前偏移登记换月通知；可填 5min、1h、5d 等任意非负时间间隔。",
        ),
        "rollover_notices": FieldDefinition(public=False),
        "rollover_orders": FieldDefinition(public=False),
    }

    register_rollover_notices: ClassVar[Flow] = Flow(
        "register_rollover_notices",
        inputs=(TermStructureExpandModule.contract_metadata, rollover_policy, rollover_before_expiry),
        outputs=(rollover_notices,),
        phase=Phase.PRE_REPLAY,
        order=46,
        after=(TermStructureExpandModule.expand_term_structure,),
        description="登记换月通知",
        compute=lambda state, ctx: _register_rollover_notices(state, ctx),
        strategy_scoped=True,
    )
    handle_rollover_notice: ClassVar[Flow] = Flow(
        "handle_rollover_notice",
        inputs=(_POSITIONS_REF,),
        outputs=(rollover_orders,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER_NOTICE,
        order=10,
        description="处理换月通知",
        compute=lambda state, ctx: _handle_rollover_notice(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (register_rollover_notices, handle_rollover_notice)


def _expand_term_structure(state, ctx) -> None:
    """Record contract candidates that intersect the formal run window."""
    start_dt, end_dt = run_window_envelope_for_state(state)
    start_date = _datatime_date_text(start_dt)
    end_date = _datatime_date_text(end_dt)
    all_contracts: dict[Any, frozenset] = {}
    all_metadata: dict[Any, tuple[dict[str, Any], ...]] = {}
    product_expansion_cache: dict[tuple[Any, str | None, str | None], tuple[list[Any], list[dict[str, Any]]]] = {}
    strategies = ctx.active_strategies or frozenset(state.strategy_configs)
    for strategy in strategies:
        products = ctx.get_for(ProductSelectionModule.products, strategy)
        expanded: list[Any] = []
        metadata: list[dict[str, Any]] = []
        for product in products:
            cache_key = (product, start_date, end_date)
            if cache_key not in product_expansion_cache:
                product_expansion_cache[cache_key] = _expand_product_contracts(
                    product, start_date=start_date, end_date=end_date,
                )
            contracts, rows = product_expansion_cache[cache_key]
            expanded.extend(contracts)
            metadata.extend(dict(row) for row in rows)
        all_contracts[strategy] = frozenset(expanded)
        all_metadata[strategy] = tuple(metadata)
        ctx.set_for(TermStructureExpandModule.expanded_contracts, strategy, all_contracts[strategy])
        ctx.set_for(TermStructureExpandModule.contract_metadata, strategy, all_metadata[strategy])
    state.term_structure_store.set_expansion(all_contracts, all_metadata)


def _register_force_close_notices(state, ctx) -> None:
    start_dt, end_dt = run_window_envelope_for_state(state)
    drafts: list[EventDraft] = []
    strategies = ctx.active_strategies or frozenset(state.strategy_configs)
    for strategy in strategies:
        metadata = list(ctx.get_for(TermStructureExpandModule.contract_metadata, strategy, ()))
        offset = _parse_time_offset(
            state.config_for(strategy).get(DeliveryForceCloseModule.force_close_before_expiry, "0d"),
            field_name="force_close_before_expiry",
        )
        strategy_drafts = _lifecycle_event_drafts(
            strategy, metadata, start_dt=start_dt, end_dt=end_dt,
            offset=offset, notice_type="force_close", notice_reason="auto_close_date",
            state=state, reference_tz=_reference_timezone(state, strategy),
            engine_mode=engine_mode_for(state.config_for(strategy)),
        )
        drafts.extend(strategy_drafts)
        ctx.set_for(DeliveryForceCloseModule.force_close_notices, strategy, strategy_drafts)
    if drafts:
        ctx.set(DeliveryForceCloseModule.force_close_notices, drafts)


def _register_rollover_notices(state, ctx) -> None:
    start_dt, end_dt = run_window_envelope_for_state(state)
    drafts: list[EventDraft] = []
    strategies = ctx.active_strategies or frozenset(state.strategy_configs)
    for strategy in strategies:
        config = state.config_for(strategy)
        policy = str(config.get(RolloverModule.rollover_policy, "none") or "none")
        if policy == "none":
            ctx.set_for(RolloverModule.rollover_notices, strategy, [])
            continue
        if policy != "date_before_expiry":
            raise ValueError(f"unsupported rollover_policy={policy!r}")
        metadata = list(ctx.get_for(TermStructureExpandModule.contract_metadata, strategy, ()))
        offset = _parse_time_offset(
            config.get(RolloverModule.rollover_before_expiry, "5d"),
            field_name="rollover_before_expiry",
        )
        strategy_drafts = _lifecycle_event_drafts(
            strategy, metadata, start_dt=start_dt, end_dt=end_dt,
            offset=offset, notice_type="rollover", notice_reason="date_before_expiry",
            state=state, reference_tz=_reference_timezone(state, strategy),
            engine_mode=engine_mode_for(config),
        )
        drafts.extend(strategy_drafts)
        ctx.set_for(RolloverModule.rollover_notices, strategy, strategy_drafts)
    if drafts:
        ctx.set(RolloverModule.rollover_notices, drafts)


def _resolve_tradable_target_weights(state, ctx) -> None:
    # contract_metadata is set via ctx.set_for during PRE_REPLAY, but PER_EVENT
    # dispatch gets a brand-new FlowContext per batch (see scheduler.py's
    # make_dispatcher) -- ctx.get_for here would always see the empty default,
    # never PRE_REPLAY's output. Read from state.term_structure_store instead,
    # like _next_contract_object_for_notice below already does.
    for strategy in ctx.active_strategies:
        weights = ctx.get_for(_TARGET_WEIGHTS_REF, strategy, {})
        metadata = list(state.term_structure_store.contract_metadata.get(strategy, ()))
        if not weights or not metadata:
            continue
        config = state.config_for(strategy)
        rollover_policy = str(config.get(RolloverModule.rollover_policy, "none") or "none")
        rollover_offset = _parse_time_offset(
            config.get(RolloverModule.rollover_before_expiry, "5d"),
            field_name="rollover_before_expiry",
        ) if rollover_policy == "date_before_expiry" else None
        force_close_offset = _parse_time_offset(
            config.get(DeliveryForceCloseModule.force_close_before_expiry, "2d"),
            field_name="force_close_before_expiry",
        )
        mapped: dict[Any, float] = {}
        mapping_trace: dict[str, str | None] = {}
        for product, weight in weights.items():
            row = _tradable_contract_row(
                product,
                metadata,
                timestamp=ctx.timestamp,
                rollover_offset=rollover_offset,
                force_close_offset=force_close_offset,
                state=state,
                engine_mode=engine_mode_for(config),
            )
            target = row.get("contract_object", product) if row is not None else product
            if target is None:
                mapping_trace[str(product)] = None
                continue
            mapped[target] = mapped.get(target, 0.0) + weight
            mapping_trace[str(product)] = str(getattr(target, "name", target))
        ctx.set_for(_TARGET_WEIGHTS_REF, strategy, mapped)
        if mapping_trace:
            state.term_structure_store.record_target_mapping(strategy, ctx.timestamp, mapping_trace)


def _handle_rollover_notice(state, ctx) -> None:
    for strategy in ctx.active_strategies:
        ledger = state.ledgers.get(strategy)
        positions = ledger.get(_POSITIONS_REF, {}) if ledger is not None else {}
        orders: list[Order] = []
        for raw_payload in ctx.payloads_for(strategy):
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            if str(payload.get("notice_type") or "") != "rollover":
                continue
            _record_term_structure_notice(state, payload)
            old_contract = payload.get("contract_object")
            next_contract = _next_contract_object_for_notice(state, strategy, payload)
            if old_contract is None or next_contract is None:
                continue
            entry = positions.get(old_contract)
            quantity = getattr(entry, "quantity", 0) if entry is not None else 0
            if not quantity:
                continue
            close_order = Order(
                instrument=old_contract,
                timestamp=ctx.timestamp,
                quantity=-quantity,
                intent_quantity=-quantity,
                strategy=strategy,
                status=OrderStatus.SCHEDULED,
                fields={"reason": "term_structure_rollover_close", "source": payload},
            )
            open_order = Order(
                instrument=next_contract,
                timestamp=ctx.timestamp,
                quantity=quantity,
                intent_quantity=quantity,
                strategy=strategy,
                status=OrderStatus.SCHEDULED,
                fields={
                    "reason": "term_structure_rollover_open",
                    "source": payload,
                    "rollover_from": old_contract,
                },
            )
            orders.extend((close_order, open_order))
        if orders:
            ctx.set_for(RolloverModule.rollover_orders, strategy, orders)
            ctx.set(RolloverModule.rollover_orders, [
                EventDraft(EventKind.ORDER, ctx.timestamp, strategy, order)
                for order in orders
            ])


def _handle_delivery_force_close_notice(state, ctx) -> None:
    for strategy in ctx.active_strategies:
        ledger = state.ledgers.get(strategy)
        if ledger is None:
            continue
        positions = ledger.get(_POSITIONS_REF, {})
        orders: list[Order] = []
        for raw_payload in ctx.payloads_for(strategy):
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            notice_type = str(payload.get("notice_type") or "")
            if notice_type != "force_close":
                _record_term_structure_notice(state, payload)
                continue
            contract = payload.get("contract_object")
            if contract is None:
                continue
            entry = positions.get(contract)
            quantity = getattr(entry, "quantity", 0) if entry is not None else 0
            if not quantity:
                continue
            order = Order(
                instrument=contract,
                timestamp=ctx.timestamp,
                quantity=-quantity,
                intent_quantity=-quantity,
                strategy=strategy,
                status=OrderStatus.SCHEDULED,
                fields={
                    "reason": "term_structure_force_close",
                    "source": payload,
                },
            )
            orders.append(order)
            _record_term_structure_notice(state, payload)
        if orders:
            ctx.set_for(DeliveryForceCloseModule.forced_close_orders, strategy, orders)
            ctx.set(DeliveryForceCloseModule.forced_close_orders, [
                EventDraft(EventKind.ORDER, ctx.timestamp, strategy, order)
                for order in orders
            ])


def _record_term_structure_notice(state, payload: dict[str, Any]) -> None:
    state.term_structure_store.record_notice(payload)


def _next_contract_object_for_notice(state, strategy: Any, payload: dict[str, Any]) -> Any | None:
    current = payload.get("contract_object")
    product_name = payload.get("product")
    metadata = list(state.term_structure_store.contract_metadata.get(strategy, ()))
    rows = [row for row in metadata if row.get("product") == product_name and not row.get("is_identity")]
    if not rows:
        return None
    rows = sorted(rows, key=lambda row: _timestamp_sort_key(_row_start_value(row) or pd.Timestamp.min))
    for idx, row in enumerate(rows):
        if row.get("contract_object") != current:
            continue
        if idx + 1 >= len(rows):
            return None
        return rows[idx + 1].get("contract_object")
    return None


def _reference_timezone(state, strategy: Any) -> str | None:
    config = state.config_for(strategy)
    precision = str(config.get(RunWindowModule.time_precision, "exact") or "exact")
    if precision != "exact":
        return None
    timezone = str(config.get(RunWindowModule.timezone, "Asia/Shanghai") or "").strip()
    return timezone or None


def _datatime_date_text(value: Any) -> str | None:
    ts = getattr(value, "ts", None)
    if ts is None:
        return None
    return cast(pd.Timestamp, pd.Timestamp(ts)).strftime("%Y-%m-%d")


def _expand_product_contracts(product: Any, *, start_date: str | None, end_date: str | None) -> tuple[list[Any], list[dict[str, Any]]]:
    supports = getattr(product, "supports_term_structure", None)
    if not callable(supports) or not supports():
        return [product], [{
            "product": getattr(product, "name", str(product)),
            "contract": getattr(product, "name", str(product)),
            "uid": getattr(product, "name", str(product)),
            "is_identity": True,
        }]

    contract_list = getattr(product, "get_contract_list", None)
    if not callable(contract_list):
        return [product], [{
            "product": getattr(product, "name", str(product)),
            "contract": getattr(product, "name", str(product)),
            "uid": getattr(product, "name", str(product)),
            "is_identity": True,
            "term_structure_missing": "get_contract_list",
        }]
    rows = list(cast(Any, contract_list(start_date=start_date, end_date=end_date)))
    if not rows:
        return [], []
    contract_cls = getattr(product, "contract_class", None)
    contracts: list[Any] = []
    metadata: list[dict[str, Any]] = []
    for row in rows:
        uid = row.get("uid") or row.get("contract")
        contract = contract_cls(uid) if contract_cls is not None and uid else product
        metadata_row = _with_authoritative_lifecycle_fields({
            **row,
            "product": getattr(product, "name", str(product)),
            "contract_object": contract,
            "contract_product": getattr(contract, "name", str(contract)),
            "is_identity": False,
        })
        contracts.append(contract)
        metadata.append(metadata_row)
    return contracts, metadata


@lru_cache(maxsize=1)
def _openctp_lifecycle_specs_by_instrument() -> dict[str, dict[str, Any]]:
    try:
        from sources.OpenCTP.client import normalise_instrument_code, read_cnfutures_contract_specs_for_date
    except Exception:
        return {}
    try:
        specs = read_cnfutures_contract_specs_for_date(None, allow_latest_fallback=True)
    except Exception:
        return {}
    if not isinstance(specs, pd.DataFrame) or specs.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for _, spec in specs.iterrows():
        keys = {
            normalise_instrument_code(spec.get("InstrumentID")),
            normalise_instrument_code(spec.get("NormalizedInstrumentID")),
        }
        row = {
            "open_date": spec.get("OpenDate"),
            "last_trade_date": spec.get("ExpireDate"),
            "delivery_date": spec.get("DeliveryDate"),
            "inst_life_phase": spec.get("InstLifePhase"),
            "lifecycle_source": "OpenCTP latest contract snapshot",
        }
        for key in keys:
            if key:
                out[key] = row
    return out


@lru_cache(maxsize=1)
def _akshare_lifecycle_specs_by_instrument() -> dict[str, dict[str, Any]]:
    try:
        from sources.AKShare.lifecycle import read_contract_lifecycle
        from sources.OpenCTP.client import normalise_instrument_code
    except Exception:
        return {}
    try:
        specs = read_contract_lifecycle()
    except Exception:
        return {}
    if not isinstance(specs, pd.DataFrame) or specs.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for _, spec in specs.iterrows():
        key = normalise_instrument_code(spec.get("contract_code"))
        if not key:
            continue
        out[key] = {
            "open_date": spec.get("list_date"),
            "last_trade_date": spec.get("last_trading_date"),
            "notice_date": spec.get("delivery_notice_date"),
            "delivery_date": spec.get("last_delivery_date"),
            "lifecycle_source": f"AKShare {spec.get('exchange')} contract lifecycle",
        }
    return out


# Local product/contract names are suffixed with these short exchange codes
# (see sources.LocalCNFutures.product_catalog._EXCHANGE_TO_SECTOR_CODE), not
# the AKShare exchange codes used by src_akshare_contract_lifecycle.
_LOCAL_EXCHANGE_SUFFIX_TO_AKSHARE = {
    "DCE": "DCE",
    "CZC": "CZCE",
    "INE": "INE",
    "SHF": "SHFE",
    "CFE": "CFFEX",
    "GFE": "GFEX",
}
_akshare_live_cache: dict[str, dict[str, Any]] = {}
_akshare_live_attempted: set[str] = set()
_AKSHARE_LIVE_LOOKUP_ENV = "GTHT_AKSHARE_LIVE_LOOKUP"


def _akshare_live_lookup_enabled() -> bool:
    """Live AKShare lookups make a real network call and write to the shared
    cache DB. Enabled by default; set GTHT_AKSHARE_LIVE_LOOKUP=0 to opt out
    (e.g. for hermetic/offline test runs)."""
    import os

    return str(os.environ.get(_AKSHARE_LIVE_LOOKUP_ENV, "1")).strip().lower() not in {"0", "false", "no"}


def _row_exchange(row: dict[str, Any]) -> str | None:
    for key in ("contract_product", "contract", "uid"):
        text = str(row.get(key) or "").strip()
        if "." not in text:
            continue
        suffix = text.rsplit(".", 1)[-1].upper()
        mapped = _LOCAL_EXCHANGE_SUFFIX_TO_AKSHARE.get(suffix)
        if mapped:
            return mapped
    return None


def _akshare_live_lookup(exchange: str, key: str) -> dict[str, Any] | None:
    """On-demand top-up for a contract missing from the backfilled table.

    Tried at most once per exchange per process: DCE/GFEX only ever expose a
    recent rolling window through AKShare, so a live query now is exactly as
    good as it gets for a *current* contract, and repeating it per-contract
    within one run would be wasted network calls for the same answer.
    """
    if exchange in _akshare_live_attempted:
        return _akshare_live_cache.get(key)
    _akshare_live_attempted.add(exchange)
    try:
        from sources.AKShare.lifecycle import fetch_and_store_live
        from sources.OpenCTP.client import normalise_instrument_code
    except Exception:
        return None
    try:
        live_rows = fetch_and_store_live(exchange)
    except Exception:
        return None
    for live_row in live_rows:
        code = normalise_instrument_code(live_row.get("contract_code"))
        if not code:
            continue
        _akshare_live_cache[code] = {
            "open_date": live_row.get("list_date"),
            "last_trade_date": live_row.get("last_trading_date"),
            "notice_date": live_row.get("delivery_notice_date"),
            "delivery_date": live_row.get("last_delivery_date"),
            "lifecycle_source": f"AKShare {exchange} live lookup",
        }
    return _akshare_live_cache.get(key)


def _with_authoritative_lifecycle_fields(row: dict[str, Any]) -> dict[str, Any]:
    if any(row.get(key) not in (None, "") for key in _LIFECYCLE_TS_KEYS + _LIFECYCLE_DATE_KEYS):
        return row
    key = _normalised_contract_id(row)
    if not key:
        return row
    # AKShare is published directly by the exchanges; prefer it over OpenCTP's
    # snapshot and let it override any overlapping field.
    spec: dict[str, Any] = {}
    openctp_spec = _openctp_lifecycle_specs_by_instrument().get(key)
    if openctp_spec:
        spec.update(openctp_spec)
    akshare_spec = _akshare_lifecycle_specs_by_instrument().get(key)
    if akshare_spec:
        spec.update(akshare_spec)
    if not spec and _akshare_live_lookup_enabled():
        exchange = _row_exchange(row)
        if exchange:
            live_spec = _akshare_live_lookup(exchange, key)
            if live_spec:
                spec.update(live_spec)
    if not spec:
        return row
    enriched = dict(row)
    for field, value in spec.items():
        if value not in (None, "") and enriched.get(field) in (None, ""):
            enriched[field] = value
    return enriched


def _normalised_contract_id(row: dict[str, Any]) -> str:
    try:
        from sources.OpenCTP.client import normalise_instrument_code
    except Exception:
        def normalise_instrument_code(value: Any) -> str:
            return "".join(ch for ch in str(value or "").upper().split(".")[0] if ch.isalnum())

    for key in ("contract_product", "contract", "uid"):
        value = row.get(key)
        text = str(value or "").strip()
        if not text:
            continue
        if "|" in text:
            parts = text.split("|")
            if len(parts) >= 4:
                return normalise_instrument_code(f"{parts[2]}{parts[3]}")
        normalized = normalise_instrument_code(text)
        if normalized:
            return normalized
    return ""


def _tradable_contract_row(
    product: Any,
    metadata: list[dict[str, Any]],
    *,
    timestamp: Any,
    rollover_offset: pd.Timedelta | None,
    force_close_offset: pd.Timedelta,
    state: Any | None = None,
    engine_mode: str = "auto",
) -> dict[str, Any] | None:
    product_name = getattr(product, "name", str(product))
    rows = [row for row in metadata if row.get("product") == product_name]
    if not rows:
        return None
    if len(rows) == 1 and rows[0].get("is_identity"):
        return rows[0]
    ts = _timestamp_sort_key(timestamp)
    rows = sorted(rows, key=lambda row: _timestamp_sort_key(_row_start_value(row) or pd.Timestamp.min))
    selected_idx: int | None = None
    for idx, row in enumerate(rows):
        start = _timestamp_sort_key(_row_start_value(row) or pd.Timestamp.min)
        end = _timestamp_sort_key(_row_end_value(row) or pd.Timestamp.max)
        if start <= ts <= end:
            selected_idx = idx
            break
    if selected_idx is None:
        for idx, row in enumerate(rows):
            start = _timestamp_sort_key(_row_start_value(row) or pd.Timestamp.min)
            if ts < start:
                return row
        return None

    row = rows[selected_idx]
    next_row = rows[selected_idx + 1] if selected_idx + 1 < len(rows) else None
    force_close_ts = _event_timestamp_from_row(
        row, offset=force_close_offset, state=state, peer_rows=rows, engine_mode=engine_mode,
    )
    if force_close_ts is not None and ts >= _timestamp_sort_key(force_close_ts):
        return next_row
    if rollover_offset is not None:
        rollover_ts = _event_timestamp_from_row(
            row, offset=rollover_offset, state=state, peer_rows=rows, engine_mode=engine_mode,
        )
        if rollover_ts is not None and ts >= _timestamp_sort_key(rollover_ts):
            return next_row or row
    return row


def _row_start_value(row: dict[str, Any]) -> Any:
    for key in ("start_ts", "listed_ts"):
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return pd.Timestamp(int(cast(Any, value)), unit="ms")
        except Exception:
            pass
    for key in ("start", "listed_date"):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _row_end_value(row: dict[str, Any]) -> Any:
    for key in ("end_ts", "auto_close_ts", "last_trade_ts", "maturity_ts"):
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return pd.Timestamp(int(cast(Any, value)), unit="ms")
        except Exception:
            pass
    for key in ("end", "auto_close_date", "last_trade_date", "maturity_date"):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _lifecycle_event_drafts(
    strategy: Any,
    metadata: list[dict[str, Any]],
    *,
    start_dt: Any,
    end_dt: Any,
    offset: pd.Timedelta,
    notice_type: str,
    notice_reason: str,
    state: Any | None = None,
    reference_tz: str | None = None,
    engine_mode: str = "auto",
) -> list[EventDraft]:
    drafts: list[EventDraft] = []
    start_key = _sort_key(start_dt)
    end_key = _sort_key(end_dt)
    for row in metadata:
        if row.get("is_identity"):
            continue
        ts = _event_timestamp_from_row(
            row, offset=offset, state=state, reference_tz=reference_tz,
            peer_rows=metadata, engine_mode=engine_mode,
        )
        if ts is None:
            continue
        ts_key = _timestamp_sort_key(ts)
        if start_key is not None and ts_key < start_key:
            continue
        if end_key is not None and ts_key > end_key:
            continue
        payload = {
            **row,
            "notice_type": notice_type,
            "notice_reason": notice_reason,
        }
        drafts.append(EventDraft(EventKind.ORDER_NOTICE, ts, strategy, payload=payload))
    return drafts


def _event_timestamp_from_row(
    row: dict[str, Any],
    *,
    offset: pd.Timedelta,
    state: Any | None = None,
    reference_tz: str | None = None,
    peer_rows: list[dict[str, Any]] | None = None,
    engine_mode: str = "auto",
) -> pd.Timestamp | None:
    base = _lifecycle_base_timestamp(
        row, reference_tz=reference_tz, state=state, peer_rows=peer_rows, engine_mode=engine_mode,
    )
    if base is None:
        return None
    return _apply_lifecycle_offset(base, offset, state=state)


def _lifecycle_base_timestamp(
    row: dict[str, Any],
    *,
    reference_tz: str | None,
    state: Any | None = None,
    peer_rows: list[dict[str, Any]] | None = None,
    engine_mode: str = "auto",
) -> pd.Timestamp | None:
    for key in _LIFECYCLE_TS_KEYS:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            ts = pd.Timestamp(int(cast(Any, value)), unit="ms")
            if pd.isna(ts):
                continue
            return _with_reference_timezone(cast(pd.Timestamp, ts), reference_tz)
        except Exception:
            pass
    for key in _LIFECYCLE_DATE_KEYS:
        value = row.get(key)
        if value in (None, ""):
            continue
        ts = pd.Timestamp(cast(Any, value))
        if pd.isna(ts):
            continue
        return _with_reference_timezone(cast(pd.Timestamp, ts), reference_tz)
    # Row fields → AKShare cache → OpenCTP → live AKShare lookup all ran already
    # in _with_authoritative_lifecycle_fields; reaching here means none of them
    # had this contract. LocalCNFutures coverage inference is the last resort —
    # it only returns non-None when it can conclusively tell the contract has
    # stopped trading (a peer contract kept printing bars after this one went
    # quiet); "still might be alive" or "no data to check" both come back None.
    inferred = _local_cnfutures_inferred_lifecycle(row, peer_rows=peer_rows, state=state)
    if inferred is not None:
        return _with_reference_timezone(inferred, reference_tz)
    if str(engine_mode).lower() == "exact":
        raise ValueError(
            "exact engine_mode could not determine whether "
            f"{row.get('contract_product') or row.get('contract') or row.get('uid')} "
            "has stopped trading: no authoritative lifecycle date, and local "
            "coverage inference is inconclusive (either no market data to check, "
            "or the contract may still be trading)"
        )
    return None


def _local_cnfutures_inferred_lifecycle(
    row: dict[str, Any],
    *,
    peer_rows: list[dict[str, Any]] | None,
    state: Any | None,
) -> pd.Timestamp | None:
    raw_prices = _raw_prices_table_for(state)
    if not isinstance(raw_prices, pd.DataFrame):
        raw_market_data = getattr(state, "raw_market_data", None) if state is not None else None
        if isinstance(raw_market_data, dict):
            raw_prices = raw_market_data.get("raw_prices")
    if not isinstance(raw_prices, pd.DataFrame):
        return None
    try:
        from sources.LocalCNFutures.lifecycle import infer_contract_end_from_coverage
    except Exception:
        return None
    result = infer_contract_end_from_coverage(row, peer_rows or [row], raw_prices)
    if result.get("status") != "ended":
        return None
    raw_ts = result.get("timestamp")
    if raw_ts is None:
        return None
    ts = pd.Timestamp(raw_ts)
    if pd.isna(ts):
        return None
    row.setdefault("lifecycle_source", result.get("source"))
    row.setdefault("lifecycle_inference", result)
    return cast(pd.Timestamp, ts)


def _with_reference_timezone(ts: pd.Timestamp, reference_tz: str | None) -> pd.Timestamp:
    if reference_tz:
        if ts.tzinfo is None:
            return cast(pd.Timestamp, ts.tz_localize(reference_tz))
        return cast(pd.Timestamp, ts.tz_convert(reference_tz))
    return ts


def _apply_lifecycle_offset(
    base: pd.Timestamp,
    offset: pd.Timedelta,
    *,
    state: Any | None,
) -> pd.Timestamp:
    if offset <= pd.Timedelta(0):
        return base
    table = _current_prices_table_for(state)
    if isinstance(table, pd.DataFrame) and not table.empty:
        shifted = _shift_on_event_axis(base, offset, table)
        if shifted is not None:
            return shifted
    return cast(pd.Timestamp, base - offset)


def _raw_prices_table_for(state: Any | None) -> Any:
    if state is None:
        return None
    from tools.testers.backtest.modules.market_data import raw_prices_table_for
    return raw_prices_table_for(state)


def _current_prices_table_for(state: Any | None) -> Any:
    if state is None:
        return None
    from tools.testers.backtest.modules.market_data import current_prices_table_for
    return current_prices_table_for(state)


def _shift_on_event_axis(base: pd.Timestamp, offset: pd.Timedelta, table: pd.DataFrame) -> pd.Timestamp | None:
    data_index = DataIndex(table.index)
    events = pd.DatetimeIndex(data_index.event_timestamps())
    if events.empty:
        return None
    aligned_base = data_index.tz_align(base)
    day_count = max(0, int(offset.days))
    subday = cast(pd.Timedelta, offset - pd.Timedelta(days=day_count))
    anchor = aligned_base
    if day_count:
        trading_days = pd.DatetimeIndex(data_index.trading_day_index())
        pos = int(events.searchsorted(cast(Any, aligned_base), side="right")) - 1
        if pos < 0:
            return None
        base_day = trading_days[pos]
        unique_days = pd.DatetimeIndex(pd.unique(trading_days)).sort_values()
        day_pos = int(unique_days.searchsorted(base_day, side="right")) - 1
        target_day_pos = day_pos - day_count
        if target_day_pos < 0:
            return None
        target_day = unique_days[target_day_pos]
        day_positions = [i for i, day in enumerate(trading_days) if day == target_day and events[i] <= aligned_base]
        if not day_positions:
            day_positions = [i for i, day in enumerate(trading_days) if day == target_day]
        if not day_positions:
            return None
        anchor = events[day_positions[-1]]
    desired = cast(pd.Timestamp, anchor - subday)
    final_pos = int(events.searchsorted(cast(Any, desired), side="right")) - 1
    if final_pos < 0:
        return None
    return cast(pd.Timestamp, events[final_pos])


def _parse_time_offset(value: Any, *, field_name: str) -> pd.Timedelta:
    if value not in (None, ""):
        try:
            text = str(value).strip()
            if text.endswith("d"):
                text = f"{text[:-1]}D"
            delta = cast(pd.Timedelta, pd.Timedelta(text))
            if delta < pd.Timedelta(0):
                raise ValueError
            return delta
        except Exception:
            raise ValueError(
                f"invalid {field_name}={value!r}; expected non-negative time such as "
                "'5min', '1h', or '2d'"
            )
    return cast(pd.Timedelta, pd.Timedelta(0))


def _sort_key(value: Any) -> pd.Timestamp | None:
    sort_key = getattr(value, "sort_key", None)
    if callable(sort_key):
        raw = sort_key()
        if raw is not None:
            return _timestamp_sort_key(raw)
    ts = getattr(value, "ts", None)
    if ts is not None:
        return _timestamp_sort_key(ts)
    return None


def _timestamp_sort_key(value: Any) -> pd.Timestamp:
    ts = cast(pd.Timestamp, pd.Timestamp(value))
    if ts.tzinfo is not None:
        ts = cast(pd.Timestamp, ts.tz_convert("UTC")).tz_localize(None)
    return ts
