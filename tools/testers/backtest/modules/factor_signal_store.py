from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FactorSignalStore:
    precomputed_tables: dict[Any, Any] = field(default_factory=dict)
    precomputed_table_keys: dict[Any, Any] = field(default_factory=dict)
    live_price_tables: dict[Any, Any] = field(default_factory=dict)
    live_executors: dict[Any, Any] = field(default_factory=dict)

    def put_precomputed_table(self, key: Any, table: Any) -> None:
        self.precomputed_tables[key] = table

    def bind_precomputed_table(self, strategy: Any, key: Any) -> None:
        self.precomputed_table_keys[strategy] = key

    def precomputed_table_for(self, strategy: Any, fallback_key: Any = None) -> Any:
        key = self.precomputed_table_keys.get(strategy, fallback_key)
        return self.precomputed_tables.get(key)
