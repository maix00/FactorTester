# ADR-044: Native strategy hooks and market-event kinds

- **Date**: 2026-07-27
- **Status**: Proposed for issue #172
- **Related**: ADR-018, ADR-020, ADR-026, ADR-027, ADR-034, ADR-043

## Context

The native runtime already has a causal `EventQueue`, but its public Strategy
object is currently only an identity. The only user-shaped callback is the
incremental factor executor's private `on_bar` seam. This makes a small custom
event strategy need to know about `Flow`, `FieldRef`, `EventDraft`, and the
order-construction graph.

The runtime also currently names the aggregate replay event `BAR`. That name
must not be reused for L1 quotes, trades, or L2/L3 order-book updates. A bar is
an aggregate observation with an explicit visibility policy; a quote or book
delta is an atomic market-data observation whose sequence affects matching and
queue position.

## Decisions

### 1. Public hooks are a small adapter, not a second execution engine

The public author API has optional no-op methods:

```text
on_start(ctx)
on_stop(ctx)
on_event(ctx, event)  # generic fallback
on_bar(ctx, bar)
on_quote(ctx, quote)
on_trade(ctx, trade)
on_book_delta(ctx, delta)
on_book_snapshot(ctx, snapshot)
on_order_event(ctx, order)
on_order_<status>(ctx, order)  # e.g. on_order_canceled
```

`on_market_feed(ctx, event)` is the generic fallback for market-feed types
without a dedicated method, and `on_event(ctx, event)` is the final fallback
across feed, BAR, and order events. The adapter calls the most specific
overridden method first. A strategy does not need to implement every hook.

Order callbacks are observational. A callback returns a typed target or order
delta intent; it never mutates `Ledger`, `MarketDataStore`, `Order`, or the
event queue directly. The adapter converts returned intents into the existing
`SIGNAL → sizing → risk → execution → ledger` pipeline.

Cancel/replace commands remain an internal lifecycle capability until their
immutable action records are exposed through the same typed command adapter.
This prevents a first public API from bypassing the issue-144 order lineage.

### 2. BAR is not the L2/L3 event kind

`EventKind.MARKET_FEED` is a coarse scheduler priority for raw feed events.
Its payload carries a typed `MarketFeedEventKind`:

| payload kind | data level | author hook |
|---|---|---|
| `QUOTE` | L1 BBO | `on_quote` |
| `TRADE` | trade tick | `on_trade` |
| `BOOK_DELTA` | L2 MBP or L3 MBO delta | `on_book_delta` |
| `BOOK_SNAPSHOT` | L2/L3 snapshot | `on_book_snapshot` |

`EventKind.BAR` remains the aggregate-bar event. Raw market events are ordered
before BAR and ORDER at the same timestamp; equal timestamp events retain the
feed sequence. L2/L3 do not require separate scheduler kinds unless a future
matching model needs a different priority. The payload kind is the extensible
boundary, while `EventKind` remains the scheduling boundary.

`BarStrategy` consumes aggregate BAR events only. When a user has only L2/L3
data but wants a bar strategy, a separate `MarketDataAggregator` actor must
consume the raw book/trade events and publish a derived BAR event with an
explicit close/visibility timestamp. It is not correct to pass a book delta to
`on_bar` or to silently aggregate future book updates inside the strategy.

### 3. Data fidelity is declared separately from hook shape

The strategy declares required market events and execution capabilities. L1/BAR
can use an explicit capacity/fill model, but must not silently claim queue-level
fidelity. L2/L3 provide more precise book state and matching inputs without
changing the strategy source API.

The preflight report must distinguish:

- requested data (`bar`, `quote`, `trade`, `book_delta`)
- available data level (`L1`, `L2_MBP`, `L3_MBO`)
- fill model (`next_bar_full_fill`, `bar_volume_limited`, `book_matching`)
- whether partial fills and residual carry are supported

## Event ordering

```text
FIELD_CHANGE
→ MARKET_FEED (quote/trade/book delta)
→ BAR
→ ORDER (existing orders consume the observation)
→ POSITION (a successful fill updates a position)
→ SIGNAL (strategy decisions)
→ LEDGER
```

The exact existing signal/order ordering remains unchanged for legacy runs;
new raw market events only occupy the previously unused priority slot before
BAR. A hook-generated intent is queued as a causal SIGNAL at the same or later
timestamp and therefore goes through the existing order pipeline.

## Consequences

- Simple strategies need only subclass `BarStrategy` or `EventStrategy` and
  return target/order intents.
- Order-aware strategies can override a status-specific callback for the
  native order vocabulary (`blocked`, `submitted`, `accepted`,
  `partially_filled`, `pending_cancel`, `pending_update`, `filled`,
  `cancelled`, `rejected`, `expired`); each falls back to `on_order_event`.
- L2/L3 events are first-class and cannot be confused with aggregate bars.
- The ledger and issue-144 order lifecycle remain the sole owners of fills,
  fees, margin, DMTM, cancellation, replacement, and residual orders.
- Position events are emitted only after a fill is posted to the ledger. They
  carry immutable snapshots and never grant a strategy a mutable ledger handle.
- Account/ledger and clock/timer events remain internal native infrastructure;
  exposing them later requires an explicit payload and ownership contract.
- Adding a new market-data format only adds a payload type and a hook adapter;
  it does not multiply scheduler phases or rewrite Strategy authors' code.
