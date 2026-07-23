# ADR-041: Strategy intent policies and reusable selection tools

- **Date**: 2026-07-23
- **Status**: Accepted
- **Related**: ADR-023, ADR-024, ADR-029, ADR-032, ADR-035

## Context

`StrategyIntentPolicy` is currently split across three owners:

- a global `strategy_kind -> policy` registry used by precomputation;
- separate executable group, threshold, and long-short flows used during replay;
- a `StrategyBookPolicies.strategy_intent_precompute` callable that can replace
  only the batch path.

This split permits the live and precomputed implementations to drift. It also
makes group testing look like a prerequisite of the backtest engine rather than
one built-in strategy-intent policy.

The established external contracts point to the same separation:

- `bt` composes scheduling, selection, weighting, and rebalancing algorithms.
- Qlib strategies produce target positions; its order generator converts targets
  into orders.
- LEAN separates universe/insight production, portfolio targets, and execution.
- Zipline separates Pipeline factors/screens from target orders.

The common industry meaning is that selection and entry/exit state do not by
themselves specify transaction quantity. A strategy produces a desired target;
the order layer trades the difference from current holdings.

## Decision

### StrategyBook owns policy resolution

`StrategyBookPolicies` remains the one policy container. It distinguishes:

- per-strategy intent policies;
- book-level coordination policies such as decision merge and hierarchy;
- ledger/order overrides such as routing, cash availability, and sizing.

The container is not itself one flat toolkit. A slot becomes a reusable tool
only when it has a stable decision contract and useful composition semantics:

- intent selection, decision merge, hierarchy constraints, target allocation,
  and standard capacity/risk constraints are named toolkit components;
- order routing, cash availability, and pending-order conflict remain runtime
  boundary hooks because they inspect mutable ledger or order state;
- target sizing belongs to allocation, while target-to-order conversion and
  executable capacity remain in the order layer.

`StrategyIntentPolicy` becomes a first-class per-strategy policy resolved by
the StrategyBook. The global strategy-kind registry remains only as the catalog
of built-in defaults during migration. A precompute-only override is not the
owner of strategy semantics.

### One intent interface, two execution adapters

A strategy-intent policy produces `TradeIntent` from a strategy context. The
same policy semantics are used by:

- an event adapter for replay and step inspection;
- a vectorized adapter for policies that declare a compilable selection plan.

Unsupported custom Python logic falls back to the event adapter. It must never
silently use a different vectorized algorithm.

### Reusable policy tools

Policies may compose three tool families:

- cross-sectional selection: `screen`, `rank`, `split`, `top`, `bottom`;
- rebalance: full target, buy-and-hold, membership change, bounded replacement,
  and later a turnover budget;
- allocation: equal notional, inverse volatility, equal margin, and registered
  future allocators.

The tools own canonical semantics and diagnostics. Built-in group policy is a
cross-sectional policy whose standard plan is screen, rank, split, select,
rebalance, and allocate. Its vectorized implementation is an optimization of
the same plan.

### Factor roles belong to a policy

A strategy may bind factors to named roles declared by its selected policy.
Initial roles are `ranking`, `screen`, `entry`, `exit`, and `sizing`.

- Group policy requires `ranking` and may use `screen` or `sizing`.
- Threshold-state policy uses `entry` and `exit`, which may reference the same
  factor for backward compatibility.

Entry and exit factors produce selection or position state. Allocation or a
`sizing` factor produces target weight. Neither creates an order quantity.

### Factor-role execution and causal state

Role factor evaluation belongs to `FactorSignalModule`, not to an intent
policy. Precomputed mode may evaluate role factors into causal tables during
`PRE_REPLAY`; incremental mode updates the same role values from BAR events.
The intent policy consumes those values in timestamp order.

Entry/exit hysteresis remains a state transition even when its inputs are
precomputed. A precompute adapter may compile the ordered transitions into a
target-intent table, but must not replace them with independent vectorized
comparisons. At each SIGNAL event the event adapter either computes the same
transition from published role values or applies the compiled intent.

Missing role values are explicit: a missing entry value cannot open a new
position, and a missing exit value cannot silently fall back to the ranking or
primary factor to preserve one. Backward compatibility applies only when a
role is unbound, in which case the policy deliberately binds it to the primary
factor.

### Group membership and quantity

For group policy, membership change is the entry/exit meaning:

- entering a selected bucket creates a non-zero target;
- leaving it creates a zero target;
- remaining selected may still change target weight.

`OrderConstructModule` continues to calculate target quantity minus current
quantity. Product masks remain a post-bucket intersection and never cause
reranking.

### User surfaces

The selected intent policy owns its configuration Interface. Web and CLI obtain
the policy catalog, factor roles, and policy-specific fields from the backend
manifest. They do not expose every policy field simultaneously.

