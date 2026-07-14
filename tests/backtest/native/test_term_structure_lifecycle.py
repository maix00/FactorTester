from __future__ import annotations

from typing import cast

import pandas as pd
import pytest

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.config import StrategyConfig
from tools.testers.backtest.engines.native.position import ProductPosition
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext, FlowRegistry, make_dispatcher, sort_and_validate
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import set_cash_for_ledger_pool
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules import term_structure
from tools.testers.backtest.modules.term_structure import (
    DeliveryForceCloseModule,
    ProductSelectionModule,
    RolloverModule,
    TermStructureExpandModule,
    _expand_term_structure,
    _handle_delivery_force_close_notice,
    _handle_rollover_notice,
    _register_force_close_notices,
    _register_rollover_notices,
    _resolve_tradable_target_weights,
)
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.run_window import RunWindowModule, strategy_run_window_datetimes


def _ms(value: str) -> int:
    return int(cast(pd.Timestamp, pd.Timestamp(value)).timestamp() * 1000)


class _Contract:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Contract) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)


class _TermProduct:
    name = "P.DCE"
    contract_class = _Contract

    def supports_term_structure(self) -> bool:
        return True

    def get_contract_list(self, start_date=None, end_date=None):
        return [{
            "uid": "P2601.DCE",
            "contract": "P2601",
            "start": "2026-01-01",
            "end": "2026-01-31",
            "end_ts": _ms("2026-01-31 15:00"),
            "last_trade_ts": _ms("2026-01-31 15:00"),
        }]


class _TwoContractTermProduct(_TermProduct):
    def get_contract_list(self, start_date=None, end_date=None):
        return [
            {
                "uid": "P2601.DCE",
                "contract": "P2601",
                "start": "2026-01-01",
                "end": "2026-01-31",
                "end_ts": _ms("2026-01-31 15:00"),
                "last_trade_ts": _ms("2026-01-31 15:00"),
            },
            {
                "uid": "P2602.DCE",
                "contract": "P2602",
                "start": "2026-01-20",
                "end": "2026-02-28",
                "end_ts": _ms("2026-02-28 15:00"),
                "last_trade_ts": _ms("2026-02-28 15:00"),
            },
        ]


class _CoverageOnlyTermProduct(_TermProduct):
    def get_contract_list(self, start_date=None, end_date=None):
        return [{
            "uid": "P2601.DCE",
            "contract": "P2601",
            "start": "2026-01-01",
            "end": "2026-01-31",
            "end_ts": _ms("2026-01-31 15:00"),
        }]


class _AutoCloseBeforeLastTradeProduct(_TermProduct):
    def get_contract_list(self, start_date=None, end_date=None):
        return [{
            "uid": "FB2603.DCE",
            "contract": "FB2603",
            "start": "2025-11-21",
            "end": "2026-02-02",
            "end_ts": _ms("2026-02-02 00:00"),
            "auto_close_date": "2026-01-28",
            "last_trade_date": "2026-03-02",
            "delivery_date": "2026-03-05",
        }]


class _CoverageOnlyTwoContractTermProduct(_TermProduct):
    def get_contract_list(self, start_date=None, end_date=None):
        return [
            {
                "uid": "P2601.DCE",
                "contract": "P2601",
                "start": "2026-01-01",
                "end": "2026-01-31",
                "end_ts": _ms("2026-01-31 15:00"),
            },
            {
                "uid": "P2602.DCE",
                "contract": "P2602",
                "start": "2026-01-20",
                "end": "2026-02-28",
                "end_ts": _ms("2026-02-28 15:00"),
            },
        ]


class _CountingTermProduct(_TermProduct):
    def __init__(self) -> None:
        self.calls = 0

    def get_contract_list(self, start_date=None, end_date=None):
        self.calls += 1
        return super().get_contract_list(start_date=start_date, end_date=end_date)


def test_term_structure_registers_force_close_event_before_expiry():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    axis = pd.date_range("2026-01-01 09:00", "2026-01-30 15:00", freq="1D", tz="Asia/Shanghai")
    account.market_data_store.current_prices_table = pd.DataFrame({"FB2603.DCE": range(len(axis))}, index=axis)
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_force_close_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-29 15:00", tz="Asia/Shanghai")
    assert captured[0].payload["kind"] == "force_close"
    assert captured[0].payload["notice_type"] == "force_close"
    assert captured[0].payload["contract_object"] == _Contract("P2601.DCE")


def test_force_close_notice_uses_last_trade_date_not_auto_close_or_row_end():
    strategy = Strategy(alias="A")
    product = _AutoCloseBeforeLastTradeProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_force_close_notices(account, ctx)
    queue.run_until_drained()

    assert captured == []


