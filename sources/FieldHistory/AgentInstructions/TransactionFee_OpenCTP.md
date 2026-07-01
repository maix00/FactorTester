# TransactionFee_OpenCTP

OpenCTP is the latest listed-contract baseline for transaction-fee and contract
spec fields. It is not a source of dated historical exchange-change events.

## Fields

- `OpenRatioByMoney`
- `OpenRatioByVolume`
- `CloseRatioByMoney`
- `CloseRatioByVolume`
- `CloseTodayRatioByMoney`
- `CloseTodayRatioByVolume`
- `VolumeMultiple`

## Write Rule

Do not append OpenCTP latest rows into `agent_field_change_events` or
`historical_field_values`. `sources.FieldHistory.views.TransactionFee` folds the
latest OpenCTP snapshot into the unified provider at read time.

Use exchange official notices for historical fee-change events. Use Guosen only
as a secondary current baseline or cross-check when official history is missing.

