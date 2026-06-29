# LimitOrderVolume_CZCE

Use this file when cleaning Zhengzhou Commodity Exchange official sources for
order-volume fields.

## Source

- Data source id: `CZCE`
- Official site: `https://www.czce.com.cn`
- Rule documents usually live under `cn/content_file/flfg/zcjywgz/`.
- Product business rules live under `pzxz`.
- Example rule source:
  `https://www.czce.com.cn/cn/content_file/flfg/zcjywgz/ywbf/2026/5/a5ad00e02e484498abdbac8ddbfd5c35.pdf`

## Field Group

`LimitOrderVolume`

Supported fields:

- `MinLimitOrderVolume`
- `MaxLimitOrderVolume`
- `MaxMarketOrderVolume`

## Notice Discovery

Guosen currently has CZCE products in the unified snapshot. When a Guosen row
maps to `ExchangeID = CZCE`, search CZCE official rules and notices in this
order:

1. Search product business rules:
   - `site:czce.com.cn/cn/content_file/flfg/zcjywgz/pzxz <品种名> 期货业务细则 交易指令 每次最大下单量`
   - `site:czce.com.cn <product_code> 期货业务细则 交易指令 每次最大下单量`
2. Search exchange trading management rules:
   - `site:czce.com.cn/cn/content_file/flfg/zcjywgz/ywbf 期货交易管理办法 交易指令 每次最小下单量 最大下单量`
3. Search explicit adjustment notices:
   - `site:czce.com.cn 调整 交易指令 每次最小开仓下单量`
   - `site:czce.com.cn 调整 交易指令 每次最大下单量`

## Extraction Rules

- CZCE futures business rules commonly state product-level values such as
  `交易指令每次最小下单量为1手，限价指令每次最大下单量为1000手，市价指令每次最大下单量为200手`.
- Treat `限价指令每次最大下单量` as `MaxLimitOrderVolume`.
- Treat `市价指令每次最大下单量` as `MaxMarketOrderVolume`.
- Treat `每次最小下单量` as `MinLimitOrderVolume`, unless the source states a
  more specific `每次最小开仓下单量`; then store the specific value in
  `raw_note` and `parser_notes`.
- Product-level rules use `contract_codes = []`.
- If the source names specific contracts, split into one event per contract.
- If a business rule says the exchange may adjust standards separately, keep
  searching for later adjustment notices before using the business-rule value
  for dates after the possible adjustment.

## Audited Example

On 2026-06-29, the local environment could not directly fetch CZCE official
notice text due anti-bot/precondition responses, but an accessible repost at
`https://www.hsqh.net/col49/7101` preserved the CZCE original notice
`郑商函〔2026〕43号`.

The reposted original says:

- Effective point: `自2026年3月9日当晚夜盘交易时起`, so
  `effective_trading_day = 2026-03-10` and
  `effective_timestamp = 2026-03-09 21:00:00`.
- Value `8`: `MA` contracts `2606`, `2607`, `2608`, `2609`;
  `PX/TA/PF` contracts `2604`, `2605`, `2606`, `2607`, `2608`, `2609`.
- Value `4`: `PR/SH/PL` contracts `2604`, `2605`, `2606`, `2607`, `2608`,
  `2609`.

Each product/contract pair must be ingested as one event.
