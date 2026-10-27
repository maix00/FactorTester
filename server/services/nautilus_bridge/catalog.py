"""Atomic, bounded NT Parquet catalog staging for one frozen futures contract.

The caller resolves historical instrument metadata and an exact source
window.  A successful receipt freezes source bytes and emitted bar values;
it does not imply that a mutable upstream data service can reproduce them.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterator

from server.services.nautilus_bridge.market_data import (
    DailySettlementRecord,
    FuturesContractSpec,
    MarketBar,
    iter_daily_bars,
    iter_minute_bars,
    to_nautilus_bar,
    to_nautilus_daily_settlement,
    to_nautilus_instrument,
)
from server.services.nautilus_bridge.version import NAUTILUS_VERSION


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _peak_rss_bytes() -> int:
    # macOS ru_maxrss is bytes, Linux ru_maxrss is KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value * (1024 if sys.platform.startswith("linux") else 1))


def _bar_digest_line(bar: MarketBar) -> bytes:
    fields = (
        bar.contract_uid, str(bar.clock.interval_open_ns),
        str(bar.clock.interval_end_ns), str(bar.clock.available_at_ns),
        str(bar.open), str(bar.high), str(bar.low), str(bar.close),
        str(bar.volume), str(bar.open_interest),
    )
    return ("|".join(fields) + "\n").encode("utf-8")


def _assert_readback(catalog, bar_type, source_bars: list[MarketBar]) -> None:
    """Query only the just-written window; compare every value and clock."""
    read = catalog.query_bars(
        identifiers=[str(bar_type)],
        start=source_bars[0].clock.available_at_ns,
        end=source_bars[-1].clock.available_at_ns,
    )
    if len(read) != len(source_bars):
        raise ValueError(f"catalog readback count {len(read)} != {len(source_bars)}")
    for expected, actual in zip(source_bars, read, strict=True):
        if (actual.ts_event != expected.clock.interval_end_ns
                or actual.ts_init != expected.clock.available_at_ns):
            raise ValueError("catalog readback clock mismatch")
        for name in ("open", "high", "low", "close", "volume"):
            if Decimal(str(getattr(actual, name))) != getattr(expected, name):
                raise ValueError(f"catalog readback {name} mismatch")


@dataclass(frozen=True)
class CatalogReceipt:
    schema_version: int
    engine: str
    instrument_id: str
    contract_uid: str
    bar_type: str
    source_path: str
    source_bytes: int
    source_mtime_ns: int
    source_sha256: str
    metadata_provenance: str
    selected_count: int
    first_event_ns: int
    last_event_ns: int
    first_available_ns: int
    last_available_ns: int
    selected_bars_sha256: str
    catalog_files: tuple[dict[str, str | int], ...]
    elapsed_ms: float
    process_peak_rss_bytes: int
    max_batch_bars: int
    session_summaries: tuple[dict[str, str | int], ...] = ()
    settlement_records: tuple[dict[str, str | int], ...] = ()
    bundle_id: str = ""
    bundle_version: str = ""
    bundle_fingerprint: str = ""
    member_id: str = ""


def _stage_contract_catalog(
    source_path: str | Path, target_dir: str | Path, *,
    contract_uid: str, instrument_spec: FuturesContractSpec,
    start_ns: int, end_ns: int,
    bars: Iterator[MarketBar], bar_type_suffix: str,
    batch_bars: int = 4_096, max_bars: int = 100_000,
    bundle_id: str = "", bundle_version: str = "",
    bundle_fingerprint: str = "", member_id: str = "",
) -> CatalogReceipt:
    """Shared bounded NT writer for one source-owned Bar contract.

    A new sibling staging directory is renamed only after every chunk can be
    read back.  Neither the source nor an existing target is modified.  The
    source is opened via projected Arrow batches; never ``add_data(all_bars)``.
    """
    if start_ns > end_ns or batch_bars < 1 or max_bars < 1:
        raise ValueError("invalid window or batch budget")
    source = Path(source_path).resolve(strict=True)
    target = Path(target_dir).resolve()
    if target.exists():
        raise FileExistsError(target)
    if not target.parent.is_dir():
        raise FileNotFoundError(target.parent)
    if source.is_dir():
        raise ValueError("source must be one contract parquet file")

    from nautilus_trader import __version__ as nt_version
    from nautilus_trader.model import BarType
    from nautilus_trader.persistence import ParquetDataCatalog

    if nt_version != NAUTILUS_VERSION:
        raise RuntimeError(f"NautilusTrader pin mismatch: {nt_version}")
    instrument = to_nautilus_instrument(instrument_spec)
    bar_type = BarType.from_str(f"{instrument.id}-{bar_type_suffix}")
    started = time.perf_counter()
    initial_stat = source.stat()
    source_hash = _sha256_file(source)
    staged = Path(tempfile.mkdtemp(prefix=f".{target.name}-staging-", dir=target.parent))
    try:
        catalog = ParquetDataCatalog(str(staged))
        catalog.write_instruments([instrument])
        selected_hash = hashlib.sha256()
        first: MarketBar | None = None
        last: MarketBar | None = None
        selected_count = 0
        settlement_records: list[dict[str, str | int]] = []
        settlement_events = []
        batch: list[MarketBar] = []
        from tools.factors.expr.streaming.calendar_window import TradingSessionSummary
        session_summary = TradingSessionSummary()

        def flush() -> None:
            if not batch:
                return
            catalog.write_bars([
                to_nautilus_bar(bar, bar_type, instrument_spec=instrument_spec)
                for bar in batch
            ])
            _assert_readback(catalog, bar_type, batch)
            batch.clear()

        for bar in bars:
            if not isinstance(bar, MarketBar):
                raise TypeError("continuous roll marker cannot enter contract catalog")
            if bar.contract_uid != contract_uid:
                raise ValueError(f"unexpected contract UID: {bar.contract_uid}")
            if bar.instrument_code != instrument_spec.instrument_code:
                raise ValueError(f"instrument code mismatch: {bar.instrument_code}")
            selected_count += 1
            if selected_count > max_bars:
                raise ValueError("selected window exceeds explicit max_bars budget")
            selected_hash.update(_bar_digest_line(bar))
            if bar.settlement_price is not None:
                settlement_records.append({
                    "contract_uid": bar.contract_uid,
                    "trading_day": bar.trading_day.isoformat(),
                    "event_ns": bar.clock.interval_end_ns,
                    "settlement_price": str(bar.settlement_price),
                })
                settlement_events.append(to_nautilus_daily_settlement(
                    DailySettlementRecord(
                        contract_uid=bar.contract_uid,
                        instrument_id=str(instrument.id),
                        trading_day=bar.trading_day,
                        settlement_price=bar.settlement_price,
                        timestamp_ns=bar.clock.interval_end_ns,
                        rule_set_ref=instrument_spec.provenance,
                        source_path=str(source),
                        row_number=bar.row_number,
                    ),
                    instrument=instrument, instrument_spec=instrument_spec,
                ))
            session_summary.add(bar.trading_day, bar.clock.interval_open_ns,
                                bar.clock.interval_end_ns)
            if first is None:
                first = bar
            last = bar
            batch.append(bar)
            if len(batch) == batch_bars:
                flush()
        flush()
        if settlement_events:
            catalog.write_instrument_closes(settlement_events)
        if first is None or last is None:
            raise ValueError("source contains no bars in selected window")
        final_stat = source.stat()
        if (initial_stat.st_size, initial_stat.st_mtime_ns) != (
            final_stat.st_size, final_stat.st_mtime_ns
        ):
            raise RuntimeError("source changed while catalog was staged")

        files = tuple({
            "path": file.relative_to(staged).as_posix(),
            "bytes": file.stat().st_size,
            "sha256": _sha256_file(file),
        } for file in sorted(staged.rglob("*.parquet")))
        receipt = CatalogReceipt(
            schema_version=1, engine=f"NautilusTrader {nt_version}",
            instrument_id=str(instrument.id), contract_uid=contract_uid,
            bar_type=str(bar_type), source_path=str(source),
            source_bytes=initial_stat.st_size, source_mtime_ns=initial_stat.st_mtime_ns,
            source_sha256=source_hash,
            metadata_provenance=instrument_spec.provenance,
            selected_count=selected_count,
            first_event_ns=first.clock.interval_end_ns,
            last_event_ns=last.clock.interval_end_ns,
            first_available_ns=first.clock.available_at_ns,
            last_available_ns=last.clock.available_at_ns,
            selected_bars_sha256=selected_hash.hexdigest(),
            catalog_files=files,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            process_peak_rss_bytes=_peak_rss_bytes(), max_batch_bars=batch_bars,
            session_summaries=tuple({
                "trading_day": item.trading_day.isoformat(),
                "start_ns": item.start_ns, "end_ns": item.end_ns,
                "bar_count": item.bar_count,
            } for item in session_summary.sessions()),
            settlement_records=tuple(settlement_records),
            bundle_id=bundle_id, bundle_version=bundle_version,
            bundle_fingerprint=bundle_fingerprint, member_id=member_id,
        )
        receipt_path = staged / "factor_tester_catalog_receipt.json"
        receipt_path.write_text(json.dumps(asdict(receipt), ensure_ascii=False,
                                          sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(staged, target)
        return receipt
    except Exception:
        shutil.rmtree(staged)
        raise


def load_catalog_settlement_records(
    catalog_dir: str | Path, *, contract_uid: str,
) -> tuple[dict[str, str | int], ...]:
    """Read the persisted DAY1 settlement observations for one staged catalog."""
    folder = Path(catalog_dir)
    receipt = json.loads((folder / "factor_tester_catalog_receipt.json").read_text())
    if receipt.get("contract_uid") != contract_uid:
        raise ValueError("catalog settlement identity differs from requested contract")
    records = receipt.get("settlement_records") or ()
    for item in records:
        if item.get("contract_uid") != contract_uid:
            raise ValueError("settlement record belongs to another contract")
        if not str(item.get("trading_day") or "") or not str(item.get("settlement_price") or ""):
            raise ValueError("settlement record is incomplete")
    return tuple(records)


def stage_contract_minute_catalog(
    source_path: str | Path, target_dir: str | Path, *,
    contract_uid: str, instrument_spec: FuturesContractSpec,
    start_ns: int, end_ns: int,
    batch_bars: int = 4_096, max_bars: int = 100_000,
    bundle_id: str = "", bundle_version: str = "",
    bundle_fingerprint: str = "", member_id: str = "",
) -> CatalogReceipt:
    """Write one contract's unadjusted MIN1 bars in bounded NT batches."""
    return _stage_contract_catalog(
        source_path, target_dir, contract_uid=contract_uid,
        instrument_spec=instrument_spec, start_ns=start_ns, end_ns=end_ns,
        bars=iter_minute_bars(Path(source_path), start_ns=start_ns, end_ns=end_ns,
                              batch_size=batch_bars),
        bar_type_suffix="1-MINUTE-LAST-EXTERNAL",
        batch_bars=batch_bars, max_bars=max_bars,
        bundle_id=bundle_id, bundle_version=bundle_version,
        bundle_fingerprint=bundle_fingerprint, member_id=member_id,
    )


