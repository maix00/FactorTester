# Source migration parity matrix — 2026-10-27

Baseline: current `fix/issue-443-nautilus-bridge` worktree, after native DMTM replay and
O(1) rule revision changes. This is a migration status table, not an acceptance record.

| Old capability | New implementation | Consumer switched | Regression evidence | Old path removed |
|---|---|---|---|---|
| LN LocalCNFutures MIN1 catalog staging | source-owned `nautilus_catalog.stage_catalogs` + `stage_contract_minute_catalog` | strategy replay uses staged catalog | synthetic dispatch + real T2403 3-bar readback | no |
| LN DAY1 catalog staging | source-owned daily loader + `InstrumentClose(DAILY_SETTLEMENT)` | Rust replay consumes bars + closes | synthetic 2/6-day runs | no |
| Daily settlement/DMTM | `to_nautilus_daily_settlement` -> native InstrumentClose | Nautilus `settle_daily_futures` | PnL 400/1000/1000, realized 3000, margin 2062->2066.80 | no (same existing adapter reused) |
| Historical rule lookup | source-owned provider protocol + SQLite savepoint snapshot | not wired into Instrument spec production path | cache revision/single-flight tests | no |
| Initial/maintenance margin | parser requires separate fields | blocked: current rule store lacks both | missing-field tests only | no |
| Night session/day boundaries | static product schedule + previous TRADING_DAY | staged DAY1 receipts | synthetic only | no |
| Source catalog metadata | metadata-only installed Bundle endpoint | not switched; old `/data-sources` still used by Web+CLI | metadata route tests | no |
| Product/source bindings | empty `product_bindings`; no migration | no | none | n/a |
| RunSpec input identity | `FrozenBundleInput` skeleton | not in RunSpec/storage/report | round-trip tests | no |
| Multi-contract catalogs | explicit `CatalogSet` types; staging remains fail-closed | no | duplicate/preflight tests | no |
| FactorActor/report multi-contract | unchanged `product -> ReplayInput` | no | existing tests only | no |

## Missing evidence

- Real rule database load read counts, elapsed time, peak RSS.
- Real initial/maintenance rule rows and effective-time behavior.
- Versioned historical session/calendar data and holiday/night ownership.
- Position-bearing real DMTM under exchange rules.
- Old/new source catalog ref-set equality for the same principal and permissions.
- Multi-contract roll/overlap run through FactorActor and report.
- Old implementation removal and read-count deltas on the same real input.

## Rules

- Do not mark a row complete because a new type or route exists.
- A row is complete only when the actual consumer uses it, regression agrees,
  the replaced old path is removed, and read/time/RSS evidence is recorded.
- Do not substitute fail-closed for a previously working capability.
