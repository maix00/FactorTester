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
