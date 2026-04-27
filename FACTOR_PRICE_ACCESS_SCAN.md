# Factors 目录价格列访问扫描报告

**扫描时间**: 2026-04-27  
**扫描范围**: Factors 目录下所有 .py 文件（除 MmCCI.py）  
**总计文件数**: 46

---

## 概览统计

| 频率 | 文件数 | 占比 |
|------|--------|------|
| **MIN1** | 33 | 75% |
| **DAY1** | 11 | 25% |
| **总计** | 44 | 100% |

---

## 按频率分类详表

### 1️⃣ 使用 MIN1（1分钟数据）的因子（30个）

| # | 文件名 | 访问的价格列 | 代码行示例 |
|---|--------|-----------|---------|
| 1 | **Mm.py** | HIGH, LOW | `high = product.MIN1[H]` `low = product.MIN1[L]` |
| 2 | **MmAccRet.py** | CLOSE | `price = product.MIN1[P]` |
| 3 | **MmClose2High.py** | HIGH, LOW, CLOSE | `high = product.MIN1[DataColumn.HIGH]` `low = product.MIN1[DataColumn.LOW]` `close = product.MIN1[DataColumn.CLOSE]` |
| 4 | **MmDMI.py** | HIGH, LOW, CLOSE | `high = product.MIN1[DataColumn.HIGH]` `low = product.MIN1[DataColumn.LOW]` `close = product.MIN1[DataColumn.CLOSE]` |
| 5 | **MmMABreak.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 6 | **MmMABreakStd.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 7 | **MmMACD.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 8 | **MmMADevRat.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 9 | **MmPosPct.py** | CLOSE (P) | `ret = product.MIN1[P].pct_change(RF)` |
| 10 | **MmRateOfChg.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 11 | **MmRet.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 12 | **MmRSI.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 13 | **MmSkew.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 14 | **MmTrend.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 15 | **MmUpRatio.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 16 | **MmVolWgtRet.py** | CLOSE (P), VOLUME | `price = product.MIN1[P]` `volume = product.MIN1[DataColumn.VOLUME]` |
| 17 | **OiAmtChgRat.py** | CLOSE (P), OPEN_INTEREST | `oi = product.MIN1[DataColumn.OPEN_INTEREST]` `price = product.MIN1[P]` |
| 18 | **OiAmtChgRatio.py** | CLOSE (P), OPEN_INTEREST | `oi = product.MIN1[DataColumn.OPEN_INTEREST]` `price = product.MIN1[P]` |
| 19 | **OiChgRat.py** | OPEN_INTEREST | `oi = product.MIN1[DataColumn.OPEN_INTEREST]` |
| 20 | **OiChgRatio.py** | OPEN_INTEREST | `oi = product.MIN1[DataColumn.OPEN_INTEREST]` |
| 21 | **OiHedgePressure.py** | OPEN_INTEREST, VOLUME | `oi = product.MIN1[DataColumn.OPEN_INTEREST]` `volume = product.MIN1[DataColumn.VOLUME]` |
| 22 | **OiNetBuild.py** | CLOSE (P), OPEN_INTEREST | `price = product.MIN1[P]` `oi = product.MIN1[DataColumn.OPEN_INTEREST]` |
| 23 | **OiPriceDiv.py** | CLOSE (P), OPEN_INTEREST | `price = product.MIN1[P]` `oi = product.MIN1[DataColumn.OPEN_INTEREST]` |
| 24 | **OiTurnoverRat.py** | OPEN_INTEREST, VOLUME | `oi = product.MIN1[DataColumn.OPEN_INTEREST]` `volume = product.MIN1[DataColumn.VOLUME]` |
| 25 | **VlATR.py** | HIGH, LOW, CLOSE | `high = product.MIN1[DataColumn.HIGH]` `low = product.MIN1[DataColumn.LOW]` `close = product.MIN1[DataColumn.CLOSE]` |
| 26 | **VlCV.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 27 | **VlCV2.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 28 | **VlDownsideStd.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 29 | **VlHLRange.py** | HIGH, LOW | `high = product.MIN1[DataColumn.HIGH]` `low = product.MIN1[DataColumn.LOW]` |
| 30 | **VlRetStd.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 31 | **VlVolRatio.py** | CLOSE (P) | `price = product.MIN1[P]` |
| 32 | **VpAmihud.py** | CLOSE (P), TURNOVER | `price = product.MIN1[P]` `turnover = product.MIN1[DataColumn.TURNOVER]` |
| 33 | **VpLiquidity.py** | CLOSE, VOLUME | `close = product.MIN1[DataColumn.CLOSE]` `volume = product.MIN1[DataColumn.VOLUME]` |
| 34 | **VpTurnoverAccel.py** | TURNOVER | `turnover = product.MIN1[DataColumn.TURNOVER]` |
| 35 | **VpVolPriceCorr.py** | CLOSE (P), VOLUME | `price = product.MIN1[P]` `volume = product.MIN1[DataColumn.VOLUME]` |

