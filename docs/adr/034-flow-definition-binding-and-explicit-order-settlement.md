# ADR 034: Flow Definition/Binding Split and Explicit Order Settlement

## Status

Accepted.

## Context

The native engine needs flows to be visible to the frontend/CLI progress model
and to cross-framework audits. Some logical steps also run in multiple runtime
locations: for example, market snapshot lookup is the same operation when
bound to BAR, SIGNAL, ORDER, TRADE_INTENT, or LEDGER events.

The older `Flow` shape mixed two concerns:

- what the step does;
- where it is scheduled.

The older `FlowOverride` wrapper also hid business behavior, especially fee and
slippage, inside another flow's compute chain. That made the flow graph less
auditable and made order settlement semantics depend on wrapper registration
order.

## Decision

Introduce two explicit concepts:

- `FlowDefinition`: logical step identity, inputs, outputs, compute, owner, and
  default UI/progress description.
- `FlowBinding`: phase/event-kind/order placement for a definition, with an
  optional binding name and description.

Keep `Flow(...)` as a single-binding convenience for one-off steps while modules
incrementally migrate.

Remove `FlowOverride`. Fee and slippage are now explicit ORDER flows:

1. `resolve_execution_price`
2. `apply_slippage`
3. `resolve_fee_cost`
4. `apply_order_fill`
5. `equity_on_order`
6. `finalize_order`

`resolve_fee_cost` only writes `order.fee_cost` and applies pre-settlement cash
constraint resizing. `apply_order_fill` performs the atomic ledger action:
reject/cancel handling, cash update, position update, margin sync, order trace,
and terminal order status (`FILLED` or `REJECTED`). `finalize_order` no longer
decides state; it only records terminal state and raises if an ORDER event
escapes without a terminal status.

## Consequences

- The flow graph is closer to the business process shown to users.
- A single logical definition can be bound to multiple phases or event kinds
  without duplicating compute code.
- Binding names can remain stable for strategy activation and existing
  manifests while definition names expose the shared logical step.
- Fee/slippage/settlement order is explicit and testable through scheduler
  ordering instead of hidden wrapper composition.
- Future pipeline customization should add or replace explicit flows at clear
  lifecycle boundaries, not wrap arbitrary flows.
