"""Optional Nautilus feed contract for source-owned adapters.

Only immutable metadata is defined here. Importing this module does not load
Nautilus, TradeResearch internals, plugins or market data.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NautilusAdapterContract:
    """Source-owned declaration of one verified Nautilus feed adapter.

    The source owns its physical schema and time semantics. The bridge only
    compares this declaration with the catalog projection before admitting it.
    """

    member_key: str
    adapter_id: str
    frequency: str
    sampling_mode: str
    data_kind: str
    market_depth: str
    delivery_mode: str
    timezone: str
    layout: str
    naming_scheme: str
    required_time_columns: tuple[tuple[str, str], ...]
    required_data_columns: tuple[tuple[str, str], ...]
    clock_policy: str
    product_scope: str
    instrument_scope: str = "unspecified"
    bar_time_semantics: str = "unspecified"
    raw_timestamp_unit: str = "unspecified"
    supported_book_types: tuple[str, ...] = ()


__all__ = ["NautilusAdapterContract"]
