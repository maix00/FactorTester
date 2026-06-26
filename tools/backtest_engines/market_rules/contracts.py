"""Versioned market-rule values and explicit missing-history policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, Protocol, TypeVar

import pandas as pd


T = TypeVar("T")


class RuleProvenance(str, Enum):
    EFFECTIVE_AT = "effective_at"
    AS_OF_LATEST = "as_of_latest"
    CONFIGURED_DEFAULT = "configured_default"


class RuleFallbackPolicy(str, Enum):
    STRICT_HISTORICAL = "strict_historical"
    LATEST_AVAILABLE = "latest_available"
    CONFIGURED_DEFAULT = "configured_default"


@dataclass(frozen=True, slots=True)
class ResolvedRule(Generic[T]):
    value: T
    provenance: RuleProvenance
    effective_at: pd.Timestamp | None = None

    @property
    def approximated(self) -> bool:
        return self.provenance != RuleProvenance.EFFECTIVE_AT


class RuleProvider(Protocol, Generic[T]):
    def resolve(
        self,
        instrument: str,
        timestamp: pd.Timestamp,
        fallback: RuleFallbackPolicy,
    ) -> ResolvedRule[T]: ...
