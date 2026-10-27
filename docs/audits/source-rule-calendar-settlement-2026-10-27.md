# Source rule / calendar / settlement inventory — 2026-10-27

Baseline: `2095208b8e3f941a9a55d9baf438dc87e29e3d2d`
Read-only inventory. No provider, rule database, or market data was modified.

## Existing fields

### Trading specification (`cn_futures_trading_spec_fields`)

```text
trading_spec_source / trading_spec_date
open_fee_ratio / open_fee_fixed
close_fee_ratio / close_fee_fixed
close_today_fee_ratio / close_today_fee_fixed
long_margin_ratio / long_margin_fixed
short_margin_ratio / short_margin_fixed
min_tick / point_value
min_trade_quantity / max_trade_quantity
```

There is no initial-vs-maintenance margin field, and no explicit side-specific
initial/maintenance pair. `nautilus_catalog.build_contract_spec` now requires:

```text
long_margin_ratio == short_margin_ratio
initial_margin_ratio
maintenance_margin_ratio
```

The first exists in the current source; the last two do not. Real Local staging therefore
fails closed until a rule source supplies them.

### Historical rule values

`tools.data.field_history.MARKET_RULE_FIELDS` contains:

```text
VolumeMultiple, PriceTick, MinLimitOrderVolume, MaxLimitOrderVolume
OpenRatioByMoney / OpenRatioByVolume
CloseRatioByMoney / CloseRatioByVolume
CloseTodayRatioByMoney / CloseTodayRatioByVolume
LongMarginRatioByMoney / LongMarginRatioByVolume
ShortMarginRatioByMoney / ShortMarginRatioByVolume
```

It has no initial/maintenance margin fields and no explicit effective-time calendar rule
schema. `trading_fields.EffectiveRule` supports `trading_sessions` and `daily_settlement`,
but no production constructor of those rules was found in this checkout; the existing
callers/tests build them explicitly. This inventory does not claim they are populated.

### Sessions

`CNFutures` exposes current product fields:

```text
trading_day_sessions
night_session
trading_day_close_time
```

`trading_sessions.infer_trading_sessions` derives observed day/night intervals from MIN1
bar endpoints. `TradingSessionSummary` in a catalog receipt records observed starts/ends
per trading day.

What is missing:

- a versioned historical session schedule with effective dates;
- exceptional holiday/early-close sessions;
- separate interval start, end, and publication time per trading day;
- a source-provided calendar revision.

The current DAY1 reader uses the previous unique `TRADING_DAY` plus the current static
night/day fields; it does not satisfy a historical calendar requirement.

### Settlement

`term_structure-listed_contracts.parquet` contains:

```text
TRADING_DAY, CONTRACT_UID, CONTRACT
OPEN, HIGH, LOW, CLOSE, VWAP
SETTLEMENT_PRICE, PRE_SETTLEMENT_PRICE
VOLUME, OPEN_INTEREST
```

DAY1 `MarketBar.settlement_price` is now copied into
`CatalogReceipt.settlement_records`. It is not emitted as a Nautilus custom event and no
DMTM replay consumer was found.

`FrozenTradingFields.daily_settlement` and
`NautilusExecutionPlan.requires_daily_settlement_adapter()` exist, but the actual
settlement event stream / account DMTM path is not wired in this checkout.

## Missing items by owner

| Item | Needed | Current owner/blocker |
|---|---|---|
| initial margin | side-specific initial ratio/fixed rule | source/rule data; no field |
| maintenance margin | side-specific maintenance ratio/fixed rule | source/rule data; no field |
| historical sessions | versioned intervals, holidays, publication | calendar/rule source; not present |
| session revision | source-provided revision + snapshot | calendar source; not present |
| settlement event | typed event + effective close time | execution/Nautilus adapter; not wired |
| DMTM consumption | account settlement test with official price | execution side; not wired |

## Reuse before adding

- Reuse `historical_field_values` for future margin/fee rules; add columns/events instead of
  a second history table.
- Reuse `EffectiveRule`/`TradingSessionSummary` rather than another calendar format.
- Reuse the source-owned `NautilusAdapterContract` and catalog loader for any new source.
- Do not infer a historical calendar from current product labels or natural dates.
- Do not copy long margin into maintenance margin.

## Scope

No data migration, no server stop, no public network test, no deployment.
