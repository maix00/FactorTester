"""AKShare online reference source.

Mirrors ``sources.OpenCTP``: this package does not manage local OHLCV/K-line
files. It is only the online reference source for exchange-published contract
lifecycle facts (list date / last trading day / delivery window) via the
``akshare`` package, cached and normalized into local SQLite.
"""
from .client import (
    fetch_contract_info_cffex,
    fetch_contract_info_czce,
    fetch_contract_info_dce,
    fetch_contract_info_gfex,
    fetch_contract_info_ine,
    fetch_contract_info_shfe,
)
from .lifecycle import (
    CONTRACT_LIFECYCLE_TABLE,
    fetch_and_store_live,
    known_contract_codes,
    normalize_contract_info,
    read_contract_lifecycle,
    upsert_contract_lifecycle,
)

__all__ = [
    "fetch_contract_info_shfe",
    "fetch_contract_info_ine",
    "fetch_contract_info_dce",
    "fetch_contract_info_czce",
    "fetch_contract_info_cffex",
    "fetch_contract_info_gfex",
    "CONTRACT_LIFECYCLE_TABLE",
    "normalize_contract_info",
    "upsert_contract_lifecycle",
    "known_contract_codes",
    "read_contract_lifecycle",
    "fetch_and_store_live",
]
