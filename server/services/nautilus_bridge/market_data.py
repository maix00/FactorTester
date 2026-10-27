"""Bounded LocalCNFutures bar conversion for NautilusTrader.

The source's minute ``trade_time`` names the *end* of its interval.  A
continuous product is a signal series, never a tradable InstrumentId.  This
module deliberately does not infer exchange fees, expiry, multiplier, or
margin from prices; callers must supply an authoritative instrument spec.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
NANOSECONDS = 1_000_000_000
RawTimeUnit = Literal["s", "ms", "us", "ns"]
SourceTimeUnit = RawTimeUnit | Literal["validated"]


def epoch_ns(raw: int, unit: RawTimeUnit) -> int:
    """Normalize an explicitly typed Unix timestamp, never magnitude-guess."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError("raw timestamp must be an integer")
    factor = {"s": NANOSECONDS, "ms": 1_000_000, "us": 1_000, "ns": 1}.get(unit)
    if factor is None:
        raise ValueError(f"unsupported timestamp unit: {unit!r}")
    return raw * factor


def _wall_time_ns(value: datetime, timezone: ZoneInfo) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone)
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return ((delta.days * 86_400 + delta.seconds) * NANOSECONDS
            + delta.microseconds * 1_000)


@dataclass(frozen=True)
class BarClock:
    raw_timestamp: int | None
    raw_unit: RawTimeUnit | None
    interval_open_ns: int
    interval_end_ns: int
    available_at_ns: int
    raw_trade_time: str

    def __post_init__(self) -> None:
        if not self.interval_open_ns < self.interval_end_ns <= self.available_at_ns:
            raise ValueError("bar must be published after its complete interval")


def minute_clock(
    trade_time: datetime, raw_timestamp: int, *, raw_unit: SourceTimeUnit,
    interval: timedelta = timedelta(minutes=1), timezone: ZoneInfo = SHANGHAI,
    available_delay_ns: int = 0,
) -> BarClock:
    """Validate source time against the end-labelled exchange-local minute."""
    if interval <= timedelta(0) or available_delay_ns < 0:
        raise ValueError("interval and visibility delay must be non-negative")
    end_ns = _wall_time_ns(trade_time, timezone)
    if raw_unit == "validated":
        matching = [unit for unit in ("s", "ms", "us", "ns")
                    if epoch_ns(raw_timestamp, unit) == end_ns]
        if len(matching) != 1:
            raise ValueError("trade_timestamp has no unique unit matching trade_time")
        raw_unit = matching[0]
    actual_ns = epoch_ns(raw_timestamp, raw_unit)
    if actual_ns != end_ns:
        raise ValueError(
            f"trade_timestamp {raw_timestamp} {raw_unit} disagrees with "
            f"trade_time {trade_time.isoformat()} in {timezone.key}"
        )
    interval_ns = int(interval.total_seconds() * NANOSECONDS)
    return BarClock(raw_timestamp, raw_unit, end_ns - interval_ns, end_ns,
                    end_ns + available_delay_ns, trade_time.isoformat())


def daily_clock(
    trading_day: date, *, session_open: datetime, session_close: datetime,
    timezone: ZoneInfo = SHANGHAI, available_delay_ns: int = 0,
    raw_timestamp: int | None = None, raw_unit: SourceTimeUnit = "validated",
) -> BarClock:
    """Give a date-labelled DAY1 bar an explicit calendar-supplied close.

    The source date at 00:00 is not the publish time.  A calendar supplies
    both session bounds (including night sessions and exceptional closes).
    This adapter refuses to silently use midnight or a hard-coded schedule.
    """
    if isinstance(trading_day, datetime):
        trading_day = trading_day.date()
    if available_delay_ns < 0:
        raise ValueError("visibility delay must be non-negative")
    end_ns = _wall_time_ns(session_close, timezone)
    start_ns = _wall_time_ns(session_open, timezone)
    close_date = (session_close.astimezone(timezone).date()
                  if session_close.tzinfo else session_close.date())
    if close_date != trading_day:
        raise ValueError("session close date disagrees with trading day")
    if raw_timestamp is not None:
        midnight = _wall_time_ns(datetime.combine(trading_day, time.min), timezone)
        if raw_unit == "validated":
            matching = [unit for unit in ("s", "ms", "us", "ns")
                        if epoch_ns(raw_timestamp, unit) == midnight]
            if len(matching) != 1:
                raise ValueError("daily source timestamp has no unique midnight unit")
            raw_unit = matching[0]
        if epoch_ns(raw_timestamp, raw_unit) != midnight:
            raise ValueError("daily source timestamp disagrees with trading day")
    else:
        raw_unit = None
    return BarClock(raw_timestamp, raw_unit, start_ns, end_ns, end_ns + available_delay_ns,
                    trading_day.isoformat())