def test_term_structure_expands_shared_product_once_across_strategies():
    s1 = Strategy(alias="A1")
    s2 = Strategy(alias="A2")
    product = _CountingTermProduct()
    account = BacktestRunState(strategy_configs={
        s1: StrategyConfig(strategy=s1, field_values={
            RunWindowModule.start_date: "2026-01-01",
            RunWindowModule.start_time: "09:00",
            RunWindowModule.end_date: "2026-02-05",
            RunWindowModule.end_time: "15:00",
        }),
        s2: StrategyConfig(strategy=s2, field_values={
            RunWindowModule.start_date: "2026-01-01",
            RunWindowModule.start_time: "09:00",
            RunWindowModule.end_date: "2026-02-05",
            RunWindowModule.end_time: "15:00",
        }),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(s1))
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({s1, s2}))
    ctx.set_for(ProductSelectionModule.products, s1, frozenset({product}))
    ctx.set_for(ProductSelectionModule.products, s2, frozenset({product}))

    _expand_term_structure(account, ctx)

    s1_metadata = ctx.get_for(TermStructureExpandModule.contract_metadata, s1)
    s2_metadata = ctx.get_for(TermStructureExpandModule.contract_metadata, s2)
    assert product.calls == 1
    assert s1_metadata == s2_metadata
    assert s1_metadata[0] is not s2_metadata[0]


def test_term_structure_does_not_treat_coverage_end_as_lifecycle_date(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_live_lookup", lambda exchange, key: None)
    strategy = Strategy(alias="A")
    product = _CoverageOnlyTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_force_close_notices(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured == []


def test_auto_mode_uses_local_cnfutures_coverage_inference_for_ended_contracts(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_live_lookup", lambda exchange, key: None)
    strategy = Strategy(alias="A")
    product = _CoverageOnlyTwoContractTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                EngineModule.engine_mode: "auto",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "0d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-02-02 15:00", tz="Asia/Shanghai"),
    ])
    account.market_data_store.raw_prices_table = pd.DataFrame({
        _Contract("P2601.DCE"): [1.0, 1.0, None],
        _Contract("P2602.DCE"): [None, 2.0, 2.0],
    }, index=idx)
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert {item.payload["contract_object"] for item in captured} == {_Contract("P2601.DCE")}
    assert captured[0].timestamp == pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai")
    assert captured[0].payload["contract_object"] == _Contract("P2601.DCE")
    assert captured[0].payload["lifecycle_source"] == "LocalCNFutures coverage inference"
    assert captured[0].payload["lifecycle_source_type"] == "inference"
    assert captured[0].payload["lifecycle_source_function"] == "sources.LocalCNFutures.lifecycle.infer_contract_end_from_coverage"
    rows = [
        row for row in account.runtime_info_rows
        if row.get("code") == "term_structure_lifecycle_inference_fallback"
    ]
    assert len(rows) == 1
    assert rows[0]["details"]["contract"] == "P2601.DCE"
    assert rows[0]["details"]["source"] == "authoritative_lifecycle"
    assert rows[0]["details"]["fallback"] == "LocalCNFutures coverage inference"


def test_exact_mode_also_uses_local_cnfutures_coverage_inference_as_last_resort(monkeypatch):
    # exact mode has no authoritative source anywhere for this contract, so it
    # falls through to the same LocalCNFutures coverage inference as auto/custom
    # instead of raising — coverage inference is a universal last resort now,
    # but ONLY when it can conclusively resolve "ended" (a later peer contract
    # still has data after this one goes quiet). Tested at the row level
    # directly: a full _register_rollover_notices sweep would also process the
    # still-active peer (P2602), which coverage inference cannot resolve
    # either way and which exact mode must legitimately raise on — that's
    # covered separately by test_exact_mode_raises_when_coverage_inference_is_inconclusive.
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_live_lookup", lambda exchange, key: None)

    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-02-02 15:00", tz="Asia/Shanghai"),
    ])
    account = BacktestRunState(strategy_configs={})
    account.market_data_store.raw_prices_table = pd.DataFrame({
        _Contract("P2601.DCE"): [1.0, 1.0, None],
        _Contract("P2602.DCE"): [None, 2.0, 2.0],
    }, index=idx)
    ended_row = {"product": "P.DCE", "contract": "P2601", "uid": "P2601.DCE"}
    peer_row = {"product": "P.DCE", "contract": "P2602", "uid": "P2602.DCE"}

    ts = term_structure._event_timestamp_from_row(
        ended_row, offset=pd.Timedelta(0), state=account,
        peer_rows=[ended_row, peer_row], engine_mode="exact",
    )

    assert ts == pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai")
    assert ended_row["lifecycle_source"] == "LocalCNFutures coverage inference"
    assert ended_row["lifecycle_source_type"] == "inference"
    assert ended_row["lifecycle_source_function"] == "sources.LocalCNFutures.lifecycle.infer_contract_end_from_coverage"
    rows = [
        row for row in account.runtime_info_rows
        if row.get("code") == "term_structure_lifecycle_inference_fallback"
    ]
    assert len(rows) == 1
    assert rows[0]["details"]["contract"] == "P2601.DCE"


