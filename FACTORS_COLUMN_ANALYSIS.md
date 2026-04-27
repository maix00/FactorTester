# Factors目录 - 数据列使用汇总分析

## 📊 完整汇总表格 (47个因子)

| 序号 | 文件名 | 使用的列名 | 调整情况 |
|------|--------|-----------|--------|
| 1 | Mm.py | HIGH, LOW | ✗ 非ADJUSTED |
| 2 | MmAccRet.py | CLOSE | ✗ 非ADJUSTED |
| 3 | MmCCI.py | CLOSE_ADJUSTED, HIGH_ADJUSTED, LOW_ADJUSTED | ✓ 全部ADJUSTED |
| 4 | MmClose2High.py | CLOSE, HIGH, LOW | ✗ 非ADJUSTED |
| 5 | MmDMI.py | CLOSE, HIGH, LOW | ✗ 非ADJUSTED |
| 6 | MmGKTrend.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 7 | MmIntradayMom.py | CLOSE, OPEN | ✗ 非ADJUSTED |
| 8 | MmIntradayRange.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 9 | MmMABreak.py | CLOSE | ✗ 非ADJUSTED |
| 10 | MmMABreakStd.py | CLOSE | ✗ 非ADJUSTED |
| 11 | MmMACD.py | CLOSE | ✗ 非ADJUSTED |
| 12 | MmMADevRat.py | CLOSE | ✗ 非ADJUSTED |
| 13 | MmOvernightTrend.py | CLOSE, OPEN | ✗ 非ADJUSTED |
| 14 | MmPKTrend.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 15 | MmPosPct.py | CLOSE | ✗ 非ADJUSTED |
| 16 | MmRateOfChg.py | CLOSE | ✗ 非ADJUSTED |
| 17 | MmRet.py | CLOSE | ✗ 非ADJUSTED |
| 18 | MmRSI.py | CLOSE | ✗ 非ADJUSTED |
| 19 | MmRSTrend.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 20 | MmSkew.py | CLOSE | ✗ 非ADJUSTED |
| 21 | MmTrend.py | CLOSE | ✗ 非ADJUSTED |
| 22 | MmUpRatio.py | CLOSE | ✗ 非ADJUSTED |
| 23 | MmVolWgtRet.py | VOLUME | - 非价格列 |
| 24 | MmYZTrend.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 25 | OiAmtChgRat.py | CLOSE, OPEN_INTEREST | ✗ 非ADJUSTED |
| 26 | OiAmtChgRatio.py | CLOSE, OPEN_INTEREST | ✗ 非ADJUSTED |
| 27 | OiChgRat.py | OPEN_INTEREST | - 非价格列 |
| 28 | OiChgRatio.py | OPEN_INTEREST | - 非价格列 |
| 29 | OiHedgePressure.py | OPEN_INTEREST, VOLUME | - 非价格列 |
| 30 | OiNetBuild.py | CLOSE, OPEN_INTEREST | ✗ 非ADJUSTED |
| 31 | OiPriceDiv.py | CLOSE, OPEN_INTEREST | ✗ 非ADJUSTED |
| 32 | OiTurnoverRat.py | OPEN_INTEREST, VOLUME | - 非价格列 |
| 33 | VlATR.py | CLOSE, HIGH, LOW | ✗ 非ADJUSTED |
| 34 | VlCV.py | CLOSE | ✗ 非ADJUSTED |
| 35 | VlCV2.py | CLOSE | ✗ 非ADJUSTED |
| 36 | VlDownsideStd.py | CLOSE | ✗ 非ADJUSTED |
| 37 | VlGK.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 38 | VlHLRange.py | HIGH, LOW | ✗ 非ADJUSTED |
| 39 | VlPK.py | HIGH, LOW | ✗ 非ADJUSTED |
| 40 | VlRetStd.py | CLOSE | ✗ 非ADJUSTED |
| 41 | VlRS.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 42 | VlVolRatio.py | CLOSE | ✗ 非ADJUSTED |
| 43 | VlYZ.py | CLOSE, HIGH, LOW, OPEN | ✗ 非ADJUSTED |
| 44 | VpAmihud.py | TURNOVER | - 非价格列 |
| 45 | VpLiquidity.py | CLOSE, VOLUME | ✗ 非ADJUSTED |
| 46 | VpTurnoverAccel.py | TURNOVER | - 非价格列 |
| 47 | VpVolPriceCorr.py | VOLUME | - 非价格列 |

---

## 📈 统计汇总

### 按调整情况分类

