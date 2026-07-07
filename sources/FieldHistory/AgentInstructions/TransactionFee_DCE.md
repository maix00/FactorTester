# TransactionFee_DCE

Use DCE official notices as primary historical evidence for DCE futures and
options fee changes.

## Discovery

- Search DCE business notices for product name/code plus terms such as
  `交易手续费`, `日内交易手续费`, `平今仓交易手续费`, `手续费标准`, `调整`.
- Prefer the notice detail page and record its notice id, URL, source date, and
  access time.
- When Guosen shows a changed DCE fee baseline but no historical event is in
  FieldHistory, search DCE notices around the Guosen effective date and product.

## Baseline Discovery

- A product-level exchange baseline may come from the current fee table,
  listing notice, contract specification, product technical manual, or
  official settlement-parameter table. Use the most authoritative exchange
  source available and note the source type in `parser_notes`. Later notices
  should be stored as dated change events rather than overwriting the baseline.

## Extraction Rules

- `开仓手续费` maps to open fee fields.
- `平仓手续费` maps to close-yesterday fee fields unless the text explicitly says
  `平今仓` or `日内`.
- `平今仓手续费`, `日内平仓手续费`, or `日内交易手续费` maps to close-today fee fields.
- `成交金额的万分之 X` maps to `RatioByMoney = X / 10000`.
- `成交金额的百分之 X` maps to `RatioByMoney = X / 100`.
- `X 元/手` maps to `RatioByVolume = X`.
- Product-level notices leave `contract_codes` empty.
- Contract-specific notices create one event per contract code.
- Night session belongs to the next trading day.

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
