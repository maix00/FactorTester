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

