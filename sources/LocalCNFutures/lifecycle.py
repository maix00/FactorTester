"""Lifecycle inference helpers owned by LocalCNFutures.

These helpers deliberately infer only from LocalCNFutures' observed coverage.
They do not pretend to be exchange lifecycle truth: if a contract's last real
bar is earlier than the latest real bar among peer contracts for the same
product, the contract has ended within the local data horizon. If it reaches
the local data horizon, the contract may still be alive and no expiry/rollover
event should be inferred.
"""

from __future__ import annotations

from typing import Any, Iterable, cast

import pandas as pd

from tools.data.types.time_index import DataIndex


def infer_contract_end_from_coverage(
    row: dict[str, Any],
    peer_rows: Iterable[dict[str, Any]],
    raw_prices: pd.DataFrame | None,
) -> dict[str, Any]:
    if raw_prices is None or raw_prices.empty:
        return {"status": "missing", "reason": "raw_prices_unavailable"}
    contract_column = _matching_column(raw_prices, _row_contract_candidates(row))
    if contract_column is None:
        return {"status": "missing", "reason": "contract_column_unavailable"}
    contract_series = _series_for_column(raw_prices, contract_column)
    if contract_series is None:
        return {"status": "missing", "reason": "contract_column_unavailable"}
    contract_last = _last_valid_timestamp(contract_series)
    if contract_last is None:
        return {"status": "missing", "reason": "contract_data_unavailable"}

    peer_last_values = [
        ts for ts in (
            _last_valid_timestamp(series)
            for peer in peer_rows
            for column in [_matching_column(raw_prices, _row_contract_candidates(peer))]
            if column is not None
            for series in [_series_for_column(raw_prices, column)]
            if series is not None
        )
        if ts is not None
    ]
    if not peer_last_values:
        return {"status": "missing", "reason": "peer_data_unavailable"}
    data_cutoff = max(peer_last_values)
    if _trading_day(contract_last) < _trading_day(data_cutoff):
        return {
            "status": "ended",
            "timestamp": contract_last,
            "data_cutoff": data_cutoff,
            "source": "LocalCNFutures coverage inference",
        }
    return {
        "status": "active_at_data_cutoff",
        "timestamp": contract_last,
        "data_cutoff": data_cutoff,
        "source": "LocalCNFutures coverage inference",
    }


def _row_contract_candidates(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("contract_object"),
        row.get("contract_product"),
        row.get("contract"),
        row.get("uid"),
    )


def _matching_column(frame: pd.DataFrame, candidates: Iterable[Any]) -> Any | None:
    columns = list(frame.columns)
    by_name = {str(getattr(column, "name", column)): column for column in columns}
    for candidate in candidates:
        if candidate is None:
            continue
        if candidate in frame.columns:
            return candidate
        text = str(getattr(candidate, "name", candidate))
        if text in by_name:
            return by_name[text]
    return None


def _series_for_column(frame: pd.DataFrame, column: Any) -> pd.Series | None:
    data = frame[column]
    if isinstance(data, pd.DataFrame):
        if data.shape[1] == 0:
            return None
        return cast(pd.Series, data.iloc[:, 0])
    return cast(pd.Series, data)


def _last_valid_timestamp(series: pd.Series) -> pd.Timestamp | None:
    valid = series.dropna()
    if valid.empty:
        return None
    # valid.index can be a MultiIndex (e.g. a _SIGNAL@-prefixed time level
    # alongside a trading-day level) -- indexing a MultiIndex with [-1]
    # returns a tuple of level values, not a scalar, which pd.Timestamp(...)
    # cannot parse. DataIndex.event_timestamps() extracts just the signal
    # time level for both plain DatetimeIndex and MultiIndex inputs.
    events = DataIndex(valid.index).event_timestamps()
    if len(events) == 0:
        return None
    return cast(pd.Timestamp, events[-1])


def _trading_day(ts: pd.Timestamp) -> pd.Timestamp:
    if ts.tzinfo is not None:
        ts = cast(pd.Timestamp, ts.tz_convert("Asia/Shanghai"))
    return cast(pd.Timestamp, ts.normalize())
