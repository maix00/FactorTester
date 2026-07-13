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
