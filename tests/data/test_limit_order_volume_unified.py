from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

from sources.FieldHistory.views.LimitOrderVolume import build_unified_frame, build_unified_provider
from tools.data.field_history import FieldHistoryProvider, TimestampTradingDayResolver


ROOT = Path(__file__).resolve().parents[2]


def _load_market_data_module():
    module_name = "market_data_module_test"
    path = ROOT / "tools/testers/backtest/modules/market_data.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _agent_limit_order_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "provider": "Agent:DCE",
            "source_key": "agent/DCE/event-1",
            "instrument": "BZ",
            "instrument_label": "纯苯",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-10",
            "effective_timestamp": "2026-03-09 21:00:00",
            "value": "4",
            "value_type": "int",
            "contract_codes": json.dumps(["2604"]),
            "source_url": "http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html",
            "source_date": "2026-06-29T12:00:00+08:00",
            "source_notice_id": "大商所发〔2026〕74号",
            "raw_note": "BZ2604、BZ2605、BZ2606合约交易指令每次最小开仓下单数量调整为4手",
        },
        {
            "provider": "Agent:ManualAudit",
            "source_key": "agent/ManualAudit/event-2",
            "instrument": "BZ",
            "instrument_label": "纯苯",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-10",
            "effective_timestamp": "2026-03-09 21:00:00",
            "value": "4",
            "value_type": "int",
            "contract_codes": json.dumps(["2604"]),
            "source_url": "https://audit.example/bz",
            "source_date": "2026-06-29T12:05:00+08:00",
            "source_notice_id": "大商所发〔2026〕74号",
            "raw_note": "人工复核同一公告",
        },
    ])


def test_limit_order_volume_view_deduplicates_agent_events_and_keeps_sources() -> None:
    unified = build_unified_frame(_agent_limit_order_frame())

    assert len(unified) == 1
    row = unified.iloc[0]
    assert row["source_count"] == 2
    assert json.loads(row["providers"]) == ["Agent:DCE", "Agent:ManualAudit"]
    assert json.loads(row["source_notice_ids"]) == ["大商所发〔2026〕74号"]


def test_limit_order_volume_unified_provider_resolves_contract_scope() -> None:
    provider = build_unified_provider(build_unified_frame(_agent_limit_order_frame()))

    value = provider.resolve_at(
        "BZ2604.DCE",
        "MinLimitOrderVolume",
        pd.Timestamp("2026-03-10 09:01:00"),
        trading_day_resolver=TimestampTradingDayResolver({
            pd.Timestamp("2026-03-10 09:01:00"): pd.Timestamp("2026-03-10"),
        }),
    )

    assert value.value == 4
    assert value.contract_code == "2604"


def test_market_data_limit_order_fields_use_field_history_view(monkeypatch) -> None:
    raw_provider = FieldHistoryProvider.from_records([
        {
            "provider": "raw",
            "source_key": "raw",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-10",
            "value": 1,
            "contract_codes": ["2604"],
        },
    ])
    unified_provider = FieldHistoryProvider.from_records([
        {
            "provider": "Unified",
            "source_key": "unified",
            "instrument": "BZ",
            "instrument_type": "future",
            "field_name": "MinLimitOrderVolume",
            "effective_trading_day": "2026-03-10",
            "value": 4,
            "contract_codes": ["2604"],
        },
    ])

    import sources.FieldHistory.views.Unified as unified_view

    monkeypatch.setattr(unified_view, "load_unified_provider", lambda: unified_provider)

    index = pd.DatetimeIndex([pd.Timestamp("2026-03-10 09:01:00")])
    market_data_module = _load_market_data_module()
    frames = market_data_module.historical_field_frames_for_market_data(
        ["BZ2604.DCE"],
        index,
        provider=raw_provider,
        trading_day_resolver=TimestampTradingDayResolver({
            pd.Timestamp("2026-03-10 09:01:00"): pd.Timestamp("2026-03-10"),
        }),
        field_names=("MinLimitOrderVolume",),
        policy="strict_historical",
    )

    assert frames["MinLimitOrderVolume"].iloc[0, 0] == 4
