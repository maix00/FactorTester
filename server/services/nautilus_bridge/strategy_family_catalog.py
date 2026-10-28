"""Compatibility re-export; strategy families belong to TradeResearch."""

from server.services.strategy_family_catalog import (
    PUBLIC_STRATEGY_FAMILIES,
    list_public_strategy_families,
    strategy_family,
)

__all__ = [
    "PUBLIC_STRATEGY_FAMILIES",
    "list_public_strategy_families",
    "strategy_family",
]
