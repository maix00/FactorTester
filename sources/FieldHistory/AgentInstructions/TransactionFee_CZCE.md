# TransactionFee_CZCE

Use CZCE official notices as primary historical evidence for CZCE futures and
options fee changes.

## Discovery

- Search CZCE notices for `交易手续费`, `平今仓`, `日内`, `手续费标准`, and the
  product name/code.
- Record the original notice URL, notice id, publication date, access time, and
  the shortest source sentence/table row that supports the event.

## Baseline Discovery

- A product-level exchange baseline may come from the current fee table,
  listing notice, contract specification, product technical manual, or
  official settlement-parameter table. Use the most authoritative exchange
  source available and note the source type in `parser_notes`. Later notices
  should be stored as dated change events rather than overwriting the baseline.

## Extraction Rules

- `开仓手续费` maps to open fee fields.
- `平仓手续费` maps to close-yesterday fee fields unless explicitly marked
  `平今仓` or `日内`.
- `平今仓手续费` and `日内平仓手续费` map to close-today fee fields.
- Ratio fees become `*RatioByMoney`; `元/手` fees become `*RatioByVolume`.
- If the source says a specific contract such as `CF609`, create one event with
  `contract_codes = ["609"]`; do not store multiple contracts in one row.
- If the source applies to the full product, leave `contract_codes` empty.

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
