"""Long-lived stores owned by RunState.

Stores keep module-specific persistent state out of RunState's top-level
namespace while staying cheap to access on hot paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunWindowStore:
    strategy_windows: dict[Any, Any] = field(default_factory=dict)
    envelope: tuple[Any, Any] | None = None

    def set_windows(self, windows: dict[Any, Any], envelope: tuple[Any, Any]) -> None:
        self.strategy_windows = windows
        self.envelope = envelope

    def window_for(self, strategy: Any) -> Any | None:
        return self.strategy_windows.get(strategy)


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