def test_exact_mode_uses_akshare_authoritative_lifecycle_when_available(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {
        "P2601": {
            "lifecycle_source_type": "local_db",
            "lifecycle_exchange": "DCE",
            "lifecycle_source_function": "futures_contract_info_dce",
            "open_date": "2025-01-15",
            "last_trade_date": "2026-01-14",
            "notice_date": None,
            "delivery_date": "2026-01-19",
            "lifecycle_source": "AKShare DCE contract lifecycle",
        },
    })
    strategy = Strategy(alias="A")
    product = _CoverageOnlyTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                EngineModule.engine_mode: "exact",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "0d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].payload["lifecycle_source_type"] == "local_db"
    assert captured[0].payload["lifecycle_source_function"] == "futures_contract_info_dce"
    assert captured[0].payload["lifecycle_source"] == "AKShare DCE contract lifecycle"
    assert captured[0].timestamp == pd.Timestamp("2026-01-14 00:00", tz="Asia/Shanghai")


def test_akshare_lifecycle_overrides_openctp_on_conflicting_fields(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {
        "P2601": {
            "lifecycle_source_type": "local_db",
            "lifecycle_exchange": "DCE",
            "lifecycle_source_function": "src_openctp_cnfutures_contract_specs",
            "open_date": "2025-01-10",
            "last_trade_date": "2026-01-20",
            "delivery_date": "2026-01-25",
            "inst_life_phase": "0",
            "lifecycle_source": "OpenCTP latest contract snapshot",
        },
    })
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {
        "P2601": {
            "lifecycle_source_type": "local_db",
            "lifecycle_exchange": "DCE",
            "lifecycle_source_function": "futures_contract_info_dce",
            "open_date": "2025-01-15",
            "last_trade_date": "2026-01-14",
            "notice_date": None,
            "delivery_date": "2026-01-19",
            "lifecycle_source": "AKShare DCE contract lifecycle",
        },
    })
    row = term_structure._with_authoritative_lifecycle_fields({
        "product": "P.DCE",
        "contract": "P2601",
        "uid": "P2601.DCE",
    })
    assert row["last_trade_date"] == "2026-01-14"
    assert row["delivery_date"] == "2026-01-19"
    assert row["lifecycle_source_type"] == "local_db"
    assert row["lifecycle_source_function"] == "futures_contract_info_dce"
    assert row["lifecycle_source"] == "AKShare DCE contract lifecycle"
    assert row["inst_life_phase"] == "0"


def test_row_exchange_maps_local_suffix_to_akshare_code():
    assert term_structure._row_exchange({"contract": "P2601.DCE"}) == "DCE"
    assert term_structure._row_exchange({"contract": "SR409.CZC"}) == "CZCE"
    assert term_structure._row_exchange({"uid": "si2411.GFE"}) == "GFEX"
    assert term_structure._row_exchange({"contract": "P2601"}) is None


def test_akshare_lifecycle_duplicate_contract_prefers_local_product_exchange():
    out: dict[str, dict[str, object]] = {}
    product_exchange = {"EC": "INE"}

    term_structure._select_akshare_lifecycle_spec(
        out,
        "EC2602",
        {
            "lifecycle_exchange": "INE",
            "last_trade_date": "2026-02-23",
            "lifecycle_source": "AKShare INE contract lifecycle",
        },
        "EC",
        product_exchange,
    )
    term_structure._select_akshare_lifecycle_spec(
        out,
        "EC2602",
        {
            "lifecycle_exchange": "SHFE",
            "last_trade_date": "2026-02-23",
            "lifecycle_source": "AKShare SHFE contract lifecycle",
        },
        "EC",
        product_exchange,
    )

    assert out["EC2602"]["lifecycle_exchange"] == "INE"
    assert out["EC2602"]["lifecycle_source"] == "AKShare INE contract lifecycle"


