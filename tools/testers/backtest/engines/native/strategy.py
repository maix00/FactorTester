"""Strategy — a lightweight per-strategy identity object, same base class
as Product so it can be used directly as a dict key (UniqueNameObject
implements __eq__/__hash__)."""

from __future__ import annotations

from typing import Any, Final

from tools.data.types.base import UniqueNameObject


class Strategy(UniqueNameObject):
    """A user-owned actor instance for one backtest run.

    ``Strategy`` is not a Flow, broker, ledger, or policy container. The
    scheduler keeps one instance alive for the run and invokes its callbacks
    in event order. The instance may keep private state between callbacks and
    returns typed intents/commands; the owning Flow validates and executes
    those requests. ``name`` remains ``<shortAlias>:<32-hex-uuid>`` for
    stable runtime identity while ``alias`` is the user-facing name.
    """

    # These methods deliberately do nothing.  The native scheduler invokes
    # them only through the strategy-hook adapter, so legacy declarative
    # strategies remain pure identities and pay no callback cost.
    def on_event(self, ctx: Any, event: Any) -> Any:
        return None

    def on_start(self, ctx: Any) -> Any:
        return None

    def on_stop(self, ctx: Any) -> Any:
        return None

    def on_market_feed(self, ctx: Any, event: Any) -> Any:
        return self.on_event(ctx, event)

    def on_bar(self, ctx: Any, bar: Any) -> Any:
        return self.on_event(ctx, bar)

    def on_quote(self, ctx: Any, quote: Any) -> Any:
        return None

    def on_trade(self, ctx: Any, trade: Any) -> Any:
        return None

    def on_book_delta(self, ctx: Any, delta: Any) -> Any:
        return None

    def on_book_snapshot(self, ctx: Any, snapshot: Any) -> Any:
        return None

    def on_order_event(self, ctx: Any, order: Any) -> Any:
        return self.on_event(ctx, order)

    def on_order_blocked(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_submitted(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_accepted(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_partially_filled(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_pending_cancel(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_pending_update(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_filled(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_canceled(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_rejected(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_expired(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_position_event(self, ctx: Any, position_event: Any) -> Any:
        return self.on_event(ctx, position_event)

    def on_position_opened(self, ctx: Any, position_event: Any) -> Any:
        return self.on_position_event(ctx, position_event)

    def on_position_changed(self, ctx: Any, position_event: Any) -> Any:
        return self.on_position_event(ctx, position_event)

    def on_position_closed(self, ctx: Any, position_event: Any) -> Any:
        return self.on_position_event(ctx, position_event)


# One authoritative list is used by runtime capability discovery and event
# dispatch.  Keeping it next to the Actor base class prevents a new callback
# from being silently omitted by one of those paths.
STRATEGY_CALLBACKS: Final[tuple[str, ...]] = (
    "on_start",
    "on_stop",
    "on_event",
    "on_market_feed",
    "on_bar",
    "on_quote",
    "on_trade",
    "on_book_delta",
    "on_book_snapshot",
    "on_order_event",
    "on_order_blocked",
    "on_order_submitted",
    "on_order_accepted",
    "on_order_partially_filled",
    "on_order_pending_cancel",
    "on_order_pending_update",
    "on_order_filled",
    "on_order_canceled",
    "on_order_rejected",
    "on_order_expired",
    "on_position_event",
    "on_position_opened",
    "on_position_changed",
    "on_position_closed",
)


def overridden_strategy_callbacks(strategy: Any) -> frozenset[str]:
    """Return callbacks implemented by this Actor, excluding base no-ops."""

    actor_type = type(strategy)
    return frozenset(
        name
        for name in STRATEGY_CALLBACKS
        if callable(getattr(actor_type, name, None))
        and getattr(actor_type, name) is not getattr(Strategy, name)
    )




class BarStrategy(Strategy):
    """Convenience base for strategies whose author input is aggregate bars."""


class EventStrategy(Strategy):
    """Convenience base for quote/trade/order-book event strategies."""


class OrderAwareStrategy(EventStrategy):
    """Convenience base for strategies that also consume order lifecycle events."""
