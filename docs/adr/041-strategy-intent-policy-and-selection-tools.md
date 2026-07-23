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

## References

- https://pmorissette.github.io/bt/index.html
- https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst
- https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/portfolio-construction/key-concepts
- https://zipline.ml4trading.io/api-reference.html