def test_akshare_lifecycle_specs_include_local_store_source_metadata(monkeypatch):
    term_structure._akshare_lifecycle_specs_by_instrument.cache_clear()
    monkeypatch.setattr(term_structure, "_local_cnfutures_product_exchange_by_code", lambda: {"EC": "INE"})
    monkeypatch.setattr("sources.ContractLifecycle.lifecycle.read_contract_lifecycle", lambda: pd.DataFrame([{
        "exchange": "INE",
        "product_code": "EC",
        "contract_code": "EC2602",
        "list_date": "2025-02-25",
        "last_trading_date": "2026-02-23",
        "delivery_notice_date": None,
        "last_delivery_date": "2026-02-23",
        "source_query_date": "20250508",
        "source_function": "futures_contract_info_ine",
        "fetched_at": 123.0,
    }]))

    specs = term_structure._akshare_lifecycle_specs_by_instrument()

    assert specs["EC2602"]["lifecycle_source_type"] == "local_db"
    assert specs["EC2602"]["lifecycle_exchange"] == "INE"
    assert specs["EC2602"]["lifecycle_source_function"] == "futures_contract_info_ine"
    assert specs["EC2602"]["lifecycle_source_query_date"] == "20250508"
    assert specs["EC2602"]["lifecycle_fetched_at"] == 123.0


def test_lifecycle_specs_label_dce_official_portal_source(monkeypatch):
    term_structure._akshare_lifecycle_specs_by_instrument.cache_clear()
    monkeypatch.setattr(term_structure, "_local_cnfutures_product_exchange_by_code", lambda: {"P": "DCE"})
    monkeypatch.setattr("sources.ContractLifecycle.lifecycle.read_contract_lifecycle", lambda: pd.DataFrame([{
        "exchange": "DCE",
        "product_code": "P",
        "contract_code": "P2601",
        "list_date": "2025-01-15",
        "last_trading_date": "2026-01-14",
        "delivery_notice_date": None,
        "last_delivery_date": "2026-01-19",
        "source_query_date": None,
        "source_function": "official_dce_portal_contract_info",
        "fetched_at": 123.0,
    }]))

    specs = term_structure._akshare_lifecycle_specs_by_instrument()

    assert specs["P2601"]["lifecycle_source_function"] == "official_dce_portal_contract_info"
    assert specs["P2601"]["lifecycle_source"] == "DCE official portal contract lifecycle"


def test_lifecycle_specs_label_local_dayk_coverage_source(monkeypatch):
    term_structure._akshare_lifecycle_specs_by_instrument.cache_clear()
    monkeypatch.setattr(term_structure, "_local_cnfutures_product_exchange_by_code", lambda: {"M": "DCE"})
    monkeypatch.setattr("sources.ContractLifecycle.lifecycle.read_contract_lifecycle", lambda: pd.DataFrame([{
        "exchange": "DCE",
        "product_code": "M",
        "contract_code": "M2409",
        "list_date": "2023-09-15",
        "last_trading_date": "2024-09-13",
        "delivery_notice_date": None,
        "last_delivery_date": None,
        "source_query_date": None,
        "source_function": "local_cnfutures_dayk_coverage",
        "fetched_at": 123.0,
    }]))

    specs = term_structure._akshare_lifecycle_specs_by_instrument()

    assert specs["M2409"]["lifecycle_source_function"] == "local_cnfutures_dayk_coverage"
    assert specs["M2409"]["lifecycle_source"] == "LocalCNFutures daily bars coverage contract lifecycle"


def test_lifecycle_specs_label_rule_calendar_derived_source(monkeypatch):
    term_structure._akshare_lifecycle_specs_by_instrument.cache_clear()
    monkeypatch.setattr(term_structure, "_local_cnfutures_product_exchange_by_code", lambda: {"M": "DCE"})
    monkeypatch.setattr("sources.ContractLifecycle.lifecycle.read_contract_lifecycle", lambda: pd.DataFrame([{
        "exchange": "DCE",
        "product_code": "M",
        "contract_code": "M2409",
        "list_date": "2023-09-15",
        "last_trading_date": "2024-09-13",
        "delivery_notice_date": None,
        "last_delivery_date": "2024-09-20",
        "source_query_date": None,
        "source_function": "exchange_rule_dayk_calendar_derived",
        "fetched_at": 123.0,
    }]))

    specs = term_structure._akshare_lifecycle_specs_by_instrument()

    assert specs["M2409"]["lifecycle_source_function"] == "exchange_rule_dayk_calendar_derived"
    assert specs["M2409"]["lifecycle_source"] == "DCE product rule + trading calendar derived contract lifecycle"


def test_exact_engine_mode_rejects_derived_lifecycle_source(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {
        "M2409": {
            "lifecycle_source_type": "local_db",
            "lifecycle_exchange": "DCE",
            "lifecycle_source_function": "exchange_rule_dayk_calendar_derived",
            "open_date": "2023-09-15",
            "last_trade_date": "2024-09-13",
            "delivery_date": "2024-09-20",
            "lifecycle_source": "Exchange product rule/listing source plus LocalCNFutures exchange trading calendar",
        }
    })

    with pytest.raises(ValueError, match="exact engine_mode does not accept derived lifecycle metadata"):
        term_structure._with_authoritative_lifecycle_fields({
            "product": "M.DCE",
            "contract": "M2409",
            "uid": "M2409.DCE",
        }, engine_mode="exact")


