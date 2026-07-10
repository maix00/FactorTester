# SHFE（上期所）数据入库规范

## 数据获取

HTTP GET 直接获取 JSON，**不需要 Chrome**。

**URL：**
```
https://www.shfe.com.cn/data/tradedata/future/dailydata/js{YYYYMMDD}.dat
```

**响应结构：** `{"o_cursor": [...], "o_code": 0, ...}`
每条记录包含：

| JSON字段 | DB字段 | 说明 |
|---------|-------|------|
| `SPECLONGMARGINRATIO` | `LongMarginRatioByMoney` | 保证金率 |
| `SPECSHORTMARGINRATIO` | `ShortMarginRatioByMoney` | 保证金率 |
| `TRADEFEERATIO` | `OpenRatioByMoney`（ISUNITODAY=0时）或 `OpenRatioByVolume`（ISUNITODAY=1时） | 手续费率 |
| `ISUNITODAY` | — | 0=比例值(万分之), 1=绝对值(元/手) |

## 版本引用

| 日期范围 | 引用版本 | 公告字号 | CSRC UUID |
|---------|---------|---------|-----------|
| ≤ 2024-08-22 | 2023年7月修订 | 〔2023〕63号 | `1761c86458d8466f96cfa140b5358b3f` |
| 2024-08-23 ~ 2025-07-07 | 2024年修订 | 上海期货交易所公告〔2024〕136号 | — |
| ≥ 2025-07-08 | 2025年修订 | 上期公告〔2025〕87号 | — |

## 第五条原文（4阶梯）

> **合约挂牌之日起：4~8%（品种不同）**
> **交割月前第一月的第一个交易日起：10%**
> **交割月份第一个交易日起：15%**
> **最后交易日前二个交易日起：20%**

与 DCE 不同：SHFE 有 4 个阶梯（多一个最后交易日 20%）。
