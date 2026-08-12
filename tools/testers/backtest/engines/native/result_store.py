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
    """Per-strategy result rows with an explicit retention contract.

    ``summary`` runs only need the signal-time equity points for the public
    equity curve.  Keeping a positions/notional/margin snapshot for every
    intrabar ORDER event makes the retained Python object graph grow with the
    whole replay window even though those snapshots are not requested.  Full
    runs keep the historical behavior; summary runs deliberately discard the
    snapshot rows at the point they are produced.
    """

    def __init__(self, *, retention_mode: str = "full") -> None:
        if retention_mode not in {"summary", "full"}:
            raise ValueError("result retention_mode must be 'summary' or 'full'")
        self.retention_mode = retention_mode
        self._history: dict["Strategy", list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
        self._final: dict["Strategy", dict[str, Any]] = {}

    def append(
        self,
        strategy: "Strategy",
        timestamp: Any,
        *,
        event_kind: Any = None,
        **values: Any,
    ) -> None:
        if self.retention_mode == "summary":
            # The display curve is recorded separately by EquityCurveModule.
            # Keep only SIGNAL equity as a compact compatibility fallback;
            # intrabar position/notional/margin snapshots are not summary
            # outputs and must not accumulate in memory.
            kind_name = getattr(event_kind, "name", str(event_kind or ""))
            if kind_name != "SIGNAL" or values.get("equity") is None:
                return
            values = {"equity": values["equity"]}
        self._history[strategy].append((timestamp, values))

    def history(self, strategy: "Strategy") -> list[tuple[Any, dict[str, Any]]]:
        return list(self._history.get(strategy, []))

    def set_final(self, strategy: "Strategy", **values: Any) -> None:
        self._final.setdefault(strategy, {}).update(values)

    def get_final(self, strategy: "Strategy") -> dict[str, Any]:
        return dict(self._final.get(strategy, {}))
