# TransactionFee_GFEX

Use GFEX official notices as primary historical evidence for GFEX fee changes.

## Discovery

- Search GFEX notices for `交易手续费`, `平今仓`, `日内`, `手续费标准`, and product
  name/code.
- GFEX has newer products; if a product is absent in older catalogs, do not
  synthesize historical rows before listing.

## Baseline Discovery

- A product-level exchange baseline may come from the current fee table,
  listing notice, contract specification, product technical manual, or
  official settlement-parameter table. Use the most authoritative exchange
  source available and note the source type in `parser_notes`. Later notices
  should be stored as dated change events rather than overwriting the baseline.

## Extraction Rules

- `开仓` -> open fee fields.
- normal `平仓` -> close-yesterday fee fields.
- `平今仓`/`日内` -> close-today fee fields.
- percentage/万分比 by amount -> `*RatioByMoney`.
- `元/手` -> `*RatioByVolume`.
- Contract-specific scope must be split into one event per contract code.

## Source Authority

- Prefer official exchange pages/notices for exchange TransactionFee events. If
  the original site is blocked, removed, or hidden behind WAF, an exact mirror
  may be used only when it preserves the exchange notice id, publication date,
  exchange author, and the source sentence/table without broker markups.
- Ordinary broker fee pages, Sina-style snapshots, and fee aggregators are audit
  evidence only; do not use them as the source row for an exchange rule.
- If a secondary source disagrees with the exchange view, record it in
  `field_history_transaction_fee_external_audit` and then find the official
  notice before appending field-change events.
- Contract-specific fee rules must be stored as one event per contract code;
  product-level baselines leave `contract_codes` empty.
