# LimitOrderVolume_DCE

Use this file when cleaning DCE official announcements for order-volume fields.

## Source

- Official site: `http://www.dce.com.cn`
- Announcement list: `http://www.dce.com.cn/dce/ywggytz/ywggytz.htm`
- Example source:
  `http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html`
- Rules fallback: product business rules under `http://www.dce.com.cn`.
  Search `site:dce.com.cn/dce/content.thtml <品种名> 期货业务细则 交易指令 每次最大下单数量`.

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`: each order's minimum opening order quantity.
- `MaxLimitOrderVolume`: maximum limit order quantity.
- `MaxMarketOrderVolume`: maximum market order quantity.

## Extraction Rules

- Guosen currently has DCE products in the unified snapshot. When a Guosen row
  maps to `ExchangeID = DCE`, search DCE official notices first, then DCE
  product business rules.
- Only create events supported by source text. Do not hard-code structured
  product/contract/value lists in code.
- For phrases like `BZ2604、BZ2605、BZ2606合约...调整为4手`, output three
  events: product `BZ` with contract `2604`, product `BZ` with contract
  `2605`, and product `BZ` with contract `2606`; each event has value `4`.
- For a sentence containing several products and one value, split every
  product/contract pair into its own event. Example:
  `EG2604、EG2605、EG2606...调整为8手` becomes three product `EG` events with
  singleton contract scopes `2604`, `2605`, and `2606`, each with value `8`.
- Agent-ingested `contract_codes` must be empty for product-level rules or a
  singleton list for one contract-specific rule. Never store multiple contract
  codes in one event, because not every product has a term structure and the
  consumer may query a direct contract.
- If a DCE page cannot be fetched due anti-bot protection, use the stored raw
  HTML/text snapshot supplied in the task. Still parse from that text; do not
  write pre-parsed rules.
- Store the announcement number in `source_notice_id`.
- Store the smallest supporting sentence in `raw_note`.

## Notice Discovery

1. Search DCE business notices (`业务公告与通知`) with phrases:
   - `交易指令 每次最小开仓下单数量`
   - `每次最大下单数量`
   - `<product_code or Chinese product name> 交易指令`
   - `site:dce.com.cn/dce/content 交易指令 每次最小开仓下单数量 通知`
2. Prefer exchange notices with ids like `大商所发〔YYYY〕NN号` when the source
   says a rule is adjusted from a specific trading day or night session.
3. If no adjustment notice exists for a current product-level maximum, search
   the product's futures business rules. DCE business rules often state
   `交易指令每次最大下单数量为...手` in a product-specific article.
4. For options, search the option listing notice first. DCE option listing
   notices often state that option maximum order volume is the same as the
   underlying futures product.

## Audited Example

On 2026-06-29, direct access to
`http://www.dce.com.cn/dce/content/2026/ywggytz/18627837.html` returned WAF
JavaScript in the local environment, but the official URL and notice id were
located and an accessible repost at `https://www.hsqh.net/col49/7101` preserved
the DCE original text for `大商所发〔2026〕74号`.

The reposted original says:

- Effective point: `自2026年3月10日交易时（即3月9日夜盘交易小节时）起`, so
  `effective_trading_day = 2026-03-10` and
  `effective_timestamp = 2026-03-09 21:00:00`.
- Value `8`: `EB/EG/PG/L/V/PP` contracts `2604`, `2605`, `2606`.
- Value `4`: `BZ` contracts `2604`, `2605`, `2606`.

Each product/contract pair must be ingested as one event.

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
