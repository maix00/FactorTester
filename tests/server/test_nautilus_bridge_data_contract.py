"""LocalCNFutures -> NT market data clock and identity contracts."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from itertools import islice
from pathlib import Path

import pytest

from server.services.nautilus_bridge.market_data import (
    SHANGHAI,
    DailySettlementRule,
    FuturesContractSpec,
    MarketBar,
    RollMarker,
    daily_clock,
    iter_daily_bars,
    iter_daily_settlement_records,
    iter_minute_bars,
    minute_clock,
    next_open_event_time,
    to_nautilus_bar,
    to_nautilus_daily_settlement,
    to_nautilus_instrument,
    to_nautilus_open_quote,
)
from tests.nautilus_runtime import require_nautilus
from tests.nautilus_source_fixture import resolved_contract_minute_source


def test_minute_source_timestamp_units_are_explicit_or_calendar_validated():
    end = datetime(2024, 1, 2, 9, 31)
    second = 1704159060
    a = minute_clock(end, second, raw_unit="s")
    b = minute_clock(end, second * 1000, raw_unit="validated")
    assert a.interval_end_ns == b.interval_end_ns
    assert a.interval_open_ns == a.interval_end_ns - 60_000_000_000
    assert a.raw_timestamp == second and a.raw_unit == "s"
    assert b.raw_timestamp == second * 1000 and b.raw_unit == "ms"
    with pytest.raises(ValueError, match="disagrees"):
        minute_clock(end, second, raw_unit="ms")
    with pytest.raises(ValueError, match="no unique unit"):
        minute_clock(end, second + 1, raw_unit="validated")


def test_daily_date_requires_explicit_calendar_close_and_not_midnight():
    clock = daily_clock(date(2024, 1, 2),
                        session_open=datetime(2024, 1, 2, 9, 30),
                        session_close=datetime(2024, 1, 2, 15, 15))
    assert datetime.fromtimestamp(clock.interval_end_ns / 1e9, SHANGHAI).strftime("%H:%M") == "15:15"
    assert clock.raw_timestamp is None
    assert clock.raw_trade_time == "2024-01-02"


def _write_daily_term_structure(path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist([{
        "TRADING_DAY": date(2024, 1, 2), "PRODUCT": "T",
        "CONTRACT": "T2403.CFE", "CONTRACT_UID": "CFFEX|F|T|2403",
        "OPEN": 102.9, "HIGH": 103.0, "LOW": 102.8, "CLOSE": 102.95,
        "VOLUME": 1000.0, "OPEN_INTEREST": 180000.0,
        "SETTLEMENT_PRICE": 102.94, "PRE_SETTLEMENT_PRICE": 102.91,
    }]), path)
    return path


def _daily_session(day):
    return (datetime.combine(day, time(9, 30)),
            datetime.combine(day, time(15, 0)))


def test_daily_reader_uses_term_structure_schema_and_exchange_close(tmp_path):
    path = _write_daily_term_structure(tmp_path / "daily.parquet")

    bars = list(iter_daily_bars(
        path, product_codes={"T"}, session_for_day=_daily_session,
        contract_uids={"CFFEX|F|T|2403"},
    ))
    assert len(bars) == 1
    assert bars[0].clock.raw_timestamp is None
    assert bars[0].clock.raw_unit is None
    assert bars[0].settlement_price == Decimal("102.94")
    assert datetime.fromtimestamp(
        bars[0].clock.interval_end_ns / 1e9, SHANGHAI,
    ).strftime("%Y-%m-%d %H:%M") == "2024-01-02 15:00"


def test_official_daily_settlement_requires_frozen_rule_and_calendar(tmp_path):
    path = _write_daily_term_structure(tmp_path / "daily.parquet")
    rule = DailySettlementRule(
        eligible=True, price_field="settlement_price", close_time=time(15, 0),
        timezone="Asia/Shanghai", authority="exchange_notice",
        source_key="CFFEX/settlement/2024-01-02",
        rule_set_ref="sha256:official-rule-set-v1",
    )
    record, = iter_daily_settlement_records(
        path,
        instrument_ids_by_contract_uid={"CFFEX|F|T|2403": "T2403.CFFEX"},
        product_codes={"T"},
        rule_for_day=lambda uid, day: rule,
        session_for_day=lambda uid, day: _daily_session(day),
    )
    assert record.settlement_price == Decimal("102.94")
    assert record.timestamp_ns == daily_clock(
        date(2024, 1, 2), session_open=datetime(2024, 1, 2, 9, 30),
        session_close=datetime(2024, 1, 2, 15, 0),
    ).interval_end_ns
    with pytest.raises(ValueError, match="exchange close and settlement-rule time disagree"):
        list(iter_daily_settlement_records(
            path,
            instrument_ids_by_contract_uid={"CFFEX|F|T|2403": "T2403.CFFEX"},
            product_codes={"T"}, rule_for_day=lambda uid, day: rule,
            session_for_day=lambda uid, day: (
                datetime(2024, 1, 2, 9, 30), datetime(2024, 1, 2, 15, 15),
            ),
        ))


def test_official_settlement_maps_to_native_daily_settlement_close(tmp_path):
    require_nautilus()
    from nautilus_trader.model import InstrumentCloseType

    spec = FuturesContractSpec(
        instrument_code="T2403", venue="CFFEX", underlying="T",
        price_increment=Decimal("0.005"), price_precision=3,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="synthetic event conversion contract",
        resolved_source=resolved_contract_minute_source(),
    )
    instrument = to_nautilus_instrument(spec)
    record = next(iter_daily_settlement_records(
        _write_daily_term_structure(tmp_path / "daily.parquet"),
        instrument_ids_by_contract_uid={"CFFEX|F|T|2403": "T2403.CFFEX"},
        product_codes={"T"},
        rule_for_day=lambda uid, day: DailySettlementRule(
            True, "settlement_price", time(15, 0), "Asia/Shanghai",
            "exchange_notice", "CFFEX/settlement/2024-01-02",
            "sha256:official-rule-set-v1",
        ),
        session_for_day=lambda uid, day: _daily_session(day),
    ))
    close = to_nautilus_daily_settlement(
        record, instrument=instrument, instrument_spec=spec,
    )
    assert close.close_type == InstrumentCloseType.DAILY_SETTLEMENT
    assert close.ts_event == record.timestamp_ns


def _bar(end_minute: int, code: str = "T2403") -> MarketBar:
    end = datetime(2024, 1, 2, 9, end_minute)
    clock = minute_clock(end, 1704159000 + (end_minute - 30) * 60, raw_unit="s")
    return MarketBar(
        contract_uid=f"CFFEX|F|T|{code[-4:]}", instrument_code=code,
        trading_day=date(2024, 1, 2), clock=clock,
        open=Decimal("102.935"), high=Decimal("102.935"),
        low=Decimal("102.895"), close=Decimal("102.900"),
        volume=Decimal("1314"), open_interest=Decimal("189821"),
        source_path="sample.parquet", row_number=1,
    )


def test_next_open_is_after_prior_signal_and_cannot_share_full_ohlc():
    previous = _bar(31)
    next_bar = _bar(32)
    assert next_open_event_time(next_bar, previous) == previous.clock.available_at_ns + 1
    late_clock = minute_clock(datetime(2024, 1, 2, 9, 31), 1704159060,
                              raw_unit="s", available_delay_ns=2)
    delayed = MarketBar(**{**previous.__dict__, "clock": late_clock})
    with pytest.raises(ValueError, match="precedes prior bar signal"):
        next_open_event_time(next_bar, delayed)


def test_chunked_source_tracks_rolls_and_rejects_nonmonotonic_rows(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    rows = []
    for minute, code in ((31, "T2403"), (32, "T2403"), (33, "T2406")):
        rows.append({
            "trade_time": datetime(2024, 1, 2, 9, minute),
            "trade_timestamp": (1704159000 + (minute - 30) * 60) * 1000,
            "trading_day": datetime(2024, 1, 2),
            "contract_uid": f"CFFEX|F|T|{code[-4:]}", "instrument_id": code,
            "open_price": 102.935, "highest_price": 102.935,
            "lowest_price": 102.895, "close_price": 102.9,
            "volume": 1314.0, "open_interest": 189821.0,
        })
    path = tmp_path / "T.CFE.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path, row_group_size=1)
    events = list(iter_minute_bars(path, batch_size=1, continuous_product="T.CFE"))
    assert [type(event) for event in events] == [MarketBar, MarketBar, RollMarker, MarketBar]
    assert events[2].from_contract_uid == "CFFEX|F|T|2403"
    assert events[2].to_contract_uid == "CFFEX|F|T|2406"
    assert events[0].clock.raw_unit == "ms"
    rows[2]["trade_time"] = rows[1]["trade_time"]
    rows[2]["trade_timestamp"] = rows[1]["trade_timestamp"]
    pq.write_table(pa.Table.from_pylist(rows), path)
    with pytest.raises(ValueError, match="duplicate"):
        list(iter_minute_bars(path, batch_size=1))


def test_real_t_contract_small_read_only_sample():
    pytest.importorskip("pyarrow")
    source = Path("/Users/maxdeux/Documents/GTHT/data/sources/LocalCNFutures")
    path = source / "data_mink_product/CFFEX_F_T_2403.parquet"
    if not path.exists():
        pytest.skip("local China futures source unavailable")
    bars = list(islice(iter_minute_bars(path, batch_size=8), 3))
    assert len(bars) == 3
    assert {bar.contract_uid for bar in bars} == {"CFFEX|F|T|2403"}
    assert [bar.clock.raw_unit for bar in bars] == ["ms"] * 3
    assert all(bar.clock.available_at_ns == bar.clock.interval_end_ns for bar in bars)


def test_nt_objects_use_supplied_frozen_spec_and_bar_close_time():
    require_nautilus()
    with pytest.raises(ValueError, match="provenance"):
        FuturesContractSpec(
            instrument_code="T2403", venue="CFFEX", underlying="T",
            price_increment=Decimal("0.005"), price_precision=3,
            multiplier=Decimal("10000"), currency="CNY",
            activation_ns=1, expiration_ns=10, margin_init=Decimal("0.02"),
            margin_maint=Decimal("0.02"), provenance="",
            resolved_source=resolved_contract_minute_source(),
        )
    spec = FuturesContractSpec(
        instrument_code="T2403", venue="CFFEX", underlying="T",
        price_increment=Decimal("0.005"), price_precision=3,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="test fixture; not exchange metadata",
        resolved_source=resolved_contract_minute_source(),
    )
    instrument = to_nautilus_instrument(spec)
    from nautilus_trader.model import BarType
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    first = _bar(31)
    nt_bar = to_nautilus_bar(first, bar_type, instrument_spec=spec)
    assert str(nt_bar.close) == "102.900"
    wrong_type = BarType.from_str("TL2406.CFFEX-1-MINUTE-LAST-EXTERNAL")
    with pytest.raises(ValueError, match="BarType instrument"):
        to_nautilus_bar(first, wrong_type, instrument_spec=spec)
    assert nt_bar.ts_event == first.clock.interval_end_ns
    assert nt_bar.ts_init == first.clock.available_at_ns
    continuous = MarketBar(**{**first.__dict__, "continuous_product": "T.CFE"})
    with pytest.raises(ValueError, match="continuous product"):
        to_nautilus_bar(continuous, bar_type, instrument_spec=spec)
    bad_tick = MarketBar(**{**first.__dict__, "high": Decimal("102.937")})
    with pytest.raises(ValueError, match="tick size"):
        to_nautilus_bar(bad_tick, bar_type, instrument_spec=spec)
    quote = to_nautilus_open_quote(
        _bar(32), first, instrument.id,
        bid=Decimal("102.900"), ask=Decimal("102.905"),
        bid_size=Decimal("1"), ask_size=Decimal("1"),
    )
    assert quote.ts_event == first.clock.available_at_ns + 1
    assert str(quote.bid_price) == "102.900"


@pytest.mark.parametrize(
    ("code", "venue", "expected"),
    [("T", "CFFEX", "DEBT"), ("TL", "CFFEX", "DEBT"),
     ("IF", "CFFEX", "EQUITY"), ("AU", "SHFE", "COMMODITY"),
     ("RB", "SHFE", "COMMODITY"), ("SC", "INE", "COMMODITY")],
)
def test_contract_asset_class_is_declared_by_verified_source(code, venue, expected):
    require_nautilus()
    from nautilus_trader.model import AssetClass

    spec = FuturesContractSpec(
        instrument_code=f"{code}2403", venue=venue, underlying=code,
        price_increment=Decimal("0.005"), price_precision=3,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="synthetic metadata; source owns asset class",
        resolved_source=resolved_contract_minute_source(),
    )
    assert spec.asset_class_name == expected
    assert to_nautilus_instrument(spec).asset_class == getattr(AssetClass, expected)


def test_unknown_asset_class_and_unresolved_source_are_rejected():
    kwargs = dict(
        instrument_code="ZZ2403", venue="CFFEX", underlying="ZZ",
        price_increment=Decimal("0.005"), price_precision=3,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="synthetic metadata",
    )
    with pytest.raises(TypeError, match="ResolvedSource"):
        FuturesContractSpec(**kwargs, resolved_source=None)
    with pytest.raises(ValueError, match="asset class"):
        FuturesContractSpec(**kwargs,
                            resolved_source=resolved_contract_minute_source())

    from dataclasses import replace
    source = resolved_contract_minute_source()
    unadmitted = replace(source, capability=replace(source.capability, adapter_id=None))
    with pytest.raises(ValueError, match="admitted physical-contract feed"):
        FuturesContractSpec(**{**kwargs, "instrument_code": "T2403",
                               "underlying": "T"}, resolved_source=unadmitted)


def test_native_quantity_limits_preserve_values_and_defaults():
    from dataclasses import replace
    require_nautilus()
    spec = FuturesContractSpec(
        instrument_code="T2403", venue="CFFEX", underlying="T",
        price_increment=Decimal("0.005"), price_precision=3,
        multiplier=Decimal("10000"), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="synthetic fixture", resolved_source=resolved_contract_minute_source(),
    )
    original = to_nautilus_instrument(spec)
    assert str(original.min_quantity) == "1"
    assert original.max_quantity is None
    instrument = to_nautilus_instrument(replace(
        spec, min_quantity=Decimal("3"), max_quantity=Decimal("25")))
    assert str(instrument.min_quantity) == "3"
    assert str(instrument.max_quantity) == "25"
    for invalid in (Decimal("NaN"), Decimal("Infinity"), Decimal("0"),
                    Decimal("-1"), Decimal("1.5")):
        for key in ("min_quantity", "max_quantity"):
            with pytest.raises(ValueError, match="whole-contract"):
                replace(spec, **{key: invalid})
    with pytest.raises(ValueError, match="exceeds"):
        replace(spec, min_quantity=Decimal("3"), max_quantity=Decimal("2"))