@dataclass(frozen=True)
class MarketBar:
    contract_uid: str
    instrument_code: str
    trading_day: date
    clock: BarClock
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    open_interest: Decimal | None
    source_path: str
    row_number: int
    continuous_product: str | None = None
    settlement_price: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.contract_uid or not self.instrument_code:
            raise ValueError("contract identity is required")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("inconsistent OHLC bounds")
        if self.volume < 0 or (self.open_interest is not None and self.open_interest < 0):
            raise ValueError("negative volume or open interest")
        if self.settlement_price is not None and self.settlement_price <= 0:
            raise ValueError("settlement price must be positive")


@dataclass(frozen=True)
class RollMarker:
    continuous_product: str
    from_contract_uid: str
    to_contract_uid: str
    effective_at_ns: int


def _decimal(value: object, column: str, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"invalid {column}: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite {column}")
    return result


def iter_minute_bars(
    path: str | Path, *, raw_unit: SourceTimeUnit = "validated",
    batch_size: int = 2048, start_ns: int | None = None, end_ns: int | None = None,
    continuous_product: str | None = None,
) -> Iterator[MarketBar | RollMarker]:
    """Read small Arrow batches; emit exact unadjusted bars and roll boundaries.

    This avoids a second full pandas/NumPy market matrix.  Its caller must
    likewise use a bounded catalog/write pipeline; ``BacktestEngine.add_data``
    may retain a full list and is not a memory-bounded consumer.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    import pyarrow.parquet as pq

    source = Path(path)
    reader = pq.ParquetFile(source)
    required = {
        "trade_time", "trade_timestamp", "trading_day", "contract_uid",
        "instrument_id", "open_price", "highest_price", "lowest_price",
        "close_price", "volume", "open_interest",
    }
    available = set(reader.schema_arrow.names)
    missing = required - available
    if missing:
        raise ValueError(f"{source.name} missing fields: {sorted(missing)}")
    previous_time: int | None = None
    previous_uid: str | None = None
    row_number = 0
    from traderesearch_data.shared_cache import host_input_cache
    for batch in host_input_cache().iter_parquet_batches(
        source, batch_size=batch_size, columns=sorted(required),
    ):
        for row in batch.to_pylist():
            row_number += 1
            clock = minute_clock(row["trade_time"], int(row["trade_timestamp"]), raw_unit=raw_unit)
            if previous_time is not None and clock.interval_end_ns <= previous_time:
                raise ValueError(f"out-of-order or duplicate bar at source row {row_number}")
            previous_time = clock.interval_end_ns
            if start_ns is not None and clock.interval_end_ns < start_ns:
                continue
            if end_ns is not None and clock.interval_end_ns > end_ns:
                return
            uid = str(row["contract_uid"] or "")
            if continuous_product and previous_uid and uid != previous_uid:
                yield RollMarker(continuous_product, previous_uid, uid, clock.interval_open_ns)
            previous_uid = uid
            yield MarketBar(
                contract_uid=uid, instrument_code=str(row["instrument_id"] or ""),
                trading_day=row["trading_day"].date(), clock=clock,
                open=_decimal(row["open_price"], "open_price"),
                high=_decimal(row["highest_price"], "highest_price"),
                low=_decimal(row["lowest_price"], "lowest_price"),
                close=_decimal(row["close_price"], "close_price"),
                volume=_decimal(row["volume"], "volume"),
                open_interest=_decimal(row["open_interest"], "open_interest", optional=True),
                source_path=str(source), row_number=row_number,
                continuous_product=continuous_product,
            )


def iter_daily_bars(
    path: str | Path, *, product_codes: set[str],
    session_for_day: Callable[[date], tuple[datetime, datetime]],
    raw_unit: SourceTimeUnit = "validated", batch_size: int = 2048,
    start_ns: int | None = None, end_ns: int | None = None,
    contract_uids: set[str] | None = None,
) -> Iterator[MarketBar]:
    """Stream LocalCNFutures' date-labelled DAY1 table through an exchange calendar.

    The normalized term-structure artifact stores uppercase columns and a
    trading-day date label; it does not store ``trade_timestamp``.  Its date
    label is never treated as the Nautilus event time.  The caller must supply
    the versioned session calendar that determines the actual close.
    """
    if not product_codes or batch_size < 1:
        raise ValueError("product_codes and positive batch_size required")
    import pyarrow.dataset as ds

    source = Path(path)
    dataset = ds.dataset(source, format="parquet")
    required = {
        "TRADING_DAY", "CONTRACT_UID", "PRODUCT", "CONTRACT",
        "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "OPEN_INTEREST",
    }
    available = set(dataset.schema.names)
    missing = required - available
    if missing:
        raise ValueError(f"{source.name} missing fields: {sorted(missing)}")
    optional = {"SETTLEMENT_PRICE", "PRE_SETTLEMENT_PRICE"} & available
    timestamp_column = "TRADE_TIMESTAMP" if "TRADE_TIMESTAMP" in available else None
    columns = required | optional | ({timestamp_column} if timestamp_column else set())
    predicate = ds.field("PRODUCT").isin(sorted(product_codes))
    if contract_uids:
        predicate = predicate & ds.field("CONTRACT_UID").isin(sorted(contract_uids))
    scanner = dataset.scanner(columns=sorted(columns), filter=predicate,
                              batch_size=batch_size, use_threads=False)
    previous_by_uid: dict[str, int] = {}
    row_number = 0
    for batch in scanner.to_batches():
        for row in batch.to_pylist():
            row_number += 1
            day_value = row["TRADING_DAY"]
            day = day_value.date() if isinstance(day_value, datetime) else day_value
            start, close = session_for_day(day)
            raw_timestamp = row.get(timestamp_column) if timestamp_column else None
            clock = daily_clock(
                day, session_open=start, session_close=close,
                raw_timestamp=(int(raw_timestamp) if raw_timestamp is not None else None),
                raw_unit=raw_unit,
            )
            if start_ns is not None and clock.interval_end_ns < start_ns:
                continue
            if end_ns is not None and clock.interval_end_ns > end_ns:
                continue
            uid = str(row["CONTRACT_UID"] or "")
            last = previous_by_uid.get(uid)
            if last is not None and clock.interval_end_ns <= last:
                raise ValueError(f"out-of-order or duplicate daily bar for {uid}")
            previous_by_uid[uid] = clock.interval_end_ns
            yield MarketBar(
                contract_uid=uid,
                instrument_code=str(row["CONTRACT"] or "").split(".", 1)[0],
                trading_day=day, clock=clock,
                open=_decimal(row["OPEN"], "OPEN"),
                high=_decimal(row["HIGH"], "HIGH"),
                low=_decimal(row["LOW"], "LOW"),
                close=_decimal(row["CLOSE"], "CLOSE"),
                volume=_decimal(row["VOLUME"], "VOLUME"),
                open_interest=_decimal(row["OPEN_INTEREST"], "OPEN_INTEREST", optional=True),
                source_path=str(source), row_number=row_number,
                settlement_price=(
                    _decimal(row.get("SETTLEMENT_PRICE"), "SETTLEMENT_PRICE", optional=True)
                    if "SETTLEMENT_PRICE" in optional else None
                ),
            )


@dataclass(frozen=True, slots=True)
class DailySettlementRule:
    """One frozen exchange rule effective for a product on a trading day."""

    eligible: bool
    price_field: str
    close_time: time
    timezone: str
    authority: str
    source_key: str
    rule_set_ref: str

    def __post_init__(self) -> None:
        if not self.eligible:
            raise ValueError("daily settlement event requested for an ineligible product")
        if self.price_field != "settlement_price":
            raise ValueError("DMTM requires the official settlement_price field")
        if self.authority not in {"exchange_notice", "exchange_calendar"}:
            raise ValueError("settlement rule needs exchange authority")
        if not self.source_key or not self.rule_set_ref:
            raise ValueError("settlement rule provenance and frozen rule-set ref are required")
        ZoneInfo(self.timezone)


@dataclass(frozen=True, slots=True)
class DailySettlementRecord:
    contract_uid: str
    instrument_id: str
    trading_day: date
    settlement_price: Decimal
    timestamp_ns: int
    rule_set_ref: str
    source_path: str
    row_number: int


def iter_daily_settlement_records(
    path: str | Path, *, instrument_ids_by_contract_uid: Mapping[str, str],
    product_codes: set[str],
    rule_for_day: Callable[[str, date], DailySettlementRule],
    session_for_day: Callable[[str, date], tuple[datetime, datetime]],
    start_ns: int | None = None, end_ns: int | None = None,
    batch_size: int = 2048,
) -> Iterator[DailySettlementRecord]:
    """Read official settlement prices and timestamp them with frozen rules.

    This intentionally projects only the term-structure identity, trading-day
    and settlement columns. Missing prices, missing rules, invalid calendars,
    duplicate rows and out-of-order events fail closed. The caller must
    resolve the versioned exchange rule and calendar; no midnight or observed
    OHLC close is used as a substitute.
    """
    if not instrument_ids_by_contract_uid or not product_codes or batch_size < 1:
        raise ValueError("instrument mapping, product codes and positive batch size are required")
    import pyarrow.dataset as ds

    source = Path(path)
    dataset = ds.dataset(source, format="parquet")
    required = {"TRADING_DAY", "CONTRACT_UID", "PRODUCT", "SETTLEMENT_PRICE"}
    missing = required - set(dataset.schema.names)
    if missing:
        raise ValueError(f"{source.name} missing settlement fields: {sorted(missing)}")
    predicate = (
        ds.field("PRODUCT").isin(sorted(product_codes))
        & ds.field("CONTRACT_UID").isin(sorted(instrument_ids_by_contract_uid))
    )
    scanner = dataset.scanner(
        columns=sorted(required), filter=predicate,
        batch_size=batch_size, use_threads=False,
    )
    previous_by_uid: dict[str, int] = {}
    row_number = 0
    for batch in scanner.to_batches():
        for row in batch.to_pylist():
            row_number += 1
            raw_day = row["TRADING_DAY"]
            day = raw_day.date() if isinstance(raw_day, datetime) else raw_day
            uid = str(row["CONTRACT_UID"] or "")
            instrument_id = instrument_ids_by_contract_uid.get(uid)
            if instrument_id is None:
                raise ValueError(f"settlement row contains an unfrozen contract {uid!r}")
            price = _decimal(row["SETTLEMENT_PRICE"], "SETTLEMENT_PRICE", optional=True)
            if price is None or price <= 0:
                raise ValueError(f"{uid}/{day}: official settlement price is missing or invalid")
            rule = rule_for_day(uid, day)
            if not isinstance(rule, DailySettlementRule):
                raise TypeError("rule_for_day must return a validated DailySettlementRule")
            session_open, session_close = session_for_day(uid, day)
            if session_close.tzinfo is None:
                timezone = ZoneInfo(rule.timezone)
                close = session_close.replace(tzinfo=timezone)
            else:
                close = session_close.astimezone(ZoneInfo(rule.timezone))
            if close.date() != day or close.timetz().replace(tzinfo=None) != rule.close_time:
                raise ValueError(f"{uid}/{day}: exchange close and settlement-rule time disagree")
            clock = daily_clock(
                day, session_open=session_open, session_close=close,
                timezone=ZoneInfo(rule.timezone),
            )
            event_ns = clock.interval_end_ns
            if start_ns is not None and event_ns < start_ns:
                continue
            if end_ns is not None and event_ns > end_ns:
                continue
            previous = previous_by_uid.get(uid)
            if previous is not None and event_ns <= previous:
                raise ValueError(f"duplicate or out-of-order settlement for {uid}/{day}")
            previous_by_uid[uid] = event_ns
            yield DailySettlementRecord(
                uid, instrument_id, day, price, event_ns,
                rule.rule_set_ref, str(source), row_number,
            )


def to_nautilus_daily_settlement(record: DailySettlementRecord, *, instrument: object,
                                 instrument_spec: FuturesContractSpec):
    """Convert a validated settlement record into Nautilus' native close event."""
    from nautilus_trader.model import InstrumentClose, InstrumentCloseType, Price

    if str(getattr(instrument, "id", "")) != record.instrument_id:
        raise ValueError("settlement InstrumentId differs from the frozen instrument")
    if record.instrument_id != f"{instrument_spec.instrument_code}.{instrument_spec.venue}":
        raise ValueError("settlement record differs from the frozen instrument specification")
    formatted = f"{record.settlement_price:.{instrument_spec.price_precision}f}"
    if Decimal(formatted) != record.settlement_price:
        raise ValueError("settlement price exceeds frozen instrument precision")
    if record.settlement_price % instrument_spec.price_increment != 0:
        raise ValueError("settlement price is not aligned to the frozen tick size")
    return InstrumentClose(
        instrument_id=instrument.id,
        close_price=Price.from_str(formatted),
        close_type=InstrumentCloseType.DAILY_SETTLEMENT,
        ts_event=record.timestamp_ns,
        ts_init=record.timestamp_ns,
    )


