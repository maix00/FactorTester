"""Strategy — a lightweight per-strategy identity object, same base class
as Product so it can be used directly as a dict key (UniqueNameObject
implements __eq__/__hash__)."""

from __future__ import annotations

from typing import Any

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

    def on_order_scheduled(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_accepted(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_partially_filled(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_cancel_pending(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_replace_pending(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_filled(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_canceled(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_rejected(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)

    def on_order_expired(self, ctx: Any, order: Any) -> Any:
        return self.on_order_event(ctx, order)


class BarStrategy(Strategy):
    """Convenience base for strategies whose author input is aggregate bars."""


class EventStrategy(Strategy):
    """Convenience base for quote/trade/order-book event strategies."""


class OrderAwareStrategy(EventStrategy):
    """Convenience base for strategies that also consume order lifecycle events."""
