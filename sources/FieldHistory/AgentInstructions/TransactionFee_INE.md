# TransactionFee_INE

Use INE official notices as primary historical evidence for INE fee changes.

## Discovery

- Search INE notices for `交易手续费`, `平今仓`, `日内`, `手续费标准`, and the
  product name/code.
- Record the INE notice id and original INE URL when available, not only a
  mirrored broker or SHFE page.

## Extraction Rules

Apply the same field mapping as `TransactionFee_SHFE.md`:

- open fees -> open fields.
- normal close fees -> close-yesterday fields.
- `平今仓`/`日内` fees -> close-today fields.
- money-ratio text -> `*RatioByMoney`.
- `元/手` text -> `*RatioByVolume`.
- split every contract-specific notice into one event per contract code.