| 类别 | 数量 | 占比 | 典型代表 |
|------|------|------|--------|
| ✓ 全部ADJUSTED版本 | 1 | 2.1% | MmCCI |
| ✗ 非ADJUSTED或混合版本 | 32 | 68.1% | MmGKTrend, MmRSTrend, VlRS, etc. |
| - 非价格列相关因子 | 14 | 29.8% | MmVolWgtRet, OiChgRatio, VpLiquidity, etc. |
| **总计** | **47** | **100%** | - |

### 数据列使用频率

| 列名 | 使用数量 | 详情 |
|------|---------|------|
| CLOSE | 32 | 非ADJUSTED: 31 + ADJUSTED: 1 |
| HIGH | 13 | 非ADJUSTED: 12 + ADJUSTED: 1 |
| LOW | 13 | 非ADJUSTED: 12 + ADJUSTED: 1 |
| OPEN | 11 | 全部非ADJUSTED |
| OPEN_INTEREST | 9 | 与CLOSE/VOLUME配合 |
| VOLUME | 6 | 流动性/风险相关因子 |
| TURNOVER | 3 | 交易额相关因子 |

### 按数据类型统计

| 数据频率 | 因子数 | ADJUSTED情况 |
|---------|--------|----------|
| DAY1数据 | 11 | 全部非ADJUSTED |
| MIN1数据 | 36 | 非ADJUSTED: 35 + ADJUSTED: 1 |

---

## 🔍 关键发现

### 1️⃣ ADJUSTED版本极其稀缺
- **现状**: 仅1个因子 (MmCCI) 使用ADJUSTED列
- **原因分析**:
  - 日线数据中可能已考虑复权
  - 许多因子设计本身不依赖价格绝对值
  - 历史数据可能已默认复权处理

### 2️⃣ 分频率观察
- **DAY1日线数据 (11个因子)**: 
  - 全部使用非ADJUSTED版本
  - 包括: MmGKTrend, MmPKTrend, MmYZTrend, VlGK, VlPK, VlRS, VlYZ等
  
- **MIN1分钟数据 (36个因子)**:
  - 35个使用非ADJUSTED (97.2%)
  - 1个使用ADJUSTED (2.8%): MmCCI

### 3️⃣ 因子类型分布
- **价格方向因子** (17个): 使用OPEN/CLOSE/HIGH/LOW
  - 全部非ADJUSTED: MmGKTrend, MmRSTrend, MmYZTrend等
  
- **价格收益率因子** (15个): 使用CLOSE或其衍生
  - 全部非ADJUSTED: MmRet, MmRSI, MmMACD等
  
- **波动率/流动性因子** (15个): 使用VOLUME/TURNOVER等
  - 与价格无直接关系

### 4️⃣ 参数化设计模式
许多因子采用参数化P列设计：
```python
P: DataColumn = DataColumn.CLOSE  # 默认CLOSE
price = product.MIN1[P]
```
- 包括: MmAccRet, MmTrend, MmRet, VlCV, VlRetStd等
- 灵活性高，但默认值全为非ADJUSTED

---

## 💡 应用建议

### 对于数据供应端
1. 确认DAY1/MIN1数据是否已剔除复权影响
2. 验证ADJUSTED列的生成逻辑是否正确
3. 检查MmCCI的数据质量（唯一ADJUSTED用户）

### 对于因子使用端
1. **理解价格调整假设**:
   - 若数据未调整，使用这些因子的结果将受除权除息影响
   - 特别关注期货品种的交割月复权

2. **MmCCI监控**:
   - 作为仅有的ADJUSTED版本用户
   - 确保ADJUSTED_*列的数据完整性
   - 与其他因子结果做对标检验

3. **批量因子计算**:
   - 优先提供未复权数据
   - 在需要时再做后处理复权

### 对于因子开发
- 若需使用ADJUSTED版本，可参考MmCCI的实现方式
- 新增因子应明确标注价格调整假设

---

## 📝 附录：列名说明

| 列名 | 含义 | 调整状态 |
|------|------|--------|
| OPEN | 开盘价 | 未调整 |
| HIGH | 最高价 | 未调整 |
| LOW | 最低价 | 未调整 |
| CLOSE | 收盘价 | 未调整 |
| OPEN_ADJUSTED | 开盘价 | 已复权 |
| HIGH_ADJUSTED | 最高价 | 已复权 |
| LOW_ADJUSTED | 最低价 | 已复权 |
| CLOSE_ADJUSTED | 收盘价 | 已复权 |
| VOLUME | 成交量 | - |
| TURNOVER | 成交额 | - |
| OPEN_INTEREST | 持仓量 | - |

---

**分析日期**: 2026-04-27  
**总因子数**: 47  
**数据来源**: Factors目录下所有.py文件的func_timeseries函数分析