def next_open_event_time(bar: MarketBar, previous_bar: MarketBar | None) -> int:
    """Clock for an independently observed opening quote, after prior signal.

    This does not read a future OHLC inside the previous ``on_bar``.  The
    opening quote must be delivered from the *current* row as a separate
    event, with explicit bid/ask and liquidity assumptions at execution.
    """
    at_ns = bar.clock.interval_open_ns + 1
    if previous_bar is not None and at_ns <= previous_bar.clock.available_at_ns:
        raise ValueError("next open precedes prior bar signal availability")
    return at_ns


def to_nautilus_bar(bar: MarketBar, bar_type: object, *,
                    instrument_spec: FuturesContractSpec):
    """Convert one tradable contract bar to a native NT Bar, without bulk copy.

    Continuous product bars have a rolling identity and must travel as a
    separate factor/market-data signal stream, not a tradable instrument.
    """
    if bar.continuous_product is not None:
        raise ValueError("continuous product bar cannot be a tradable NT Bar")
    if bar.instrument_code != instrument_spec.instrument_code:
        raise ValueError("bar instrument differs from frozen contract spec")
    if str(bar_type.instrument_id) != f"{instrument_spec.instrument_code}.{instrument_spec.venue}":
        raise ValueError("BarType instrument differs from frozen contract spec")
    from nautilus_trader.model import Bar, Price, Quantity

    def fixed_price(value: Decimal):
        formatted = f"{value:.{instrument_spec.price_precision}f}"
        if Decimal(formatted) != value:
            raise ValueError("bar price exceeds frozen contract precision")
        ticks = value / instrument_spec.price_increment
        if ticks != ticks.to_integral_value():
            raise ValueError("bar price is not aligned to frozen tick size")
        return Price.from_str(formatted)

    if bar.volume != bar.volume.to_integral_value():
        raise ValueError("futures bar volume must be integral contract count")

    return Bar(
        bar_type=bar_type,
        open=fixed_price(bar.open), high=fixed_price(bar.high),
        low=fixed_price(bar.low), close=fixed_price(bar.close),
        volume=Quantity.from_str(str(int(bar.volume))),
        ts_event=bar.clock.interval_end_ns,
        ts_init=bar.clock.available_at_ns,
    )


