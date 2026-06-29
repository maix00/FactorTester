# LimitOrderVolume_CFFEX

Use this file when cleaning China Financial Futures Exchange official sources
for order-volume fields.

## Source

- Data source id: `CFFEX`
- Official site: `https://www.cffex.com.cn`
- Exchange notices: `https://www.cffex.com.cn/cn/jystz.html`
- Business/rule resources often live under `https://www.cffex.com.cn/cn/ywzy/`
  or PDF paths under `/u/cms/www/`.

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`
- `MaxLimitOrderVolume`
- `MaxMarketOrderVolume`

## Notice Discovery

Guosen currently has CFFEX products in the unified snapshot. When a Guosen row
maps to `ExchangeID = CFFEX`, search CFFEX official notices and product
contract rules:

1. Search exchange notices:
   - `site:cffex.com.cn/cn/jystz 交易指令 每次最大下单数量`
   - `site:cffex.com.cn/cn/jystz 调整 限价指令 市价指令 最大下单数量`
2. Search business/rule pages:
   - `site:cffex.com.cn/cn/ywzy <产品名> 合约交易细则 每次最大下单数量`
   - `site:cffex.com.cn/u/cms/www <产品名> 合约交易细则 每次最大下单数量`
3. Search abnormal-trading standards only as supporting context. Those notices
   may reference `交易所规定的限价指令每次最大下单数量` but usually do not define
   the actual field value.

## Extraction Rules

- CFFEX product contract rules often define order-volume fields per product
  family, such as股指期货 or国债期货. Store product-level events with
  `contract_codes = []` unless explicit contracts are named.
- `每次最小下单数量` -> `MinLimitOrderVolume`.
- `限价指令每次最大下单数量` -> `MaxLimitOrderVolume`.
- `市价指令每次最大下单数量` -> `MaxMarketOrderVolume`.
- If a notice says a value changes for a named contract family from a date,
  create one event per affected product family. If individual contracts are
  listed, create one event per contract.
