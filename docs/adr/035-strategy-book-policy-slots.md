# ADR 035: StrategyBook Policy Slots

## Status

Accepted.

## Context

The native backtest engine now exposes several decisions that cross a single
strategy or module boundary:

- routing an order to a ledger,
- deciding how much cash a ledger may use,
- adjusting target deltas before order construction,
- resolving conflicts between new signals and pending orders,
- merging trade decisions or applying hierarchy constraints.

Leaving these as unrelated callables on `StrategyBookStore` makes the extension
surface hard to reason about. Moving all default behavior into StrategyBook
would be equally wrong: order sizing belongs to order construction, pending
order replacement belongs to order flow, and cash availability belongs to cash
and margin semantics.

## Decision

`StrategyBookStore` owns a single `StrategyBookPolicies` object. Each policy is
an explicit extension slot:

- `order_routing`
- `cash_availability`
- `order_sizing`
- `pending_order_conflict`
- `trade_decision_merge`
- `hierarchy_constraints`

StrategyBook hosts these slots because they are strategy/ledger orchestration
decisions. Default business implementations remain with the owning module:

- `OrderConstructModule` computes the default order deltas and lot-size sizing.
- `OrderFlowModule` owns the default pending-order conflict behavior.
- cash and margin helpers own the default available-cash behavior.

Strategy intent is a separate layer from order sizing. Target weights are one
intent format (`TargetWeightIntent`), while technical or event-driven rules may
emit direct `OrderDeltaIntent` values. `OrderConstructModule` consumes the
intent representation and turns it into order deltas/orders; StrategyBook can
override sizing or conflict behavior, but it does not own the default
membership, long-short, technical-rule, or liquidation logic.

Callers should go through module-level helpers such as
`apply_order_sizing_policy`, `apply_pending_order_conflict_policy`, and
`available_cash_for_ledger` rather than reaching into raw policy fields.

## Consequences

- Position sizing is no longer a public executable module. It is an internal
  order-construction step with a StrategyBook policy override.
- Group membership and long-short are concrete strategy-intent policies, not
  universal prerequisites for order construction.
- Strategies that do not naturally express themselves as target weights can
  bypass equity target sizing by emitting `OrderDeltaIntent`.
- Order lifecycle is not a standalone flow. Order terminal state is recorded by
  `OrderFlowModule` helpers after the business action that produced the state.
- New signal vs pending order replacement is a StrategyBook policy slot with
  the existing default behavior: a newer signal replaces a still-future order
  for the same strategy and product.
- Future richer StrategyBooks can override these decisions without changing the
  flow graph or turning StrategyBook into a backtest runner.