def test_auto_engine_mode_allows_derived_lifecycle_source(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {
        "M2409": {
            "lifecycle_source_type": "local_db",
            "lifecycle_exchange": "DCE",
            "lifecycle_source_function": "exchange_rule_dayk_calendar_derived",
            "open_date": "2023-09-15",
            "last_trade_date": "2024-09-13",
            "delivery_date": "2024-09-20",
            "lifecycle_source": "Exchange product rule/listing source plus LocalCNFutures exchange trading calendar",
        }
    })

    row = term_structure._with_authoritative_lifecycle_fields({
        "product": "M.DCE",
        "contract": "M2409",
        "uid": "M2409.DCE",
    }, engine_mode="auto")

    assert row["lifecycle_source_function"] == "exchange_rule_dayk_calendar_derived"
    assert row["delivery_date"] == "2024-09-20"


def test_term_structure_lifecycle_flows_declare_engine_mode_input():
    for flow in (
        TermStructureExpandModule.expand_term_structure,
        TermStructureExpandModule.resolve_tradable_target_weights,
        DeliveryForceCloseModule.register_force_close_notices,
        RolloverModule.register_rollover_notices,
    ):
        assert EngineModule.engine_mode in flow.inputs


def test_akshare_live_lookup_is_attempted_once_per_exchange_and_persists(monkeypatch):
    monkeypatch.setattr(term_structure, "_akshare_live_cache", {})
    monkeypatch.setattr(term_structure, "_akshare_live_attempted", set())
    calls: list[str] = []

    def fake_fetch_and_store_live(exchange, **kwargs):
        calls.append(exchange)
        return [{
            "contract_code": "SI2411",
            "source_function": "futures_contract_info_gfex",
            "source_query_date": None,
            "list_date": "2022-12-22",
            "last_trading_date": "2024-11-15",
            "delivery_notice_date": None,
            "last_delivery_date": "2024-11-19",
        }]

    monkeypatch.setattr("sources.ContractLifecycle.lifecycle.fetch_and_store_live", fake_fetch_and_store_live)

    first = term_structure._akshare_live_lookup("GFEX", "SI2411")
    second = term_structure._akshare_live_lookup("GFEX", "SI2411")
    missing = term_structure._akshare_live_lookup("GFEX", "SI2412")

    assert first == {
        "lifecycle_source_type": "live_official_or_akshare_then_local_db",
        "lifecycle_exchange": "GFEX",
        "lifecycle_source_function": "futures_contract_info_gfex",
        "lifecycle_source_query_date": None,
        "lifecycle_fetched_at": None,
        "open_date": "2022-12-22",
        "last_trade_date": "2024-11-15",
        "notice_date": None,
        "delivery_date": "2024-11-19",
        "lifecycle_source": "AKShare GFEX live lookup",
    }
    assert second == first
    assert missing is None
    assert calls == ["GFEX"]


def test_with_authoritative_lifecycle_fields_falls_back_to_akshare_live_lookup(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_live_cache", {})
    monkeypatch.setattr(term_structure, "_akshare_live_attempted", set())
    monkeypatch.setattr(term_structure, "_akshare_live_lookup_enabled", lambda: True)

    def fake_fetch_and_store_live(exchange, **kwargs):
        return [{
            "contract_code": "SI2411",
            "source_function": "futures_contract_info_gfex",
            "list_date": "2022-12-22",
            "last_trading_date": "2024-11-15",
            "delivery_notice_date": None,
            "last_delivery_date": "2024-11-19",
        }]

    monkeypatch.setattr("sources.ContractLifecycle.lifecycle.fetch_and_store_live", fake_fetch_and_store_live)

    row = term_structure._with_authoritative_lifecycle_fields({
        "product": "SI.GFE",
        "contract": "SI2411",
        "uid": "SI2411.GFE",
    })
    assert row["lifecycle_source_type"] == "live_official_or_akshare_then_local_db"
    assert row["lifecycle_source_function"] == "futures_contract_info_gfex"
    assert row["last_trade_date"] == "2024-11-15"
    assert row["lifecycle_source"] == "AKShare GFEX live lookup"


def test_akshare_live_lookup_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv(term_structure._AKSHARE_LIVE_LOOKUP_ENV, raising=False)
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        term_structure, "_akshare_live_lookup",
        lambda exchange, key: calls.append((exchange, key)) or None,
    )

    term_structure._with_authoritative_lifecycle_fields({
        "product": "SI.GFE",
        "contract": "SI2411",
        "uid": "SI2411.GFE",
    })

    assert calls == [("GFEX", "SI2411")]


