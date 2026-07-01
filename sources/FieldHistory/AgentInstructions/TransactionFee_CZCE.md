# TransactionFee_CZCE

Use CZCE official notices as primary historical evidence for CZCE futures and
options fee changes.

## Discovery

- Search CZCE notices for `交易手续费`, `平今仓`, `日内`, `手续费标准`, and the
  product name/code.
- Record the original notice URL, notice id, publication date, access time, and
  the shortest source sentence/table row that supports the event.

## Extraction Rules

- `开仓手续费` maps to open fee fields.
- `平仓手续费` maps to close-yesterday fee fields unless explicitly marked
  `平今仓` or `日内`.
- `平今仓手续费` and `日内平仓手续费` map to close-today fee fields.
- Ratio fees become `*RatioByMoney`; `元/手` fees become `*RatioByVolume`.
- If the source says a specific contract such as `CF609`, create one event with
  `contract_codes = ["609"]`; do not store multiple contracts in one row.
- If the source applies to the full product, leave `contract_codes` empty.

