"""Stage frozen RunSpec products into receipt-checked Nautilus catalogs."""

from __future__ import annotations

from datetime import date, datetime, timezone
from importlib import import_module
import json
from pathlib import Path
from typing import Any, cast

from sources.registry import installed_bundles
from traderesearch_data.nautilus import (
    CatalogLoadRequest, CatalogStagingRequest, NautilusCatalogLoader,
)


def _ns(value: str) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1_000_000_000)


def build_run_spec_session_calendar(*, catalogs: dict[str, dict[str, str]]) -> Any:
    """Reuse day summaries frozen by catalog staging; never reread source Bars."""
    from tools.factors.expr.streaming.calendar_window import (
        TradingCalendarWindow, TradingSessionSummary,
    )

    summary = TradingSessionSummary()
    seen: set[Path] = set()
    for value in catalogs.values():
        folder = Path(value["catalog_dir"]).resolve(strict=True)
        if folder in seen:
            continue
        seen.add(folder)
        receipt = json.loads((folder / "factor_tester_catalog_receipt.json").read_text())
        if receipt.get("contract_uid") != value["contract_uid"]:
            raise ValueError("calendar catalog identity differs from frozen input")
        sessions = receipt.get("session_summaries")
        if not sessions:
            raise ValueError("catalog has no frozen session summaries; restage this input")
        total = 0
        for item in sessions:
            start, end, count = (int(item[key]) for key in ("start_ns", "end_ns", "bar_count"))
            summary.add(date.fromisoformat(item["trading_day"]), start, end,
                        contract=value["contract_uid"], count=count)
            total += count
        if total != int(receipt["selected_count"]):
            raise ValueError("calendar summary count differs from frozen input")
    return TradingCalendarWindow(summary.sessions())


def stage_run_spec_catalogs(
    *, staging_requests: list[dict[str, Any]], source_key: str, frequency: str,
    start_utc: str, end_utc: str, target_root: Path,
) -> dict[str, dict[str, str]]:
    """Select one installed source-owned loader before any plugin activation."""
    matches = [(bundle, member) for bundle in installed_bundles()
               if bundle.execution_location == "server"
               for member in bundle.members if member.id == source_key]
    if len(matches) != 1:
        raise ValueError(f"expected one server-installed source member: {source_key}")
    _, member = matches[0]
    if member.kind != "market_data" or member.data_type != "bar" or member.frequency != frequency:
        raise ValueError(f"source member does not provide requested Bar frequency: {source_key}")
    entrypoint = dict(member.integrations).get("nautilus_catalog")
    if not entrypoint:
        raise ValueError(f"source member has no Nautilus catalog loader: {source_key}")
    start_ns, end_ns = _ns(start_utc), _ns(end_utc)
    if end_ns < start_ns:
        raise ValueError("catalog range ends before its start")
    if not staging_requests:
        raise ValueError("catalog staging request has no members")
    module_name, _, symbol_path = entrypoint.partition(":")
    loader = import_module(module_name)
    for name in symbol_path.split("."):
        loader = getattr(loader, name)
    if not callable(loader):
        raise ValueError(f"source catalog entrypoint is not callable: {source_key}")
    load_catalog = cast(NautilusCatalogLoader, loader)
    try:
        requests = tuple(
            CatalogStagingRequest(tuple(str(path) for path in item.get("paths", ())))
            for item in staging_requests
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid catalog staging request") from exc
    return load_catalog(CatalogLoadRequest(
        source_key=source_key, frequency=frequency,
        related_members=tuple(member.related_members),
        staging_requests=requests, start_utc=start_utc, end_utc=end_utc,
        start_ns=start_ns, end_ns=end_ns, target_root=target_root,
    ))
