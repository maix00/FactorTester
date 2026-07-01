"""ResultStore — the front-end-facing results container.

BacktestRunState owns one ResultStore for the run, but result rows stay isolated here
by Strategy so multi-strategy/multi-group results do not leak into each other.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.strategy import Strategy


class ResultStore:
    def __init__(self) -> None:
        self._history: dict["Strategy", list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
        self._final: dict["Strategy", dict[str, Any]] = {}

    def append(self, strategy: "Strategy", timestamp: Any, **values: Any) -> None:
        self._history[strategy].append((timestamp, values))

    def history(self, strategy: "Strategy") -> list[tuple[Any, dict[str, Any]]]:
        return list(self._history.get(strategy, []))

    def set_final(self, strategy: "Strategy", **values: Any) -> None:
        self._final.setdefault(strategy, {}).update(values)

    def get_final(self, strategy: "Strategy") -> dict[str, Any]:
        return dict(self._final.get(strategy, {}))
