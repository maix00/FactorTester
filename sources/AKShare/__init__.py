"""AKShare-compatible online fetch adapters.

This package owns provider-specific fetch/cache wrappers only. Unified contract
lifecycle schema, storage, audit, and backfill code lives in
``sources.ContractLifecycle``.
"""
from .client import (
    fetch_contract_info_cffex,
    fetch_contract_info_czce,
    fetch_contract_info_dce,
    fetch_contract_info_gfex,
    fetch_contract_info_ine,
    fetch_contract_info_shfe,
)

__all__ = [
    "fetch_contract_info_shfe",
    "fetch_contract_info_ine",
    "fetch_contract_info_dce",
    "fetch_contract_info_czce",
    "fetch_contract_info_cffex",
    "fetch_contract_info_gfex",
]