The CLI-Anything harness wraps the real `factortester` HTTP CLI. It provides
human-readable and JSON inspection plus workspace mutation commands; it does
not reimplement policy resolution locally.

### Boundary-policy audit

`StrategyBookPolicies` is a suitable registration and resolution container for
book-level policies. It is not the execution owner of every registered policy.
The module that owns a lifecycle transition must call the policy, validate its
decision, apply it, and publish the corresponding audit output.

The current callable contracts are too weak for that rule:

- `order_routing(state, order) -> ledger` is sufficient only for a pure,
  deterministic, single-ledger mapping. The result is currently resolved each
  time `state.ledger_for(order)` is called instead of being frozen. In
  addition, target-minus-current reads positions through the strategy/product
  ledger mapping before the order-routing hook runs. A custom route can
  therefore calculate a delta from one ledger and later book it to another.
- `cash_availability(state, ledger, cash, reason) -> float` can express a
  static reserve, but not a buying-power decision over a candidate order
  batch. It has no explicit timestamp, cash-pool identity, candidate orders,
  pending reservations, same-batch proceeds, or per-order result. Signal-order
  funding, execution-order funding, and margin funding are distinct decisions
  currently multiplexed through an untyped `reason` string.
- `pending_order_conflict(state, strategy, order, timestamp) -> None` has no
  decision result. After the hook returns, scheduling unconditionally marks
  the new order scheduled, overwrites the `(strategy, instrument)` pending
  index, and emits its event. The hook cannot coherently express reject-new,
  keep-existing, merge, coexist, or defer. It is also called before the new
  order receives its planned execution and price timestamps.

There are two ownership problems in addition to those contract problems:

- accounting-ledger assignment and execution-venue routing are different
  semantics. The former must be known before target-minus-current; the latter,
  if introduced later, belongs to execution and must not change accounting
  ownership;
- generic order scheduling and pending-order resolution currently live in the
  group-membership module even though threshold, long-short, and custom intent
  policies need exactly the same order lifecycle.

Finally, these policy objects are not declared Flow inputs and their decisions
are not structured Flow outputs. Step mode can show the resulting quantity or
order, but cannot establish which policy ran, what action it selected, or why.

### Uniform decision behavior

Boundary policies use one decision envelope, not one universal business
payload. `RouteDecision`, `BuyingPowerDecision`, and `PendingOrderDecision`
retain domain-specific fields, while every decision follows the same behavioral
contract:

- the policy returns a value and does not directly mutate ledger, order queue,
  pending index, or cash-pool state;
- the owning module validates and applies the returned value atomically;
- the decision is deterministic for the same frozen request and policy
  configuration;
- the value is serializable and contains `policy_id`, `policy_version`, a
  domain action, a stable `reason_code`, a concise reason, effective timestamp,
  input digest, domain payload, diagnostics, and implementation provenance;
- the default policy returns the same envelope as a custom policy; there is no
  invisible special-case path;
- step output shows a compact decision summary, while an explicit CLI command
  can print the complete request, decision, and provenance;
- invalid or incomplete decisions fail before state mutation and identify the
  policy and rejected field.

The shared envelope is an Interface and audit protocol. It must not become a
dictionary of optional fields. Domain decisions remain typed dataclasses or
Protocols with their own validation:

```text
PolicyDecision envelope
├── RouteDecision: position_ledger_id
├── BuyingPowerDecision: cash_pool_id, available amount, order limits
└── PendingOrderDecision: replace/cancel_new/merge/coexist/defer + result set
```

### Boundary-policy target design

Accounting ledger ownership is resolved before target conversion:

1. `PositionLedgerPolicy` receives strategy, product, signal timestamp, target
   intent identity, and declared ledger candidates.
2. `PositionLedgerModule` validates one declared ledger and freezes the
   decision in the target/order lineage.
3. Target-minus-current reads positions from that frozen ledger.
4. Cash, fee, margin, fill, and settlement consume the same ledger identity;
   none re-runs the policy.

If venue or broker routing is needed later, a separate execution policy may
split an already-accounted order into execution children. Those children must
retain the parent accounting ledger.

Cash handling is separated by decision meaning:

- `CashReservePolicy` is a pure ledger/cash-pool reserve rule and replaces the
  current simple `cash_availability` use case;
- `BuyingPowerPolicy` receives one cash pool, all participating ledgers, current
  positions and reservations, and the complete candidate order batch, then
  returns allowed per-order quantities or notionals;
- `MarginFundingPolicy` handles a margin-requirement change and returns paid
  amount, deficit, and required follow-up action.

