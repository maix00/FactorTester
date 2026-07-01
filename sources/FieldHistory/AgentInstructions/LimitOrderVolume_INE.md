# LimitOrderVolume_INE

Use this file when cleaning Shanghai International Energy Exchange official
sources for order-volume fields.

## Source

- Data source id: `INE`
- Official site: `https://www.ine.cn`
- Announcement list: `https://www.ine.cn/publicnotice/`
- Rules list: `https://www.ine.cn/regulation/ineregulation/rules/`
- Example rule source:
  `https://www.ine.cn/regulation/ineregulation/rules/202606/t20260622_832197.html`

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`
- `MaxLimitOrderVolume`
- `MaxMarketOrderVolume`

## Notice Discovery

Guosen currently has INE products in the unified snapshot. When a Guosen row
maps to `ExchangeID = INE`, search INE official notices and rules:

1. Search INE announcements:
   - `site:ine.cn/publicnotice 交易指令 下单量 通知`
   - `site:ine.cn/publicnotice 市价指令 限价指令 每次最大下单量`
   - `site:ine.cn/publicnotice <品种名> 交易指令`
2. Search INE rules:
   - `site:ine.cn/regulation/ineregulation/rules 交易细则 交易指令`
   - `site:ine.cn/regulation/ineregulation/rules 期权交易管理细则 交易指令`
3. INE is affiliated with SHFE but must be ingested as `data_source = INE`
   when the official source is on `ine.cn` or names 上海国际能源交易中心.

## Extraction Rules

- Split futures and options into separate events.
- Use product-level `contract_codes = []` unless the source names explicit
  contracts.
- If the INE rule is synchronized with a SHFE exchange-wide notice, store the
  INE source URL as evidence when available; do not use a SHFE URL as the only
  source for an INE row unless the source explicitly says it applies to INE.
- For night-session effective language, use the first trading day as
  `effective_trading_day` and the preceding night-session open timestamp as
  `effective_timestamp` when available.
