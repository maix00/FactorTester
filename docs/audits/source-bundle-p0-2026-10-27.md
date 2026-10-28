# Source Bundle P0 audit — 2026-10-27

Baseline: `945ddc5b73e1c4bee55592b4520510cf9536c60f`
Worktree: `/Users/maxdeux/Documents/GTHT/Codes/.workspace/issues/443-nautilus-bridge`
Branch: `fix/issue-443-nautilus-bridge`

This is an audit record, not an acceptance record. No data was migrated, no service was
stopped, and no remote operation was performed.

## Current Bundle surface

`installed_bundles()` currently discovers `sources/Local/bundle.json` with five members:

| Member | Kind | Frequency | Nautilus catalog integration |
|---|---|---|---|
| `LocalCNFuturesMIN1` | market_data | MIN1 | none |
| `LocalCNFuturesDAY1` | market_data | DAY1 | none |
| `LocalCNFuturesContractMIN1` | market_data | MIN1 | `sources.LocalCNFutures.nautilus_catalog:stage_catalogs` |
| `LocalCNFuturesContractDAY1` | market_data | DAY1 | `sources.LocalCNFutures.nautilus_catalog:stage_catalogs` |
| `FieldHistory:market_rules:exchange` | historical_rules | n/a | none |

`product_bindings` is empty. The current `Local` entrypoints are:

```text
sources.Local.data_source_bundle
sources.LocalCNFutures.CNFutures
sources.LocalCNFutures.artifacts
```

Only `LocalCNFuturesContractMIN1` has a verified adapter contract for its declared
MIN1/parquet layout. `LocalCNFuturesContractDAY1` declares a different adapter
(`local_cnfutures_contract_daily_term_structure_v1`) but is routed through the same
catalog loader entrypoint.

## Entry and consumer chain

```text
catalog_staging.stage_run_spec_catalogs
  -> installed_bundles(): unique server member by id + exact frequency
  -> member.integrations["nautilus_catalog"]
  -> sources.LocalCNFutures.nautilus_catalog.stage_catalogs
  -> stage_contract_minute_catalog(...)
  -> dict[product_key] = {catalog_dir, contract_uid}
```

The strategy consumer currently converts that dict to:

```python
inputs = {
    product: ReplayInput(Path(value["catalog_dir"]), value["contract_uid"])
    for product, value in catalogs.items()
}
```

Therefore the current consumer contract is exactly one staged catalog per product.
Changing the source return to multiple contracts per product requires coordination with
the strategy/execution consumer and is not part of this P0 audit.

## Correctness risks

### 1. Multiple contracts collapse to one catalog per product

`sources/LocalCNFutures/nautilus_catalog.py` stages every requested contract, but then uses:

```python
catalogs.setdefault(product_key, {...})
```

For two lifecycle contracts of the same product, only the first survives in the returned
mapping. The calendar builder also iterates only returned values, so the dropped contract
does not contribute sessions. This means the current path cannot be used to claim full
roll/multi-contract replay.

Required before P1: agree on an explicit multi-catalog reference shape with the execution
consumer, then test two contracts of one product, overlapping windows, and a roll.

### 2. Historical margin mapping is lossy

`build_contract_spec` currently computes:

```python
margin = max(long_margin_ratio, short_margin_ratio)
margin_init = margin
margin_maint = margin
```

and uses `or 0` for missing long/short values. This is not an ADR-184 lossless mapping:

- long and short margin are distinct semantics;
- initial and maintenance margin are distinct;
- a missing rule is not zero;
- the selected value has no effective-time identity.

`FuturesContractSpec` only carries `margin_init`/`margin_maint`, and the current adapter
does not represent side-specific or time-varying rules. A fix needs either an explicit
execution-side rule path or a fail-closed unsupported report. Do not keep the `max` value
and call it complete.

### 3. DAY1 is routed through the minute loader

Both `LocalCNFuturesContractMIN1` and `LocalCNFuturesContractDAY1` resolve to
`stage_catalogs`. That loader always calls:

```python
stage_contract_minute_catalog(
    contract_data_path_for(...),
    ...
)
```

`stage_contract_minute_catalog` reads with `iter_minute_bars` and creates a
`1-MINUTE-LAST-EXTERNAL` BarType. The DAY1 adapter declares:

```text
layout: term_structure_snapshot
bar_time_semantics: trading_day_label
raw_timestamp_unit: date_label
required column: SETTLEMENT_PRICE
```

