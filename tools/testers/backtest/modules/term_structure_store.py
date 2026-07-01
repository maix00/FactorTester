from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TermStructureStore:
    expanded_contracts: dict[Any, Any] = field(default_factory=dict)
    contract_metadata: dict[Any, Any] = field(default_factory=dict)
    target_mapping: dict[Any, dict[str, Any]] = field(default_factory=dict)
    notices: list[dict[str, Any]] = field(default_factory=list)

    def set_expansion(self, contracts: dict[Any, Any], metadata: dict[Any, Any]) -> None:
        self.expanded_contracts = contracts
        self.contract_metadata = metadata

    def record_target_mapping(self, strategy: Any, timestamp: Any, mapping: dict[str, str | None]) -> None:
        self.target_mapping.setdefault(strategy, {})[str(timestamp)] = mapping

    def record_notice(self, payload: dict[str, Any]) -> None:
        self.notices.append(payload)
