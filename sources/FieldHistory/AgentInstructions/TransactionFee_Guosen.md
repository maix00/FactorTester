# TransactionFee_Guosen

Guosen pages provide a current brokerage-facing snapshot of fee settings. Treat
them as baseline evidence and cross-check material, not as the primary source for
dated historical fee changes.

## Fields

- `OpenRatioByMoney`, `CloseRatioByMoney`, `CloseTodayRatioByMoney`
- `OpenRatioByVolume`, `CloseRatioByVolume`, `CloseTodayRatioByVolume`
- `VolumeMultiple` only when the source explicitly provides the contract
  multiplier; otherwise let OpenCTP supply it.

## Extraction

- Locate the table columns containing open, close, and close-today fees.
- Percent/万分比 values become `*RatioByMoney` as decimals.
- `元/手` values become `*RatioByVolume`.
- Empty start date means the baseline is open-ended backward:
  `effective_trading_day = 1900-01-01`, empty `effective_timestamp`.
- Empty end date means open-ended forward.
- If a row is contract-specific, create one row per contract code.
- If a row is product-level, leave `contract_codes` empty.

## Duplicate Check

Before writing a Guosen baseline, check the semantic key in
`sources/FieldHistory/AGENT.md`. Do not write a duplicate baseline for an
existing product/type/field/value. If Guosen disagrees with an official exchange
notice, record the conflict in `parser_notes` and do not silently override the
official event.

