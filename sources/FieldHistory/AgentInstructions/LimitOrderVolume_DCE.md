# LimitOrderVolume_DCE

Use this file when cleaning DCE official announcements for order-volume fields.

## Source

- Official site: `http://www.dce.com.cn`
- Announcement list: `http://www.dce.com.cn/dce/ywggytz/ywggytz.htm`
- Example source:
  `http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html`

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`: each order's minimum opening order quantity.
- `MaxLimitOrderVolume`: maximum limit order quantity.
- `MaxMarketOrderVolume`: maximum market order quantity.

## Extraction Rules

- Only create events supported by source text. Do not hard-code structured
  product/contract/value lists in code.
- For phrases like `BZ2604、BZ2605、BZ2606合约...调整为4手`, output one event:
  product `BZ`, contracts `2604/2605/2606`, value `4`.
- For a sentence containing several products and one value, group contracts by
  product. Example: `EG2604、EG2605、EG2606...调整为8手` becomes product `EG`
  with contracts `2604/2605/2606`, value `8`.
- If a DCE page cannot be fetched due anti-bot protection, use the stored raw
  HTML/text snapshot supplied in the task. Still parse from that text; do not
  write pre-parsed rules.
- Store the announcement number in `source_notice_id`.
- Store the smallest supporting sentence in `raw_note`.

## Product Mapping

Use English contract prefixes in the source text as primary product codes. If
the source only uses Chinese names, use the product catalog before source-local
aliases. Known labels:

- `BZ`: 纯苯
- `EB`: 苯乙烯
- `EG`: 乙二醇
- `L`: 线型低密度聚乙烯
- `PG`: 液化石油气
- `PP`: 聚丙烯
- `V`: 聚氯乙烯

## Effective Time

`自YYYY年M月D日交易时（即M月D-1日夜盘交易小节时）起` means:

- `effective_trading_day`: the trading day in the first date.
- `effective_timestamp`: previous calendar day's night open, currently
  `21:00:00` for DCE futures unless a source states otherwise.

