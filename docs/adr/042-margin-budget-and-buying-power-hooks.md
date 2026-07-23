# ADR-042: Margin budget and buying-power hooks

- **Date**: 2026-07-23
- **Status**: Accepted
- **Related**: ADR-031, ADR-032, ADR-033, ADR-035, ADR-041

## Context

Group allocation currently produces relative target weights and
`OrderConstructModule` interprets a gross weight of one as one times equity.
That cash-account convention underuses futures capital. The signal cash check
then compounds the problem by treating every positive futures order as if its
full notional were cash expenditure.

The framework needs three distinct decisions:

1. how selected products share relative notional exposure;
2. how far the complete cash-pool portfolio is scaled toward a margin budget;
3. whether the executable order batch fits the hard buying-power limit.

LEAN similarly separates portfolio targets, risk adjustment, execution, and
buying-power checks. It also orders position-reducing trades ahead of orders
that increase margin impact. Backtrader supplies cash and commission/margin
information to a sizer but leaves sizing separate from its futures accounting
model. These are boundary references, not imported defaults.

## Decision

### Enabled margin has one default semantic

When effective `margin_mode` is `auto`, `exact`, `custom`, or `fixed`:

- allocation defaults to `equal_notional` (shown to users as 等名义敞口);
- `target_margin_utilization` defaults to `0.80`;
- `max_margin_utilization` defaults to `0.85`;
- the target margin budget is always converted into and reported as total
  gross notional leverage.

There is no implicit `legacy_gross_1x` fallback in margin mode. When margin is
explicitly disabled, target weights keep their cash-account meaning and no
margin-budget scaling is applied. Users may configure the target and maximum,
subject to `0 < target <= max < 1`.

### Target scaling is a cash-pool policy

Allocation produces relative signed notional weights. `MarginBudgetModule`
runs after strategy intents and signal-time equity, but before order sizing. It
groups every participating strategy and ledger by cash-pool identity and makes
one decision for the whole pool.

For each target product it resolves the historical long/short margin rule at
the causal signal timestamp. A product that is not margin-accounted uses
`m_i = 1.0`, even when it shares a portfolio with margin-accounted products;
its full notional therefore participates in the weighted capital requirement.
With raw target notional `N_i` and margin ratio `m_i`:

```text
raw projected margin = sum(abs(N_i) * m_i)
pool scale = target utilization * pool equity / raw projected margin
scaled target notional = raw target notional * pool scale
gross leverage = sum(abs(scaled target notional)) / pool equity
```

The same pool scale preserves equal-notional, equal-margin, inverse-volatility,
or factor-sizing relationships. A shared pool never grants each strategy a
separate 80% budget. Conflicting target/max settings within one pool fail
before order creation.

The policy returns a typed, serializable decision. The owning module validates
and applies it to `TargetWeightIntent`; the policy does not mutate intents,
orders, positions, or cash.

### Buying power is authoritative at execution

The signal-stage check is a causal estimate. For margin-accounted products it
uses incremental margin requirement, expected fees, expected realized loss,
and configured reserve. It never uses full futures notional as cash cost.

The execution-stage check uses resolved execution prices, slippage, fees,
current positions, and current historical margin rules. It simulates the
complete cash-pool order batch and enforces both available cash and
`max_margin_utilization`.

Orders that reduce absolute position exposure are applied before increasing
orders. A hard cap may proportionally reduce only the margin-increasing part of
the batch. Closing or otherwise margin-releasing orders are never blocked by
the cap. Quantity rounding is applied after scaling and the resulting error is
reported.

### Drift remains a margin-risk event

Price moves, losses, DMTM, or a historical margin-rule increase can move an
existing portfolio above the hard limit. Normal signal events rebalance toward
the target; they do not mechanically trade every bar. Existing margin-check
and liquidation events remain responsible for post-fill drift and use the
same cash-pool utilization calculation.

### Hook ownership

`StrategyBookPolicies` registers overrides, while lifecycle modules own their
application:

- `margin_budget` receives an immutable cash-pool target request and returns a
  target scale plus diagnostics;
- `buying_power` receives an immutable cash-pool order-batch request and
  returns allowed quantities plus diagnostics;
- margin funding/liquidation remains owned by `MarginModule`.

Both hooks use structured decisions with policy identity, reason code,
effective timestamp, pool identity, and diagnostics. Compact step output is
the default; CLI detail output may expose the complete request and decision.

## Step and result contract

Every margin-budget decision reports at least:

- cash-pool equity;
- target margin and projected margin;
- weighted margin ratio;
- target scale;
- gross notional leverage;
- projected utilization before and after quantity rounding;
- rounding error and hard-limit headroom.

These are numerical results, not log-only prose, so Web, CLI, persisted run
artifacts, and step mode consume the same fields.

## Acceptance invariants

- Equal-notional allocation remains equal after margin-budget scaling.
- Equal-margin allocation produces equal projected margin contributions.
- Mixed cash and margin products give cash products a `1.0` margin ratio in
  the portfolio-weighted calculation.
- Initial projected utilization is within configured tolerance of 80%, unless
  whole-lot rounding or unavailable buying power is explicitly reported.
- Two strategies sharing a cash pool consume one combined target and maximum.
- Signal estimation and execution simulation both use incremental futures
  margin rather than full notional.
- Actual execution does not actively increase utilization beyond 85%.
- Margin-releasing quantities are never reduced by the hard cap.
- Historical margin changes and DMTM losses feed the existing margin-risk
  event path.
- Step output exposes gross leverage and the other fields above without
  dumping per-product internals by default.

## Consequences

Historical margin-mode backtests intentionally change because their old
one-times-notional fallback was not the desired product semantic. Cash-mode
backtests remain unscaled. A configured 80% margin target is a capital budget,
not a risk guarantee; volatility-aware allocation and independent risk limits
remain separate policies.
