# TransactionFee_CFFEX

Use CFFEX official notices as primary historical evidence for index futures,
bond futures, and option fee changes.

## Discovery

- Search CFFEX notices for `交易手续费`, `平今仓`, `日内`, `手续费标准`, product
  name/code, and contract code.
- CFFEX notices often distinguish futures and options; preserve
  `instrument_type`.

## Extraction Rules

- `开仓手续费` -> open fee fields.
- `平仓手续费` -> close-yesterday fee fields unless explicitly `平今仓`.
- `平今仓手续费`/`日内平仓手续费` -> close-today fee fields.
- ratio by notional/amount -> `*RatioByMoney`.
- `元/手` -> `*RatioByVolume`.
- Store one event per contract code when scope is contract-specific.

## Source Authority

- Store exchange TransactionFee events only from official exchange pages/notices
  or exact mirrored exchange notices with the original notice id.
- Secondary pages, broker pages, and fee aggregators are audit evidence only; do
  not use them as the source row for an exchange rule.
- If a secondary source disagrees with the exchange view, record it in
  `field_history_transaction_fee_external_audit` and then find the official
  notice before appending field-change events.
- Contract-specific fee rules must be stored as one event per contract code;
  product-level baselines leave `contract_codes` empty.