def to_nautilus_open_quote(
    bar: MarketBar, previous_bar: MarketBar | None, instrument_id: object,
    *, bid: Decimal, ask: Decimal, bid_size: Decimal, ask_size: Decimal,
):
    """Publish separately observed opening BBO with stated spread and depth.

    The caller, not this adapter, establishes where an opening quote came
    from.  Passing the future full bar to a prior ``on_bar`` is forbidden.
    """
    from nautilus_trader.model import Price, Quantity, QuoteTick

    if bar.continuous_product is not None:
        raise ValueError("continuous product has no tradable opening quote")
    if bid <= 0 or ask < bid or bid_size < 0 or ask_size < 0:
        raise ValueError("invalid opening quote")
    at_ns = next_open_event_time(bar, previous_bar)
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str(str(bid)), ask_price=Price.from_str(str(ask)),
        bid_size=Quantity.from_str(str(bid_size)),
        ask_size=Quantity.from_str(str(ask_size)),
        ts_event=at_ns, ts_init=at_ns,
    )


@dataclass(frozen=True)
class FuturesContractSpec:
    """Frozen, authoritative exchange/product metadata required for trading."""

    instrument_code: str
    venue: str
    underlying: str
    price_increment: Decimal
    price_precision: int
    multiplier: Decimal
    currency: str
    activation_ns: int
    expiration_ns: int
    margin_init: Decimal
    margin_maint: Decimal
    provenance: str
    resolved_source: object
    min_quantity: Decimal | None = None
    max_quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if (not self.provenance or not self.instrument_code or not self.venue
                or not self.currency or not self.underlying):
            raise ValueError("authoritative instrument identity/provenance required")
        if self.price_increment <= 0 or self.multiplier <= 0:
            raise ValueError("tick and multiplier must be positive")
        if (self.price_precision < 0 or
                Decimal(f"{self.price_increment:.{self.price_precision}f}")
                != self.price_increment):
            raise ValueError("tick exceeds instrument price precision")
        if not 0 <= self.activation_ns < self.expiration_ns < 2**64:
            raise ValueError("invalid contract lifecycle")
        if self.margin_init < 0 or self.margin_maint < 0:
            raise ValueError("margin ratios must be non-negative")
        for name in ("min_quantity", "max_quantity"):
            quantity = getattr(self, name)
            if quantity is not None and (
                not isinstance(quantity, Decimal) or not quantity.is_finite()
                or quantity <= 0 or quantity != quantity.to_integral_value()
            ):
                raise ValueError(f"{name} must be a positive whole-contract quantity")
        if (self.min_quantity is not None and self.max_quantity is not None
                and self.min_quantity > self.max_quantity):
            raise ValueError("min_quantity exceeds max_quantity")
        # Keep source authority explicit.  A bare caller-supplied asset class
        # would let a futures contract silently inherit the wrong semantics.
        from server.services.nautilus_bridge.source_registry import ResolvedSource
        if not isinstance(self.resolved_source, ResolvedSource):
            raise TypeError("verified ResolvedSource is required for asset class")
        source = self.resolved_source
        if (source.adapter.product_scope != "physical_contract_only"
                or source.capability.adapter_id != source.adapter.adapter_id
                or source.capability.member_key != source.member.key):
            raise ValueError("resolved source is not an admitted physical-contract feed")
        if not self.instrument_code.startswith(self.underlying):
            raise ValueError("instrument code does not match source product")
        month = self.instrument_code[len(self.underlying):]
        if not month or not month.isdigit():
            raise ValueError("instrument code lacks a parseable futures contract month")
        product = SimpleNamespace(name=f"{self.venue}|F|{self.underlying}|{month}")
        if source.member.asset_class_for_product(product) not in {
            "DEBT", "EQUITY", "COMMODITY",
        }:
            raise ValueError("source cannot resolve the futures asset class")

    @property
    def asset_class_name(self) -> str:
        month = self.instrument_code[len(self.underlying):]
        product = SimpleNamespace(name=f"{self.venue}|F|{self.underlying}|{month}")
        value = self.resolved_source.member.asset_class_for_product(product)
        if value not in {"DEBT", "EQUITY", "COMMODITY"}:
            raise ValueError("source cannot resolve the futures asset class")
        return value


