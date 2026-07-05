# ADR 033: Native Run State, Config, Position, and Cash Pool Boundaries

## Status

Accepted

## Context

The native backtest runtime had accumulated unrelated concepts in
`engines/native/ledger.py`: ledger identity, mutable ledger state, position
lots, strategy/ledger configs, and `BacktestRunState`. This made later
changes around StrategyBook, cash pools, and ledger routing harder to reason
about because a single import path suggested one owner for several different
semantic layers.

At the same time, initial capital and base currency are cash-pool properties,
not ledger trading-rule properties. A ledger belongs to one cash pool; several
ledgers may share the same pool, and cross-currency movement must be modeled
as explicit FX movement rather than silently joining currencies in one pool.

## Decision

- Keep `engines/native/ledger.py` narrow: `Ledger`, `LedgerState`, and
  `ledger_identity`.
- Move open-position primitives into `engines/native/position.py`.
- Move `StrategyConfig`, `LedgerConfig`, and `CashPoolConfig` into
  `engines/native/config.py`.
- Move `BacktestRunState` into `engines/native/state.py`.
- Treat initial capital, base currency, and FX fee as `CashPoolConfig`.
- Keep fee, margin, accounting, settlement, tradability, rounding, and cash
  reserve policy in `LedgerConfig`.
- Let StrategyBook describe strategy-to-ledger and ledger-to-cash-pool
  topology; CashPoolModule owns cash-pool balances and cash-pool config.
- Keep the grouped-strategy business bundle together. Group membership,
  grouped target generation, and long-short group semantics are still one
  business-level package rather than many tiny modules.

## Consequences

- Runtime imports now reveal the owner boundary: state, config, position, and
  ledger identity are separate.
- Shared cash pools reject conflicting initial capital or base currency before
  cash is funded, so there is no last-writer-wins behavior.
- External-framework translation reads initial capital from the strategy/cash
  pool field, not from ledger trading-rule config.
- Future StrategyBook implementations can customize ledger/cash-pool topology
  without overloading `LedgerConfig`.
