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

## Audited Product-Level Examples

Guosen's current snapshot can mention old CZCE adjustments as a single latest
state. When the original notice says only `<品种>期货合约` and does not list a
specific contract range, store the event at product level with
`contract_codes = []`.

- Red dates (`CJ`):
  - `郑商所发〔2021〕108号`: accessible repost
    `https://www.founderfu.com/fzzqqh_2019/details_247_41617.html`.
    Effective from `2021-12-16`. Product-level fields:
    `MinLimitOrderVolume = 4`, `MaxLimitOrderVolume = 100`,
    `MaxMarketOrderVolume = 20`.
  - `郑商所发〔2022〕98号`: accessible repost
    `https://www.bhfcc.com/customer-center-ques-details.html?id=8761`.
    Effective from `2022-12-15`. Product-level
    `MinLimitOrderVolume = 2`, plus a contract-level exception
    `CJ2301 MinLimitOrderVolume = 4`.
  - `郑商所发〔2023〕53号`: accessible repost
    `https://www.hsqh.net/col49/1389`. Effective from `2023-07-12`.
    Product-level `MinLimitOrderVolume = 1`.
- Thermal coal (`ZC`):
  - `郑商所发〔2022〕8号`: accessible repost
    `https://futures.pingan.com/pinganqihuogonggao/1645407031701.shtml`.
    Effective from the `2022-02-21` night session, so
    `effective_trading_day = 2022-02-22` and
    `effective_timestamp = 2022-02-21 21:00:00`. Product-level fields:
    `MinLimitOrderVolume = 2`, `MaxLimitOrderVolume = 50`,
    `MaxMarketOrderVolume = 10`.
  - `郑商函〔2022〕15号`: accessible repost
    `https://www.xdsfutures.com.cn/company-news-details.aspx?category=18&id=665`.
    Effective from the `2022-03-08` night session, so
    `effective_trading_day = 2022-03-09` and
    `effective_timestamp = 2022-03-08 21:00:00`. Product-level
    `MinLimitOrderVolume = 4`.
