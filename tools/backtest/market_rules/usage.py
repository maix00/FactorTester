"""Run-scoped journal of market-rule provenance used by execution actors."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .contracts import ResolvedRule, RuleProvenance


@dataclass(frozen=True, slots=True)
class RuleUsage:
    rule_kind: str
    instrument: str
    timestamp: pd.Timestamp
    provenance: RuleProvenance


class RuleUsageJournal:
    def __init__(self) -> None:
        self._records: list[RuleUsage] = []

    @property
    def records(self) -> tuple[RuleUsage, ...]:
        return tuple(self._records)

    @property
    def approximation_count(self) -> int:
        return sum(record.provenance != RuleProvenance.EFFECTIVE_AT for record in self._records)

    def record(
        self,
        rule_kind: str,
        instrument: str,
        timestamp: pd.Timestamp,
        resolved: ResolvedRule,
    ) -> None:
        self._records.append(RuleUsage(
            rule_kind,
            instrument,
            pd.Timestamp(timestamp),
            resolved.provenance,
        ))