Signal-time cash checks remain an early causal estimate. Execution-time checks
use resolved execution price, slippage, and fee and are authoritative. Both
group by cash-pool identity rather than ledger object identity.

Pending-order resolution moves to a generic `OrderSchedulingModule`:

1. construct an immutable order draft and resolve its execution/price times;
2. collect all relevant existing pending orders;
3. call `PendingOrderPolicy` with the draft, planned timestamps, existing
   orders, and lifecycle context;
4. validate the returned result set;
5. atomically update statuses, pending indexes, event queue, and audit trail.

The first supported actions are `replace`, `cancel_new`, `merge`, `coexist`,
and `defer`. `coexist` requires a multi-order pending index; it cannot be
implemented by overwriting the current single `(strategy, instrument)` entry.

### Migration sequence

1. Introduce the decision envelope and domain decision types without changing
   default behavior.
2. Add compact step serializers and stable JSON output for the three decision
   families.
3. Resolve and freeze accounting-ledger ownership before target conversion;
   keep the old routing callable behind a compatibility adapter that is invoked
   exactly once.
4. Move generic scheduling out of group membership and adapt the legacy
   pending hook to `replace` semantics. Reject legacy custom hooks whose side
   effects cannot be represented safely instead of silently guessing intent.
5. Split cash reserve, buying power, and margin funding. Change batching from
   ledger identity to cash-pool identity before enabling shared-pool custom
   policies.
6. Remove compatibility adapters only after persisted RunSpecs identify the
   new policy contract version.

The migration must not change fees, margin rules, liquidity limits, DMTM,
product-mask semantics, or intent-policy target traces.

## Consequences

- Group, threshold, and long-short become peer built-in intent policies.
- Live and precomputed target traces must be equivalent for every built-in
  policy and every compilable selection plan.
- Existing flat settings and `strategy_intent_mode` remain readable through a
  migration adapter, but new RunSpecs freeze policy identity, factor bindings,
  policy parameters, and implementation provenance.
- Policy tools improve leverage while keeping market data, ledger, margin,
  fees, capacity, and execution in their current owners.
- A custom policy may sacrifice vectorized speed, but never semantic fidelity.

## Acceptance invariants

- Binding entry and exit to the primary factor reproduces the legacy threshold
  selection and target trace at every event.
- Distinct entry/exit factors produce identical selection, target weights, and
  transition reasons in event and precomputed adapters.
- Changing factor values after a timestamp cannot change any earlier intent.
- Flow contracts expose `factor_role_bindings`, `factor_role_values`, and
  `trade_intent` without undeclared reads; step output summarizes the role
  values and transition reason.
- Missing entry values do not enter and missing exit values exit explicitly.
- Order construction remains target minus current position; fee, margin,
  liquidity, and DMTM behavior is unchanged.

### Boundary-policy acceptance

- A route-policy spy is called exactly once per target/order lineage. The
  target delta, signal cash check, execution cash check, fee, fill, settlement,
  and position snapshot all report the same frozen accounting ledger.
- Routing to an undeclared ledger fails before cash, fee, queue, or ledger
  mutation. Route decisions expose policy identity, reason, and provenance in
  both step and JSON output.
- Two distinct ledgers sharing one cash pool and submitting simultaneous buys
  are constrained as one batch. Their combined spend and reservations never
  exceed the policy decision, irrespective of strategy iteration order.
- Signal and execution buying-power decisions are separately recorded; the
  execution decision uses actual execution price, slippage, fee, and pending
  reservations. Margin funding uses its own typed request and decision.
- Pending-order tests cover no conflict, replace, cancel-new, merge, coexist,
  and defer. After each action, the pending index and event queue contain the
  same live order set and no cancelled or untracked order can execute.
- Pending policy input includes the new planned execution and price timestamps
  plus all relevant existing orders. The behavior is identical for group,
  threshold, long-short, and custom intent policies.
- Default and custom policies pass the same validation and application path.
  A policy cannot mutate cash, ledgers, queues, or order status while deciding.
- Replaying a frozen request with the same policy version produces an identical
  serialized decision. Changing strategy iteration or dictionary insertion
  order does not change the result.
- Step mode prints one compact row per material decision with policy, action,
  reason, and key amounts/identities. A dedicated CLI detail command prints the
  full request, result, diagnostics, and provenance without truncation.
- Existing single-ledger, shared-ledger, fee/slippage/liquidity, margin, DMTM,
  event-vs-precomputed intent, and equity-curve regression suites remain green.

## References

- https://pmorissette.github.io/bt/index.html
- https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst
- https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/portfolio-construction/key-concepts
- https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/buying-power
- https://www.quantconnect.com/docs/v1/algorithm-framework/execution
- https://zipline.ml4trading.io/api-reference.html
