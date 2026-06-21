# ADR-023: Rebalance, allocation, market-rule quality, and evaluation ranges

- **Date**: 2026-06-21
- **Status**: Accepted
- **Related**: ADR-018, ADR-019, ADR-020, ADR-021, ADR-022

## Context

The group-test UI currently uses `each_period`, `buy_and_hold`, and `recycle`
without defining which clock emits a period. It also mixes portfolio allocation,
margin affordability, market-rule lookup, and result presentation. External
frameworks expose similar extension points, but their defaults are not
semantically interchangeable.

Installed framework source confirms these boundaries:

- Backtrader strategies run on `next`; `order_target_percent` is an explicit
  rebalance request. Commission/margin (`CommInfoBase`) and volume fillers are
  broker extensions.
- Qlib `WeightStrategyBase` produces target weights on a trade-calendar step;
  `OrderGenerator` converts them using the exchange price, costs, tradability,
  and trade unit.
- Zipline exposes scheduled callbacks and `order_target_percent`; commission,
  slippage, futures multipliers, and the ledger are separate components.
- Alphalens equal-weight factor portfolios normalize selected assets to a fixed
  gross exposure. Margin is not an allocation signal.

## Decision

### Rebalance policies are explicit triggers

`each_period` is removed from the canonical domain language. Supported policies
are:

- `buy_and_hold`: submit the first valid target once; no voluntary rebalance.
- `on_factor_signal`: rebalance whenever the configured factor frequency emits
  a new tradable signal. This is the default group-test policy.
- `scheduled`: rebalance when a named calendar schedule fires (daily, weekly,
  monthly, or a future custom schedule), independently of factor updates.
- `membership_change`: rebalance only when selected membership changes.

Roll, expiry, margin call, risk rejection, and forced liquidation are execution
or risk events. They may change positions under every policy and do not turn a
buy-and-hold strategy into a scheduled strategy.

Legacy `each_period` snapshots are migrated once to `on_factor_signal` when read.
The canonical runtime and newly persisted templates never emit `each_period`.

### Allocation is separate from margin

Allocation policies produce target weights before contract sizing:

- `inverse_volatility` is the default equal-risk policy. For selected assets,
  raw weight is `1 / max(volatility, floor)`, normalized to configured gross
  exposure. Volatility uses trailing returns only, with explicit lookback,
  minimum observations, annualization, and missing-data behavior.
- `equal_risk_contribution` uses a covariance matrix and solves for equal total
  risk contributions. It is a separate advanced policy, not an alias for
  inverse volatility.
- `equal_notional` gives every selected asset equal absolute notional weight.
- `equal_margin` gives every selected asset equal initial-margin budget and is
  retained only as an explicitly labelled comparison policy.

Margin constraints run after allocation. Except for the `equal_margin`
comparison allocator, changing margin ratios cannot change relative target
weights; a constraint may reject the rebalance or scale all weights uniformly.

### Market rules are versioned providers with explicit fallback

Commission schedules, margin ratios, liquidity/capacity data, multipliers,
tick sizes, and lot/trade units are obtained through independent provider
interfaces. A provider returns both a value and provenance:

- `effective_at`: a rule known to be effective at the simulated timestamp.
- `as_of_latest`: the latest available rule substituted for missing history.
- `configured_default`: an explicit user or application default.

Fallback is controlled by a run-level policy:

- `strict_historical`: missing `effective_at` data is an error.
- `latest_available`: use `as_of_latest` and mark every affected fill/snapshot.
- `configured_default`: use the registered default and mark it.

`latest_available` is allowed during the current data bootstrap, but results
must display an approximation warning and data-quality counts. It must never be
presented as historical truth. Adding historical tables later changes provider
resolution, not strategy, broker, or ledger contracts.

### In-sample and out-of-sample are result metadata

A run owns one ordered evaluation range and an optional split timestamp:

- in-sample: `start <= t <= split`;
- out-of-sample: `split < t <= end`.

The backend computes one continuous causal run so state crosses the split
without reset. Every timeseries point and metric carries an evaluation segment.
The frontend defaults to showing in-sample only, offers an explicit toggle for
out-of-sample, and shades the out-of-sample plot band. Metrics are reported per
segment and for the full run; they are never inferred from chart visibility.

### Framework consistency uses canonical contracts

Native, Backtrader, Qlib, and Zipline consume the same factor signals,
rebalance events, target weights, market-rule snapshots, and result schema.
Framework adapters may use native extension points, but must not silently apply
framework defaults. Comparisons assert:

- exact signal and target-weight equality;
- exact event/fill semantics where the adapter supports them;
- bounded differences explicitly caused by lot/tick rounding;
- identical provenance and evaluation-segment metadata.

Precomputed and incremental factor execution publish the same `FactorSignal`.
Supported operators require a numerical equivalence test before incremental
execution is advertised. The native event runtime executes all strategies in
one run; product-overlap batches are an input optimization and do not create
separate native backtests.

### Group and Long-Short are peer strategies

Quantile group and Long-Short definitions compile to independent strategy lanes
with their own strategy/portfolio identities. They share market and factor
actors and participate in the same run and progress stream. Long-Short is not a
post-processing subtraction of two completed group equity curves.

## Consequences

- Existing `each_period` data needs a read-time migration to
  `on_factor_signal`; no compatibility branch remains in runtime code.
- Equal-risk requires a causal volatility estimator and warm-up diagnostics.
- Latest-rule substitution enables current tests but visibly lowers result
  quality until historical market-rule data is loaded.
- Backend settings, templates, progress, and result renderers must be generated
  from the same registered contracts to prevent UI/runtime drift.