def test_akshare_live_lookup_can_be_disabled_via_env(monkeypatch):
    monkeypatch.setenv(term_structure._AKSHARE_LIVE_LOOKUP_ENV, "0")
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        term_structure, "_akshare_live_lookup",
        lambda exchange, key: calls.append((exchange, key)) or None,
    )

    row = term_structure._with_authoritative_lifecycle_fields({
        "product": "SI.GFE",
        "contract": "SI2411",
        "uid": "SI2411.GFE",
    })

    assert calls == []
    assert "last_trade_date" not in row or row.get("last_trade_date") in (None, "")


def test_exact_mode_raises_when_coverage_inference_is_inconclusive(monkeypatch):
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_live_lookup", lambda exchange, key: None)
    strategy = Strategy(alias="A")
    # No raw_prices_table at all: coverage inference has nothing to check
    # against, so it cannot conclude the contract has stopped trading either.
    product = _CoverageOnlyTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                EngineModule.engine_mode: "exact",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    with pytest.raises(ValueError, match="could not determine whether"):
        _register_force_close_notices(account, ctx)


def test_term_structure_force_close_offset_accepts_intraday_window():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "5min",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_force_close_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-31 14:55", tz="Asia/Shanghai")


def test_force_close_event_emits_reverse_order_for_existing_position():
    strategy = Strategy(alias="A")
    contract = _Contract("P2601.DCE")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy),
    })
    ledger = account.ledger_for_strategy(strategy)
    ledger.set(LedgerModule.positions, {contract: ProductPosition(quantity=3)})
    queue = EventQueue()
    order_events: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER, lambda batch: order_events.extend(batch))
    ts = pd.Timestamp("2026-01-29 15:00")
    draft = EventDraft(EventKind.TRADE_INTENT, ts, strategy, payload={
        "kind": "force_close",
        "notice_type": "force_close",
        "contract_object": contract,
    })
    ctx = FlowContext(
        timestamp=ts,
        event_queue=queue,
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: [draft]},
    )

    _handle_delivery_force_close_notice(account, ctx)
    queue.run_until_drained()

    assert len(order_events) == 1
    order = order_events[0].payload
    assert order.instrument == contract
    assert order.quantity == -3
    assert order.get("reason") == "term_structure_force_close"
    assert order.get("price_timestamp") == ts


def test_force_close_order_dispatch_fills_and_clears_position_before_settlement():
    strategy = Strategy(alias="A")
    contract = _Contract("P2601.DCE")
    flow_names = frozenset({
        "handle_delivery_force_close_notice",
        "lookup_current_prices_on_order",
        "resolve_execution_price",
        "apply_order_fill",
    })
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, active_flow_names=flow_names),
    })
    ledger = account.ledger_for_strategy(strategy)
    ledger.set(LedgerModule.positions, {contract: ProductPosition(quantity=3)})
    set_cash_for_ledger_pool(
        account,
        ledger,
        DataMoney.from_major(1000.0, currency="CNY", use_minor_units=False),
    )
    ts = pd.Timestamp("2026-01-31 00:00", tz="Asia/Shanghai")
    account.market_data_store.current_prices_table = pd.DataFrame(
        {contract: [10.0]},
        index=pd.DatetimeIndex([ts]),
    )
    account.market_data_store.market_price_tables = {
        "open": pd.DataFrame({contract: [10.0]}, index=pd.DatetimeIndex([ts])),
    }

    registry = FlowRegistry()
    for flow in (
        DeliveryForceCloseModule.handle_delivery_force_close_notice,
        MarketDataModule.lookup_current_prices_on_order,
        OrderExecutionModule.resolve_execution_price,
        LedgerModule.apply_order_fill,
    ):
        registry.register_flow(flow)
    groups = sort_and_validate(registry.resolve())
    queue = EventQueue()
    queue.set_dispatcher(
        EventKind.TRADE_INTENT,
        make_dispatcher(groups[(DeliveryForceCloseModule.handle_delivery_force_close_notice.phase, EventKind.TRADE_INTENT)], account, queue),
    )
    order_events: list[EventDraft] = []
    order_dispatcher = make_dispatcher(groups[(LedgerModule.apply_order_fill.phase, EventKind.ORDER)], account, queue)

    def _capture_and_dispatch_order(batch):
        order_events.extend(batch)
        order_dispatcher(batch)

    queue.set_dispatcher(EventKind.ORDER, _capture_and_dispatch_order)
    queue.push_event(EventDraft(EventKind.TRADE_INTENT, ts, strategy, payload={
        "kind": "force_close",
        "notice_type": "force_close",
        "contract_object": contract,
    }))

    queue.run_until_drained()

    assert len(order_events) == 1
    order = order_events[0].payload
    assert order.get("reason") == "term_structure_force_close"
    assert order.get("price_timestamp") == ts
    assert order.status.value == "filled"
    assert ledger.get(LedgerModule.positions)[contract].quantity == 0


