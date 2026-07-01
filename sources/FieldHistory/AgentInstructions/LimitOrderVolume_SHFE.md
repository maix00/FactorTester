# LimitOrderVolume_SHFE

Use this file when cleaning Shanghai Futures Exchange official sources for
order-volume fields.

## Source

- Data source id: `SHFE`
- Official site: `https://www.shfe.com.cn`
- Announcement list: `https://www.shfe.com.cn/publicnotice/notice/`
- Example source:
  `https://www.shfe.com.cn/publicnotice/notice/202606/t20260618_832171.html`

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`
- `MaxLimitOrderVolume`
- `MaxMarketOrderVolume`

## Notice Discovery

Guosen currently has SHFE products in the unified snapshot. When a Guosen row
maps to `ExchangeID = SHFE`, search SHFE official announcements first:

1. Search the announcement list or public web index:
   - `site:shfe.com.cn/publicnotice/notice 交易指令 下单量 通知`
   - `site:shfe.com.cn/publicnotice/notice 市价指令 限价指令 每次最小下单量`
   - `site:shfe.com.cn/publicnotice/notice <品种名> 交易指令 每次最大下单量`
2. For broad exchange-wide rules, parse notices such as
   `关于市价指令上线及有关交易指令下单量的通知`.
3. For rule text, search:
   - `site:shfe.com.cn/publicnotice/notice 交易管理办法 修订案 交易指令`
   - `site:shfe.com.cn 交易管理办法 限价指令 每次最大下单数量`

## Extraction Rules

- SHFE 2026 market-order launch notices may state exchange-wide futures and
  options values in one paragraph. Split futures and options into separate
  events.
- Product-level exchange-wide futures rules should be expanded to all SHFE
  futures products only when the product universe at the effective time is
  known. Otherwise leave the event as a candidate for manual expansion.
- `限价指令每次最小下单量` -> `MinLimitOrderVolume`.
- `限价指令每次最大下单量` -> `MaxLimitOrderVolume`.
- `市价指令每次最大下单量` -> `MaxMarketOrderVolume`.
- For effective dates like `自2026年7月6日（即2026年7月3日晚连续交易时段）起`,
  use `effective_trading_day = 2026-07-06` and the night-session timestamp in
  `effective_timestamp` when the exact night open is known.