def stage_contract_daily_catalog(
    source_path: str | Path, target_dir: str | Path, *,
    contract_uid: str, instrument_spec: FuturesContractSpec,
    start_ns: int, end_ns: int, product_codes: set[str],
    session_for_day: Callable, source_time_unit: str = "validated",
    batch_bars: int = 4_096, max_bars: int = 100_000,
    bundle_id: str = "", bundle_version: str = "",
    bundle_fingerprint: str = "", member_id: str = "",
) -> CatalogReceipt:
    """Write one contract's date-labelled DAY1 bars in bounded NT batches.

    The source label is never the event time; ``session_for_day`` supplies the
    source-owned exchange calendar used by ``daily_clock``.
    """
    return _stage_contract_catalog(
        source_path, target_dir, contract_uid=contract_uid,
        instrument_spec=instrument_spec, start_ns=start_ns, end_ns=end_ns,
        bars=iter_daily_bars(
            Path(source_path), product_codes=product_codes,
            session_for_day=session_for_day, raw_unit=source_time_unit,
            batch_size=batch_bars, start_ns=start_ns, end_ns=end_ns,
            contract_uids={contract_uid},
        ),
        bar_type_suffix="1-DAY-LAST-EXTERNAL",
        batch_bars=batch_bars, max_bars=max_bars,
        bundle_id=bundle_id, bundle_version=bundle_version,
        bundle_fingerprint=bundle_fingerprint, member_id=member_id,
    )
