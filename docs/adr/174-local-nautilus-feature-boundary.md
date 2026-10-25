# ADR 174: Local Nautilus feature boundary in RunSpec

Status: accepted for issue 443.

The vendored `vendor/nautilus_trader` commit `6800ea1150` adds transfer
commands, bar-volume allocation, next-bar-open orders, dynamic instrument
updates, lot/settlement basis, inventory roll and batch data APIs. RunSpec must
never accept a setting that it cannot execute.

## Current mapping

| Nautilus capability | RunSpec status |
| --- | --- |
| next-bar-open market orders | supported |
| OHLC bar-volume allocation | supported when a Venue requests it |
| per-instrument position cost basis | supported |
| lot-aware settlement basis | supported |
| daily settlement event stream | blocked unless the official event stream is wired |
| account-to-account fund transfers | blocked; no controller strategy/RunSpec field yet |
| dynamic instrument updates | adapter exists, not wired into Job chunks |
| trading-day inventory roll | native function exists, no RunSpec event stream |

`FrozenExecutionPlan.manifest()["local_nautilus_features"]` records this matrix.
Passing `fund_transfers`, `instrument_updates` or
`trading_day_inventory_roll` raises `UnsupportedExecutionConfig` rather than
silently dropping it.

## Execution boundary

`run_strategy_family_run_spec` now compiles the RunSpec execution contract and
passes it to `run_strategy_family_replay`. When a contract is present the replay
uses `engine_factory.build_backtest_engine`; the legacy hard-coded CFFEX venue
is only the fallback for tests without a contract.

Still missing before a production Job can run:

1. Stage Parquet catalogs from frozen product selections.
2. Populate `catalog_inputs` in the execution plan.
3. Add the transfer/instrument-update/inventory-roll RunSpec fields.
4. Build the Linux Nautilus wheel from the local submodule during deploy.
