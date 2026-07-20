# ADR-031: Order sizing pipeline and settlement notices

## Status

Accepted.

## Context

The native backtest engine previously implemented minimum-lot rounding and
liquidity participation as `FlowOverride`s around `OrderBookModule.size_order`.
This worked mechanically, but the observable flow graph only had one logical
node for several economically different steps:

1. target weights to raw order deltas;
2. order quantity rounding;
3. liquidity capacity capping;
4. order construction;
5. cash/margin constraints.

For strategy research and snapshot auditing, each step needs its own traceable
output. This is also cheaper to reason about than a nested override chain where
each wrapper manually calls `base_compute`.

Futures daily mark-to-market is a separate accounting issue. CME describes
futures MTM as daily official settlement prices that determine daily P/L and, if
required, margin adjustment. This is not a strategy order. Existing frameworks
often hide this inside broker/accounting logic; for this engine we need it as an
auditable event because cash, margin, snapshots, and order flow must explain why
ledger state changed.

References:

- CME Group, "Mark-to-Market", especially the daily settlement and margin
  adjustment discussion:
  https://www.cmegroup.com/education/courses/introduction-to-futures/mark-to-market
- Backtrader futures/spot compensation models expiry-related effects as
  broker/data-feed behavior, not ordinary strategy signal generation:
  https://www.backtrader.com/docu/order-creation-execution/futurespot/future-vs-spot/

## Decision

Order sizing constraints should be explicit pipeline `Flow`s, not
`FlowOverride`s:

```text
size_order(raw_deltas)
  -> round_order_quantity(sized_deltas)
  -> cap_order_liquidity(deltas)
  -> construct_orders(orders)
  -> constrain_to_ledger_cash(orders)
```

The intermediate fields are internal, strategy-scoped, and ctx-scoped:

- `raw_deltas`: target-minus-current-position before execution constraints.
- `sized_deltas`: after minimum-lot/position-sizing rules.
- `deltas`: final executable quantity delta before order construction.

`FlowOverride` remains available, but should be rare. It is only appropriate
when a module must decorate a base algorithm without changing the phase graph,
for example adding a fee/slippage side effect to an existing fill/cash update
where the business event is still the same fill. If the step has its own
economic meaning, output, progress label, or audit trace, it should be a
first-class `Flow`.

Daily mark-to-market should be implemented as a settlement notice, not as an
order notice. It does not express user or strategy intent to trade. It is a
clearing/accounting event:

1. register one notice after a product's full trading day has ended, using the
   exchange calendar and product session resolver;
2. use the official settlement price and historical margin fields;
3. realize daily variation into cash;
4. reset the next day's settlement basis;
5. recompute margin occupied;
6. emit snapshot/order-flow-style audit records.

If the engine does not yet have a dedicated settlement event kind, introduce one
instead of overloading `ORDER_NOTICE`. `ORDER_NOTICE` is for notices that may
create/cancel orders, such as rollover or force-close. Settlement mutates the
ledger directly and should be distinguishable in progress, snapshots, and tests.

## Consequences

- The order-sizing path is slightly more verbose but remains linear in the
  number of products. It does not add material runtime cost compared with the
  previous override chain, which already performed the same transformations.
- Flow manifests and progress displays can show each order-sizing step.
- Snapshot/order-flow traces can expose raw target, rounded quantity, liquidity
  cap, and final order separately.
- Settlement requires a new module, store fields for settlement basis, and tests
  for at least:
  - no-position settlement notice is a no-op but traceable;
  - long and short futures positions realize daily P/L to cash;
  - margin occupied updates after settlement;
  - night sessions map to the correct trading day;
  - exact mode errors when settlement price or margin fields are missing.

