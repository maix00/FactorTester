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
