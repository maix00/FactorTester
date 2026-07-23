# ADR-043: Exchange-style order lifecycle and bar-capacity matching

- **Date**: 2026-07-23
- **Status**: Accepted
- **GitHub issue**: #144
- **Related**: ADR-018, ADR-020, ADR-027, ADR-031, ADR-034, ADR-041, ADR-042

## Context

The native engine currently turns a target delta into one signed `Order`, clips
that delta against signal-bar volume, and later settles the remaining quantity
as a complete fill at next-bar open. This discards unfilled intent and conflates
the order request, execution capacity, fill, and ledger settlement.

Domestic futures reversals require distinct close-today, close-yesterday, and
open instructions. They may fill at different times; unfilled closes cannot
release margin.

FIX, vn.py, LEAN, and Backtrader share the relevant model: one atomic order has
stable identity, can receive multiple immutable fills, and projects cumulative
filled and remaining quantities. A partial fill does not create a child order.

## Decision

### Domain model

Keep `Order` as the atomic executable instruction. Do not introduce a competing
`OrderLeg` entity. A coordinated transition uses:

```text
Parent Intent
└── OrderGroup (orchestration and audit only)
    ├── Order(offset=close_today) ── Fill 0..N
    ├── Order(offset=close_yesterday) ── Fill 0..N
    └── Order(offset=open, waiting on closes) ── Fill 0..N
```

`OrderGroup` is never queued, matched, filled, or settled. Its state and
quantities are derived from its child Orders and Fills.

Each Order carries stable `order_id`, `order_group_id`, `parent_intent_id`,
`leg_role`, `offset`, side, requested quantity, latest accepted revision,
time-in-force, and eligibility time. Submit, cancel, and replace actions retain
immutable request identities and revision lineage. A cancel request is not a
cancel confirmation; fills may still arrive while cancel or replace is pending.

Each execution creates one immutable `Fill`. The Order projects:

```text
cumulative_filled = sum(Fill.quantity)
active_leaves = current_order_quantity - cumulative_filled
terminal_unfilled = current_order_quantity - cumulative_filled
```

After a terminal state active leaves is zero, while terminal unfilled remains
auditable. Fee, P&L, cash, and margin effects belong to settlement records
linked to Fill.

### Scheduling and matching

Keep `EventKind.ORDER`. Each actionable Order has an immutable attempt payload;
the attempt is not a child order. A partial fill schedules another attempt for
the same Order at the next eligible market-data bar. Stale attempts are skipped
by revision identity.

The nonterminal index contains scheduled, partial, and waiting Orders; the queue
contains only its actionable scheduled subset.

At one timestamp, the execution venue processes the complete batch:

```text
collect actionable Orders
→ net explicit account-level conflicts
→ allocate and settle all risk-reducing fills
→ recompute position, cash, margin, and buying power
→ activate satisfied dependencies
→ allocate and settle all risk-increasing fills
```

Reduce-before-increase is not sell-before-buy. Ties use submitted time and
Order ID rather than incidental dictionary order.

Liquidity limits apply to every Order, including closes. Reducing Orders receive
priority but no fictitious liquidity. Buying-power and hard margin-utilization
limits constrain only margin-increasing fills.

The default reversal policy activates open Orders only after required closes
settle fully. Partial release requires a named interleaved policy and hedge
accounting.

### Bar-volume causality

Matching fidelity is explicit:

| Mode | Capacity known at | Causal execution time |
|---|---|---|
| `next_bar_full_fill` | no capacity limit | next bar open |
| `lagged_bar_volume` | previous completed bar | current bar open |
| `execution_bar_volume` | execution bar completion | execution bar end |
| `tick_orderbook` | observed trades/depth | event timestamp |

The engine must not combine next-bar-open execution with that same bar's final
volume. Exact mode refuses bar proxies when exchange timestamps or
tick/trade/depth data are required.

### Target reconciliation

For target intents, let `A` be actual position, `R` retained signed leaves, and
`T` the latest target. If `A + R == T`, retain the Orders. Otherwise replace
their unfilled remainder, preserve fills, and supersede the group from `A` to
`T`.

Delta intents remain additive unless their policy explicitly selects replace,
merge, coexist, or defer. No special `$F=1m` branch changes these semantics.

## Observability and CLI

Compact step output shows group, Order, status, requested, cumulative filled,
active leaves, terminal unfilled, capacity used, and next attempt. Full detail
expands attempts, action revisions, Fills, and linked settlements without
truncation. All CLI inspection commands also provide machine-readable JSON and
use the real FactorTester backend.

## Acceptance

- Long `10` to short `5` produces close Orders totaling `10` and an open Order
  of `5`; no atomic Order mixes close and open.
- A close filled `6/10` releases only settled margin; its remainder stays live
  and the sequential open remains waiting.
- Close Orders are volume-limited but never shrunk by margin hard caps.
- One Order can produce fills across multiple eligible bars with one Order ID.
- Capacity is consumed once per venue, instrument, execution bar, and side.
- Reduce fills settle before increase fills evaluate buying power.
- Queue contents equal the actionable subset of the nonterminal Order index.
- Cancelled or superseded attempts cannot execute.
- Rapid target updates do not add an old remainder to a new target delta.
- Atomic and legged paths agree only with complete same-price fills, identical
  lot selection and rounding, linear fees without per-order minimums, and no
  intermediate constraint.
- Exact execution fails before mutation when offset, lot age, fee/margin rules,
  exchange timestamps, or required tick/trade/depth data are unavailable.

## References

- FIX Trading Community, Order State Changes and Trade business area
- vn.py `OrderData` and `TradeData`
- QuantConnect LEAN `OrderTicket`, `OrderEvent`, and target ordering
- Backtrader Order lifecycle and volume fillers
