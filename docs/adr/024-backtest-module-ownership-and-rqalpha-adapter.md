# ADR 024: Backtest Module Ownership and RQAlpha Adapter Boundary

## Status

Accepted.

## Context

The grouped backtest route has grown into a composition point for unrelated
concerns: HTTP/SSE transport, template payload parsing, setting defaults,
membership preparation, factor execution, market-rule fallback, order execution,
ledger serialization, and snapshot overlays. That makes semantics such as
rebalance trigger, target allocation, fee-aware executable target, lot rounding,
and product selection easy to confuse.

RQAlpha is a useful reference point because it is explicitly modular. Its public
repository describes RQAlpha as an extendable and replaceable backtest/trading
framework, and its documented mods split accounts, analyser, progress, risk,
simulation, scheduler, and transaction-cost responsibilities. Its order API also
separates high-level target orders from lower-level submitted orders. The wider
systematic-trading ecosystem likewise treats order type, slippage, commission,
liquidity, margin, and portfolio construction as execution-model choices rather
than route-layer details.

References:

- https://github.com/ricequant/rqalpha
- https://www.ricequant.com/doc/rqalpha-plus/api/order-api
- https://rqalpha.readthedocs.io/zh-cn/latest/history.html
- https://github.com/paperswithbacktest/awesome-systematic-trading

## Decision

`server/modules/*` remains the HTTP boundary. It should not be moved wholesale
under `tools/`. Instead, each business module in `tools/*` owns its domain
objects, settings, validation, CLI entrypoints, and framework adapters. Server
routes become thin adapters that authenticate, parse request transport, call
domain services, and serialize responses.

Backtest ownership is split as follows:

- Product selection: a backend `SubmissionSpec`-style object owns selected paths,
  product masks, product/contract conversion, and metadata. A frontend
  "submission" is only a UI path selection until the backend materializes it.
- Factor research: `FactorTester` owns factor definitions, factor evaluation, and
  factor-signal tables for a product selection. It should not own execution,
  order routing, or accounting.
- Test business objects: IC tests and grouped tests are `FactorTester`-backed
  research jobs. `FactorGroupTester` owns grouped-membership strategy
  construction; it is not a general backtest engine.
- Backtest runner: a `BacktestRunner`/framework adapter owns target calculation,
  order generation, matching, fees, liquidity, margin, ledger, and event replay.
- Snapshot trace: each execution module owns trace fragments for its own
  decisions. A later trace composer can build a detailed overlay on demand.

Factor execution follows ADR 022:

- `FactorExpr` is the single authoring interface.
- Batch/vector and incremental/event engines compile the same `FactorExpr`.
- External frameworks should start from a framework adapter of `FactorExpr` or a
  declared `FactorSource`, not from framework-specific handwritten factor logic.
- In the special grouped-test domain, membership may be the strategy signal sent
  into all engines, but that membership must be generated from the same
  `FactorExpr` result and checked for equivalence.

`split_count_by_membership_key` means the grouped strategy bucket count for a
specific `(tester_id, factor_alias)` membership source. It is not factor
precomputation. It exists so several selected groups can reuse one membership
tensor produced from the same factor signal.

Money precision is a registered execution setting. Native accounting can keep
minor-unit integer ledgers, while adapters such as Qlib may expose an engine
native major-unit ledger. When a framework cannot honor a setting value, the
adapter must declare that capability and either reject the value or map it to an
explicit framework-managed default. It must not silently ignore user settings.

## Consequences

- Large files such as `server/modules/single_factor_test/group.py` should be
  split by ownership, not by arbitrary length. The first extraction targets are
  payload/settings resolution, snapshot serialization, product display metadata,
  and group-run orchestration.
- New execution settings should be registered in `tools/backtest/settings`, then
  consumed by Native and adapter runners. Frontend chips and tabs use the backend
  manifest only.
- RQAlpha should be added as a fifth framework from the data and adapter layer:
  data bundle/feed, FactorExpr adapter or explicit FactorSource, strategy runner,
  order/matching/fee/margin mapping, and equivalence tests against Native.
- CLI entrypoints belong beside the domain modules, for example a backtest CLI
  that can materialize a product selection, compile a FactorExpr, run group/IC
  diagnostics, and print type-safe trace summaries for agent workflows.
- Repository-wide type checking is an acceptance gate. Type errors should be
  fixed at the ownership boundary; `type: ignore` is reserved for narrow,
  documented third-party interop cases.