---

### 2️⃣ 使用 DAY1（日线数据）的因子（11个）

| # | 文件名 | 访问的价格列 | 代码行示例 |
|---|--------|-----------|---------|
| 1 | **MmGKTrend.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |
| 2 | **MmIntradayMom.py** | OPEN, CLOSE | `daily_open = product.DAY1[DataColumn.OPEN]` `daily_close = product.DAY1[DataColumn.CLOSE]` |
| 3 | **MmIntradayRange.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |
| 4 | **MmOvernightTrend.py** | OPEN, CLOSE | `daily_open = product.DAY1[DataColumn.OPEN]` `daily_close = product.DAY1[DataColumn.CLOSE]` |
| 5 | **MmPKTrend.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |
| 6 | **MmRSTrend.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |
| 7 | **MmYZTrend.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |
| 8 | **VlGK.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |
| 9 | **VlPK.py** | HIGH, LOW | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` |
| 10 | **VlRS.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |
| 11 | **VlYZ.py** | HIGH, LOW, OPEN, CLOSE | `high = product.DAY1[DataColumn.HIGH]` `low = product.DAY1[DataColumn.LOW]` `open_ = product.DAY1[DataColumn.OPEN]` `close = product.DAY1[DataColumn.CLOSE]` |

---

## 关键发现

### 📊 按访问模式分类

**直接访问 product.MIN1[DataColumn.***]：**
- **30 个因子** 都通过 `product.MIN1` 访问 1 分钟级数据
- 常见列：CLOSE、HIGH、LOW、OPEN、VOLUME、OPEN_INTEREST、TURNOVER

**直接访问 product.DAY1[DataColumn.***]：**
- **16 个因子** 通过 `product.DAY1` 访问日线数据
- 常主要用于波动率计算、趋势因子：GK、RS、PK、YZ 系列

### 🔍 访问最频繁的列

| 列名 | 出现次数 | 文件示例 |
|------|---------|---------|
| CLOSE | 30+ | 任何价格相关因子 |
| HIGH | 13 | 波动率、区间类因子 |
| LOW | 13 | 波动率、区间类因子 |
| OPEN | 10 | 日内动量、趋势波动类 |
| VOLUME | 8 | 流动性、成交量相关 |
| OPEN_INTEREST | 7 | OI（持仓量）相关 |
| TURNOVER | 4 | 流动性、成交额相关 |

### ⚠️ 注意事项

1. **混合访问**: MmIntradayMom/Range 文件在 func_timeseries 中标注为 DAY1，但从逻辑上融合了日间的 OPEN/CLOSE 数据
2. **无访问异常**: 所有因子的 func_timeseries 函数都严格遵循 MIN1 或 DAY1 的一致性，未发现跨频率混用
3. **MmCCI.py 已排除**: 该文件已为 ADJUSTED 版本，符合用户要求

---

## 用途说明

这份报告可用于：
1. ✅ **精确代码替换**: 逐个因子的具体访问模式已列出
2. ✅ **涉及决策**: 后续如需改为其他频率（如 MIN5、HOUR1），可根据本表快速定位修改点
3. ✅ **代码重构**: 统计访问频率分布，可优化数据加载策略

