# Contract lifecycle ingestion

This store records contract-level lifecycle fields for replay and CLI audit.
It does not use announcement text as lifecycle evidence.

## Exchange official / portal ingests

- SHFE / INE / CZCE / CFFEX: prefer direct exchange contract-info endpoints;
  AKShare wrappers are only compatible fallbacks.
- GFEX: currently uses the published contract-info feed available through the
  existing compatible fetcher.
- DCE: access starts from the official portal `数据中心 -> 业务参数 -> 合约信息`
  and executes `POST /dcereport/publicweb/tradepara/contractInfo` inside a real
  browser context. Naked `requests` or the old AKShare DCE endpoint are not the
  canonical path.

DCE portal findings:

- `contractInfo` returns current/future complete lifecycle fields:
  `contractId`, `startTradeDate`, `endTradeDate`, `endDeliveryDate`.
- Adding `tradeDate` or `date` to `contractInfo` is ignored by the backend.
- `newContractInfo` supports date queries and returns new listings with
  `startTradeDate`, base price and price-limit fields, but it does not return
  `endTradeDate` or `endDeliveryDate`.

## Historical 2024+ local daily coverage baseline

Run:

```bash
PYTHONPATH=. python sources/AKShare/scripts/backfill_contract_lifecycle_from_local_dayk.py \
  --start-date 2024-01-01
```

This reads `sources.LocalCNFutures.SOURCE_DATA_DIR/data_dayk.parquet`.

- `last_trading_date`: last local daily bar with finite close only when the
  contract is not right-censored by the local data cutoff.
- `list_date`: first local daily bar with finite close.
- `source_function`: `local_cnfutures_dayk_coverage`.
- `raw_json.field_sources`: records per-field provenance.

The script does not treat "latest available local bar" as a last trading day.
If a contract's last local bar is the exchange's current local data cutoff, or
the contract month is after that cutoff month, `last_trading_date` is left empty
and `raw_json.right_censored` is set to `true`.

This baseline covers all exchanges present in LocalCNFutures daily data. It is
insert-once by default, so official/portal lifecycle rows should be ingested
first when exact list/delivery dates are available. Use `--overwrite` only when
the intended result is to replace existing lifecycle rows with local coverage.

## Field-source policy

The lifecycle table keeps source provenance in `source_function`; the audit
script prints the field policy for every source present in the table.

- Official contract-info sources populate exact exchange-published fields:
  - SHFE/INE: `OPENDATE`, `EXPIREDATE`, `STARTDELIVDATE`, `ENDDELIVDATE`,
    `BASISPRICE`.
  - CZCE: `firstTradingDay`, `lastTradingDay`, `deliveryNoticeDay`,
    `lastDeliveryDay`.
  - CFFEX: `opendate`, `expiredate`, `basisprice`.
  - DCE portal: `startTradeDate`, `endTradeDate`, `endDeliveryDate`.
- AKShare-compatible `futures_contract_info_*` rows preserve the same exchange
  contract-info semantics when those rows already exist in the local store.
- Tushare `fut_basic` can provide external contract metadata including
  `last_ddate` for DCE/GFEX, but it requires a Tushare token and is not treated
  as exchange-official per-contract data. In this environment no token is
  configured, so the Tushare backfill path reports `skipped` and leaves the
  missing fields visible to audit.
- `local_cnfutures_dayk_coverage` is the 2024+ historical coverage fallback:
  - `list_date` = first finite-close local daily bar.
  - `last_trading_date` = last finite-close local daily bar only if not
    right-censored.
  - delivery fields are intentionally left empty unless an official/portal
    lifecycle row supplies them.

LocalCNFutures daily-bar upstreams are:

- DCE: Sina daily bars through AKShare `futures_zh_daily_sina` fallback.
- CFFEX: CFFEX official monthly daily-data zip.
- SHFE / INE / CZCE / GFEX: AKShare daily futures data fetch; GFEX is retried
  because transient empty responses have been observed.

Sina is a daily/minute market-data source here; no public Sina lifecycle
endpoint was found for exact `last_delivery_date`. Therefore Sina is only
acceptable as coverage/cross-check input, not as a lifecycle delivery-date
source.

Exchange product rules such as "last delivery day is the third trading day
after last trading day" are used only with explicit product rule/listing source
provenance and the LocalCNFutures exchange trading calendar. These rows use the
distinct `source_function` value `exchange_rule_dayk_calendar_derived` and are
visibly separate from official per-contract table rows. Each row's `raw_json`
stores the product rule source notice id/url, the formula, the original
`last_trading_date`, the derived `last_delivery_date`, and the calendar path.
Backtest `engine_mode=exact` rejects this derived source; exact mode requires
official/external exact lifecycle rows.

## Completeness audit

Run:

```bash
PYTHONPATH=. python sources/AKShare/scripts/audit_contract_lifecycle_coverage.py \
  --start-date 2024-01-01 --strict
```

The audit checks coverage against 2024+ LocalCNFutures daily contracts,
required fields, right-censored local coverage rows, source distribution, field
completeness, and field-source policy. It does not require strict multi-source
cross-validation.

Optional precise-field backfills:

```bash
PYTHONPATH=. python sources/AKShare/scripts/backfill_missing_lifecycle_fields.py \
  --source cffex-official
PYTHONPATH=. python sources/AKShare/scripts/backfill_missing_lifecycle_fields.py \
  --source tushare --exchange DCE --exchange GFEX
PYTHONPATH=. python sources/AKShare/scripts/backfill_missing_lifecycle_fields.py \
  --derive-rule-calendar --exchange DCE --exchange GFEX
```

The CFFEX path uses official trading-parameter XML and can fill missing
`listing_base_price`. The Tushare path fills DCE/GFEX `last_delivery_date` only
when a token is configured; without a token it reports `skipped` and writes
nothing. The rule-calendar path fills DCE/GFEX `last_delivery_date` as a
derived field when exact official/portal history is unavailable; it refuses to
write rows without a product rule/listing source or without three later local
exchange trading days.
