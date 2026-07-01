# TransactionFee_GFEX

Use GFEX official notices as primary historical evidence for GFEX fee changes.

## Discovery

- Search GFEX notices for `交易手续费`, `平今仓`, `日内`, `手续费标准`, and product
  name/code.
- GFEX has newer products; if a product is absent in older catalogs, do not
  synthesize historical rows before listing.

## Extraction Rules

- `开仓` -> open fee fields.
- normal `平仓` -> close-yesterday fee fields.
- `平今仓`/`日内` -> close-today fee fields.
- percentage/万分比 by amount -> `*RatioByMoney`.
- `元/手` -> `*RatioByVolume`.
- Contract-specific scope must be split into one event per contract code.
