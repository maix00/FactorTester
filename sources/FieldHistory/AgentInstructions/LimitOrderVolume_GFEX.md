# LimitOrderVolume_GFEX

Use this file when cleaning Guangzhou Futures Exchange official sources for
order-volume fields.

## Source

- Data source id: `GFEX`
- Official site: `https://www.gfex.com.cn`
- Notice list: `https://www.gfex.com.cn/gfex/tzts/list_yw_7.shtml`
- Example sources:
  - `https://www.gfex.com.cn/gfex/tzts/202512/fe6524824fa24c5b9597459c28bea109.shtml`
  - `https://www.gfex.com.cn/gfex/tzts/202603/c9b5c6bcc14543b8a0f2dd6b1d2d809d.shtml`

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`
- `MaxLimitOrderVolume`
- `MaxMarketOrderVolume`

## Notice Discovery

Guosen currently has GFEX products in the unified snapshot. When a Guosen row
maps to `ExchangeID = GFEX`, search GFEX official notices first:

1. Search the notice list and web index:
   - `site:gfex.com.cn/gfex/tzts 交易指令 每次最小开仓下单数量`
   - `site:gfex.com.cn/gfex/tzts 每次最小开仓下单数量 交易限额 通知`
   - `site:gfex.com.cn/gfex/tzts <品种名> 交易指令 每次最小开仓下单数量`
2. For current default maximum values, search product business rules:
   - `site:gfex.com.cn/gfex <品种名> 期货 期权 业务细则 交易指令 每次最大下单数量`
3. GFEX adjustment notices often bundle order-volume changes with fee,
   position-limit, margin, or price-limit changes. Extract only the
   LimitOrderVolume fields and keep other fields out of this field group.

## Extraction Rules

- GFEX notices often target specific contracts such as `PS2604` or `LC2601`.
  Split into one event per contract.
- `交易指令每次最小开仓下单数量` is narrower than generic
  `MinLimitOrderVolume`. Store it as `MinLimitOrderVolume` only when the
  consumer explicitly wants the opening-order minimum; otherwise mark the
  specificity in `parser_notes`.
- Product business rules may define generic maximum order quantity. Store those
  as product-level events with `contract_codes = []`.
- If one notice lists several products and contracts with the same value, split
  every product/contract pair into its own event.
