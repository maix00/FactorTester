"""ProductSelectionModule — resolves each strategy's product_path_selection.

`ProductSelectionModule.products` deliberately keeps the product-path universe:
for futures that is normally the abstract product/continuous series used for
research and signal coverage checks.  `TermStructureExpandModule` runs later
and records the concrete contracts whose trading life intersects the run
window; it does not require each contract to cover the whole run window.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.order import Order, OrderStatus
from tools.products.product_path_selection import ProductPathSelection
from tools.testers.backtest.modules.run_window import RunWindowModule

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.products.product_path_selection import ProductPathSelection


_POSITIONS_REF = FieldRef("positions", owner="LedgerModule")


class ProductSelectionModule(ExecutableModule):
    key: ClassVar[str] = "product_selection"
    label: ClassVar[str] = "产品选择"

    product_path_selection: ClassVar[FieldRef[Any]] = FieldRef("product_path_selection")
    product_path_candidates: ClassVar[FieldRef[list[Any]]] = FieldRef("product_path_candidates")
    products: ClassVar[FieldRef[frozenset]] = FieldRef("products")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "product_path_candidates": FieldDefinition(
            public=True, label="产品路径候选", default=[], control_template="custom", tab="product_path_selection",
            chip_template="产品路径候选: {value}", tab_label="产品路径", tab_order=30,
            help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场路径组。",
            serialization={
                "kind": "product_path_candidate_list",
                "display_order": 10,
                "item_kind": "product_path_selection",
                "shared_page_field": "product_path_candidates",
                "selection_field": "product_path_selection",
                "product_group_source": "user_product_group_templates",
                "manual_candidate_source": "runtime_manual_path_group",
                "fallback_policy": (
                    "copy_page_candidates",
                    "load_user_product_groups_when_page_empty",
                ),
                "mutation_scope": {
                    "page": "page_candidates_only",
                    "module": "module_candidates_only",
                },
                "persist_manual_candidates": False,
                "dedupe_product_groups": True,
                "allow_duplicate_manual_candidates": True,
            },
        ),
        "product_path_selection": FieldDefinition(
            public=True, label="产品路径", default=None, control_template="select", tab="product_path_selection",
            chip_template="产品路径: {value}", tab_label="产品路径", tab_order=30,
            help_text="选择或内联一组产品路径；若引用用户产品组模板，则保存产品组模板 id。",
            info_overlay={"type": "product_path_selection_products"},
            instance_class=ProductPathSelection,
            serialization={
                "kind": "product_path_selection",
                "display_order": 20,
                "shared_page_field": "product_path_selection",
                "product_group_reference_keys": (
                    "product_group_template_id",
                    "path_id",
                ),
                "product_group_source_type": "user_product_group_template",
                "id_keys": (
                    "product_path_selection_id",
                    "selection_id",
                    "id",
                ),
                "manual_path_keys": (
                    "paths",
                    "selected_paths",
                ),
                "product_group_fields": ("product_path_selection_id",),
                "manual_fields": (
                    "product_path_selection_id",
                    "paths",
                ),
            },
        ),
    }

    resolve_product_selection: ClassVar[Flow] = Flow(
        "resolve_product_selection", inputs=(product_path_selection,), outputs=(products,),
        phase=Phase.PRE_REPLAY, order=15, compute=lambda account, ctx: _resolve_product_selection(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (resolve_product_selection,)


def _resolve_product_selection(account, ctx) -> None:
    by_selection_id: dict[str, list] = defaultdict(list)
    for strategy in account.strategy_configs:
        selection = account.config_for(strategy).get(ProductSelectionModule.product_path_selection)
        by_selection_id[selection.selection_id].append(strategy)

    for selection_id, strategies in by_selection_id.items():
        selection = account.config_for(strategies[0]).get(ProductSelectionModule.product_path_selection)
        resolved = frozenset(selection.products)  # parsed once per unique selection_id
        for strategy in strategies:
            ctx.set_for(ProductSelectionModule.products, strategy, resolved)


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
    lifecycle_events: ClassVar[FieldRef[Any]] = FieldRef("lifecycle_events")
    forced_close_orders: ClassVar[FieldRef[Any]] = FieldRef("forced_close_orders")
    force_close_before_expiry: ClassVar[FieldRef[str]] = FieldRef("force_close_before_expiry")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "expanded_contracts": FieldDefinition(public=False),
        "contract_metadata": FieldDefinition(public=False),
        "lifecycle_events": FieldDefinition(public=False),
        "forced_close_orders": FieldDefinition(public=False),
        "force_close_before_expiry": FieldDefinition(
            public=True,
            label="到期强平提前量",
            default="0d",
            control_template="text",
            tab="term_structure",
            chip_template="到期强平提前量: {value}",
            tab_label="期限结构",
            tab_order=38,
            help_text="按合约生命周期基准日向前偏移登记强平事件；若有 First Notice/交割风险日期则优先使用，否则使用合约窗口结束日。",
        ),
    }

    expand_term_structure: ClassVar[Flow] = Flow(
        "expand_term_structure",
        inputs=(ProductSelectionModule.products, RunWindowModule.run_window_envelope, force_close_before_expiry),
        outputs=(expanded_contracts, contract_metadata),
        phase=Phase.PRE_REPLAY, order=39,
        after=(ProductSelectionModule.resolve_product_selection,),
        compute=lambda account, ctx: _expand_term_structure(account, ctx),
    )
    handle_term_structure_notice: ClassVar[Flow] = Flow(
        "handle_term_structure_notice",
        inputs=(_POSITIONS_REF,),
        outputs=(forced_close_orders,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.NOTICE,
        order=15,
        compute=lambda account, ctx: _handle_term_structure_notice(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (expand_term_structure, handle_term_structure_notice)


def _expand_term_structure(account, ctx) -> None:
    """Record contract candidates that intersect the formal run window."""
    start_dt, end_dt = getattr(account, "run_window_envelope", (None, None))
    start_date = _datatime_date_text(start_dt)
    end_date = _datatime_date_text(end_dt)
    all_contracts: dict[Any, frozenset] = {}
    all_metadata: dict[Any, tuple[dict[str, Any], ...]] = {}
    drafts: list[EventDraft] = []
    for strategy in account.strategy_configs:
        products = ctx.get_for(ProductSelectionModule.products, strategy)
        expanded: list[Any] = []
        metadata: list[dict[str, Any]] = []
        for product in products:
            contracts, rows = _expand_product_contracts(product, start_date=start_date, end_date=end_date)
            expanded.extend(contracts)
            metadata.extend(rows)
        all_contracts[strategy] = frozenset(expanded)
        all_metadata[strategy] = tuple(metadata)
        ctx.set_for(TermStructureExpandModule.expanded_contracts, strategy, all_contracts[strategy])
        ctx.set_for(TermStructureExpandModule.contract_metadata, strategy, all_metadata[strategy])
        offset = _parse_force_close_offset(
            account.config_for(strategy).get(TermStructureExpandModule.force_close_before_expiry, "0d")
        )
        drafts.extend(_lifecycle_event_drafts(strategy, metadata, start_dt=start_dt, end_dt=end_dt, offset=offset))
    account.term_structure_expanded_contracts = all_contracts
    account.term_structure_contract_metadata = all_metadata
    if drafts:
        ctx.set(TermStructureExpandModule.lifecycle_events, drafts)


def _handle_term_structure_notice(account, ctx) -> None:
    for strategy in ctx.active_strategies:
        ledger = account.ledgers.get(strategy)
        if ledger is None:
            continue
        positions = ledger.get(_POSITIONS_REF, {})
        orders: list[Order] = []
        for raw_payload in ctx.payloads_for(strategy):
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            notice_type = str(payload.get("notice_type") or "")
            if notice_type != "force_close":
                _record_term_structure_notice(account, payload)
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
            _record_term_structure_notice(account, payload)
        if orders:
            ctx.set_for(TermStructureExpandModule.forced_close_orders, strategy, orders)
            ctx.set(TermStructureExpandModule.lifecycle_events, [
                EventDraft(EventKind.ORDER, ctx.timestamp, strategy, order)
                for order in orders
            ])


def _record_term_structure_notice(account, payload: dict[str, Any]) -> None:
    notices = getattr(account, "term_structure_notices", None)
    if notices is None:
        notices = []
        account.term_structure_notices = notices
    notices.append(payload)


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
        contracts.append(contract)
        metadata.append({
            **row,
            "product": getattr(product, "name", str(product)),
            "contract_object": contract,
            "contract_product": getattr(contract, "name", str(contract)),
            "is_identity": False,
        })
    return contracts, metadata


def _lifecycle_event_drafts(
    strategy: Any,
    metadata: list[dict[str, Any]],
    *,
    start_dt: Any,
    end_dt: Any,
    offset: pd.Timedelta,
) -> list[EventDraft]:
    drafts: list[EventDraft] = []
    start_key = _sort_key(start_dt)
    end_key = _sort_key(end_dt)
    for row in metadata:
        if row.get("is_identity"):
            continue
        ts = _event_timestamp_from_row(row, offset=offset)
        if ts is None:
            continue
        ts_key = _timestamp_sort_key(ts)
        if start_key is not None and ts_key < start_key:
            continue
        if end_key is not None and ts_key > end_key:
            continue
        payload = {
            **row,
            "notice_type": "force_close",
            "notice_reason": "auto_close_date",
        }
        drafts.append(EventDraft(EventKind.NOTICE, ts, strategy, payload=payload))
    return drafts


def _event_timestamp_from_row(row: dict[str, Any], *, offset: pd.Timedelta) -> pd.Timestamp | None:
    for key in ("auto_close_ts", "first_notice_ts", "notice_ts", "delivery_ts", "maturity_ts", "end_ts"):
        value = row.get(key)
        if value not in (None, ""):
            try:
                return cast(pd.Timestamp, pd.Timestamp(int(value), unit="ms") - offset)
            except Exception:
                pass
    for key in ("auto_close_date", "first_notice_date", "notice_date", "delivery_date", "maturity_date", "end"):
        value = row.get(key)
        if value in (None, ""):
            continue
        return cast(pd.Timestamp, pd.Timestamp(value) - offset)
    return None


def _parse_force_close_offset(value: Any) -> pd.Timedelta:
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
            raise ValueError(f"invalid force_close_before_expiry={value!r}; expected non-negative time such as '0d' or '2d'")
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