def to_nautilus_instrument(spec: FuturesContractSpec):
    """Construct NT FuturesContract only when complete metadata is supplied."""
    from nautilus_trader.model import (
        AssetClass,
        Currency,
        FuturesContract,
        InstrumentId,
        Price,
        Quantity,
        Symbol,
        Venue,
    )

    symbol = Symbol(spec.instrument_code)
    return FuturesContract(
        instrument_id=InstrumentId(symbol, Venue(spec.venue)), raw_symbol=symbol,
        asset_class=getattr(AssetClass, spec.asset_class_name),
        currency=Currency.from_str(spec.currency),
        price_precision=spec.price_precision,
        price_increment=Price.from_str(str(spec.price_increment)),
        multiplier=Quantity.from_str(str(spec.multiplier)),
        lot_size=Quantity.from_int(1), underlying=spec.underlying,
        activation_ns=spec.activation_ns, expiration_ns=spec.expiration_ns,
        ts_event=spec.activation_ns, ts_init=spec.activation_ns,
        margin_init=spec.margin_init, margin_maint=spec.margin_maint,
        exchange=spec.venue,
        min_quantity=(Quantity.from_str(str(spec.min_quantity.to_integral_value()))
                      if spec.min_quantity is not None else None),
        max_quantity=(Quantity.from_str(str(spec.max_quantity.to_integral_value()))
                      if spec.max_quantity is not None else None),
    )