Those fields are not exercised by the current minute loader. DAY1 must get its own source
reader/clock/settlement validation; matching a member name is not evidence.

### 4. Central code still owns source-specific choices

The source loader still imports and calls:

```text
server.modules.shared.price_services
server.services.nautilus_bridge.catalog
server.services.nautilus_bridge.source_registry
```

It resolves product lifecycle through `find_contract_product`, source paths through
`contract_data_path_for`, and staging through central `stage_contract_minute_catalog`.
These are explicit remaining central dependencies, not a fully external Bundle.

### 5. Authorization is not a manifest claim

`provisioner` / `execution_location` describe placement. They do not grant permission to
read, share, execute, or upload data. The server installation root is the trust boundary;
client manifests must never be imported as Manager plugins.

### 6. Manifest version is not data revision

The current update policy is `mutable_history`, `unversioned`, `replay_policy=not_declared`.
A Bundle manifest version does not freeze market bytes, and the installed metadata cache
does not own market data.

### 7. Product bindings and catalog projections are not migrated

`product_bindings` is empty. Existing product/category records are not migrated to
`source_product_ref`. Old catalog APIs still activate source code and check availability;
`product_source_descriptors()` and the federated capability snapshot are not yet pure
JSON/metadata reads.

## Field mapping baseline

### MIN1 market member

| Source field | Neutral meaning | Nautilus target | Unit/precision | Time semantics |
|---|---|---|---|---|
| `trade_time` / `trade_timestamp` | Bar event time | `Bar.ts_event` / `ts_init` | milliseconds → ns | interval end, validated from exchange wall time |
| `trading_day` | Trading-day label | calendar/session key | date label | source-owned, night session belongs to next trading day |
| `open_price` | Open | `Bar.open` | price, min_tick precision | interval open |
| `highest_price` | High | `Bar.high` | price | interval high |
| `lowest_price` | Low | `Bar.low` | price | interval low |
| `close_price` | Close | `Bar.close` | price | interval close |
| `volume` | Volume | `Bar.volume` | contracts | interval volume |
| `open_interest` | Open interest | `Bar.open_interest` | contracts | interval observation |
| `min_tick` | Price increment | `price_increment` / `price_precision` | decimal | static definition |
| `point_value` | Contract multiplier | `multiplier` | decimal | static definition |
| contract UID | Instrument identity | `instrument_id` / venue / underlying | source-owned | activation/expiration |
| long/short margin | Side-specific historical rule | not losslessly represented | ratio | effective-time rule; currently lossy |
| settlement | Official settlement | separate settlement event/rule | price | trading-day close; not currently consumed by minute path |

### DAY1 member

| Source field | Neutral meaning | Required target | Status |
|---|---|---|---|
| `TRADING_DAY` | Trading-day label | Bar time/calendar | declared, not exercised by current minute loader |
| `OPEN/HIGH/LOW/CLOSE` | Daily OHLC | `Bar` fields | declared |
| `VOLUME` | Volume | `Bar.volume` | declared |
| `OPEN_INTEREST` | Open interest | `Bar.open_interest` | declared |
| `SETTLEMENT_PRICE` | Official settlement | settlement model/event | declared, no verified loader |

### Historical rules member

Current declaration is separate from market members, but execution still resolves
`FieldHistory:market_rules:exchange` through old provider code. Rule identity must include
effective time, known-at time, trading-day attribution, side (long/short), and initial vs
maintenance semantics.

## P1 preconditions

1. Execution consumer accepts an explicit multi-catalog reference before changing
   `stage_catalogs` return type.
2. Margin/rules path has a lossless destination or a fail-closed unsupported result.
3. DAY1 has its own source-owned reader and a real small-window test.
4. Central loader no longer imports source-specific product/path/rule classes.
5. Any new public request/description protocol is immutable and bounded; no data files are
   read during catalog discovery.

## Focused verification baseline

At `945ddc5b7`, this audit reran the focused P0 command from the handoff:

```text
tests/server/test_source_bundle_manifests.py
tests/server/test_nautilus_source_declarations.py
tests/server/test_nautilus_source_registry.py
tests/server/test_nautilus_catalog_staging.py
tests/server/test_nautilus_bridge_run_spec.py
tests/server/test_nautilus_strategy_runspec.py
```

Result: `71 passed in 1.10s` with GTHT Python. This is focused contract verification; it
did not run the full suite, public-network load, real DAY1/margin execution, data
migration, or deployment.