def test_signal_target_weights_map_abstract_product_to_current_contract():
    strategy = Strategy(alias="A")
    product = _TwoContractTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-10 09:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    ctx.set_for(GroupMembershipModule.target_weights, strategy, {product: 1.0})
    _resolve_tradable_target_weights(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, strategy)
    assert weights == {_Contract("P2601.DCE"): 1.0}


def test_signal_target_weights_drop_expired_last_contract_after_force_close_time():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "0d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    pre_replay_ctx = FlowContext(
        timestamp=None,
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    pre_replay_ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))
    _expand_term_structure(account, pre_replay_ctx)

    per_event_ctx = FlowContext(
        timestamp=pd.Timestamp("2026-02-01 09:01", tz="Asia/Shanghai"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    per_event_ctx.set_for(GroupMembershipModule.target_weights, strategy, {product: 1.0})
    _resolve_tradable_target_weights(account, per_event_ctx)

    assert per_event_ctx.get_for(GroupMembershipModule.target_weights, strategy) == {}


def test_signal_target_weights_resolve_across_separate_pre_replay_and_per_event_contexts():
    """Production never shares one FlowContext between expand_term_structure
    (PRE_REPLAY) and resolve_tradable_target_weights (PER_EVENT/SIGNAL) --
    scheduler.make_dispatcher constructs a brand-new FlowContext per event
    batch, so PRE_REPLAY's ctx.set_for(contract_metadata, ...) is invisible
    to any PER_EVENT flow's ctx.get_for. Only state.term_structure_store
    (persisted on BacktestRunState, not ctx) survives that boundary. This
    test uses two independent FlowContext instances -- not one shared ctx
    like the tests above -- to prove resolve_tradable_target_weights reads
    from the persisted store and would actually roll in a real replay run."""
    strategy = Strategy(alias="A")
    product = _TwoContractTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))

    pre_replay_ctx = FlowContext(
        timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}),
    )
    pre_replay_ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))
    _expand_term_structure(account, pre_replay_ctx)

    per_event_ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-26 15:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    per_event_ctx.set_for(GroupMembershipModule.target_weights, strategy, {product: 1.0})
    _resolve_tradable_target_weights(account, per_event_ctx)

    weights = per_event_ctx.get_for(GroupMembershipModule.target_weights, strategy)
    assert weights == {_Contract("P2602.DCE"): 1.0}


def test_resolve_tradable_target_weights_caches_lifecycle_inference_across_signal_events(monkeypatch):
    """Now that resolve_tradable_target_weights actually runs on every SIGNAL
    event (the ctx-boundary bug fixed above), its fallback lifecycle
    inference (LocalCNFutures coverage inference, which scans the whole raw
    price table) must not be recomputed from scratch every single event --
    that's the perf regression a real backtest hit. infer_contract_end_from_coverage
    is deterministic given (row, offset), so TermStructureStore.event_timestamp_cache
    should make it run at most once per row per offset, no matter how many
    SIGNAL events fire."""
    monkeypatch.setattr(term_structure, "_openctp_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_lifecycle_specs_by_instrument", lambda: {})
    monkeypatch.setattr(term_structure, "_akshare_live_lookup", lambda exchange, key: None)

    import sources.LocalCNFutures.lifecycle as lifecycle_module

    call_count = 0
    real_infer = lifecycle_module.infer_contract_end_from_coverage

    def _counting_infer(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_infer(*args, **kwargs)

    # _local_cnfutures_inferred_lifecycle does a local
    # `from sources.LocalCNFutures.lifecycle import infer_contract_end_from_coverage`
    # inside the function body, re-resolved on every call -- must patch the
    # source module's attribute, not term_structure's (it never imports this
    # name at module scope).
    monkeypatch.setattr(lifecycle_module, "infer_contract_end_from_coverage", _counting_infer)

    strategy = Strategy(alias="A")
    product = _CoverageOnlyTwoContractTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                EngineModule.engine_mode: "auto",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-02-02 15:00", tz="Asia/Shanghai"),
    ])
    account.market_data_store.raw_prices_table = pd.DataFrame({
        _Contract("P2601.DCE"): [1.0, 1.0, None],
        _Contract("P2602.DCE"): [None, 2.0, 2.0],
    }, index=idx)

    pre_replay_ctx = FlowContext(
        timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}),
    )
    pre_replay_ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))
    _expand_term_structure(account, pre_replay_ctx)

    # Simulate 20 SIGNAL events at distinct timestamps, each independently
    # resolving the same product's target weight -- exactly what a real
    # backtest's PER_EVENT/SIGNAL dispatch does, one fresh FlowContext per
    # event (see test above for why that matters).
    for i in range(20):
        per_event_ctx = FlowContext(
            timestamp=pd.Timestamp("2026-01-20 09:01") + pd.Timedelta(days=i),
            event_queue=EventQueue(),
            active_strategies=frozenset({strategy}),
        )
        per_event_ctx.set_for(GroupMembershipModule.target_weights, strategy, {product: 1.0})
        _resolve_tradable_target_weights(account, per_event_ctx)

    # 2 contract rows x at most 2 offsets (force_close + rollover) each = a
    # small constant ceiling, independent of how many SIGNAL events fire --
    # without the cache this scales linearly with the 20 events below.
    assert call_count <= 4


