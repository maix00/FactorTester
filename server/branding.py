"""TradeResearch platform naming with FactorTester compatibility."""

from __future__ import annotations

import os

PRODUCT_NAME = "TradeResearch"
LEGACY_PRODUCT_NAME = "FactorTester"
ENV_PREFIX = "TRADERESEARCH_"
LEGACY_ENV_PREFIX = "FACTORTESTER_"


def env(name: str, default: str = "") -> str:
    """Read TRADERESEARCH_* first, then legacy FACTORTESTER_*."""
    new = os.environ.get(ENV_PREFIX + name)
    if new is not None:
        return new
    return os.environ.get(LEGACY_ENV_PREFIX + name, default)


def env_flag(name: str, default: bool = False) -> bool:
    value = env(name).strip().lower()
    if not value:
        return bool(default)
    return value in {"1", "true", "yes", "on"}
