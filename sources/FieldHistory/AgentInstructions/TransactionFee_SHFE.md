# TransactionFee_SHFE

Use SHFE official notices as primary historical evidence for SHFE fee changes.

## Discovery

- Search SHFE notices for `交易手续费`, `平今仓`, `日内`, `手续费标准`, and the
  product name/code.
- Include INE separately for INE products even when the notice is linked from a
  shared SHFE page.

## Extraction Rules

- `开仓` -> open fee fields.
- `平仓` -> close-yesterday fee fields unless the text explicitly says `平今仓`.
- `平今仓` or `日内平今仓` -> close-today fee fields.
- `成交金额的万分之 X` -> money ratio `X / 10000`.
- `X 元/手` -> volume ratio `X`.
- Contract-specific scope must be one event per contract code.
- Product-level scope leaves `contract_codes` empty.

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