def test_signal_target_weights_roll_to_next_contract_after_rollover_notice_time():
    strategy = Strategy(alias="A")
    product = _TwoContractTermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                DeliveryForceCloseModule.force_close_before_expiry: "2d",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ctx = FlowContext(
        timestamp=pd.Timestamp("2026-01-26 15:01"),
        event_queue=EventQueue(),
        active_strategies=frozenset({strategy}),
    )
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    ctx.set_for(GroupMembershipModule.target_weights, strategy, {product: 1.0})
    _resolve_tradable_target_weights(account, ctx)

    weights = ctx.get_for(GroupMembershipModule.target_weights, strategy)
    assert weights == {_Contract("P2602.DCE"): 1.0}


def test_rollover_module_registers_rollover_notice_independently():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-26 15:00", tz="Asia/Shanghai")
    assert captured[0].payload["notice_type"] == "rollover"
    assert captured[0].payload["notice_reason"] == "date_before_expiry"


def test_rollover_notice_emits_close_and_open_orders_for_existing_position():
    strategy = Strategy(alias="A")
    product = _TwoContractTermProduct()
    old_contract = _Contract("P2601.DCE")
    new_contract = _Contract("P2602.DCE")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ledger = account.ledger_for_strategy(strategy)
    ledger.set(LedgerModule.positions, {old_contract: ProductPosition(quantity=3)})

    queue = EventQueue()
    order_events: list[EventDraft] = []
    queue.set_dispatcher(EventKind.ORDER, lambda batch: order_events.extend(batch))
    expand_ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    expand_ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))
    _expand_term_structure(account, expand_ctx)

    ts = pd.Timestamp("2026-01-26 15:00")
    draft = EventDraft(EventKind.TRADE_INTENT, ts, strategy, payload={
        "kind": "rollover",
        "notice_type": "rollover",
        "notice_reason": "date_before_expiry",
        "product": "P.DCE",
        "contract_object": old_contract,
    })
    ctx = FlowContext(
        timestamp=ts,
        event_queue=queue,
        active_strategies=frozenset({strategy}),
        drafts_by_strategy={strategy: [draft]},
    )

    _handle_rollover_notice(account, ctx)
    queue.run_until_drained()

    assert len(order_events) == 2
    orders = [event.payload for event in order_events]
    assert [(order.instrument, order.quantity) for order in orders] == [
        (old_contract, -3),
        (new_contract, 3),
    ]
    assert orders[0].get("reason") == "term_structure_rollover_close"
    assert orders[1].get("reason") == "term_structure_rollover_open"


def test_rollover_day_window_uses_trading_axis_not_calendar_days():
    strategy = Strategy(alias="A")
    product = _TermProduct()
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(
            strategy=strategy,
            field_values={
                RunWindowModule.start_date: "2026-01-01",
                RunWindowModule.start_time: "09:00",
                RunWindowModule.end_date: "2026-02-05",
                RunWindowModule.end_time: "15:00",
                RunWindowModule.timezone: "Asia/Shanghai",
                RolloverModule.rollover_policy: "date_before_expiry",
                RolloverModule.rollover_before_expiry: "5d",
            },
        ),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    axis = pd.DatetimeIndex([
        pd.Timestamp("2026-01-21 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-22 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-23 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-27 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-28 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-29 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-30 15:00", tz="Asia/Shanghai"),
        pd.Timestamp("2026-01-31 15:00", tz="Asia/Shanghai"),
    ])
    account.market_data_store.current_prices_table = pd.DataFrame({"P2601.DCE": range(len(axis))}, index=axis)
    queue = EventQueue()
    captured: list[EventDraft] = []
    queue.set_dispatcher(EventKind.TRADE_INTENT, lambda batch: captured.extend(batch))
    ctx = FlowContext(timestamp=None, event_queue=queue, active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _register_rollover_notices(account, ctx)
    queue.run_until_drained()

    assert captured
    assert captured[0].timestamp == pd.Timestamp("2026-01-23 15:00", tz="Asia/Shanghai")
