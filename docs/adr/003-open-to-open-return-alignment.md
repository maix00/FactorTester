# ADR-003：OPEN-TO-OPEN 收益率时间对齐验证

## 状态

已完成（2026-05-12）

## 背景

`CrossSectionIC.factor_expr()` 中的 RE（收益率表达式）公式：

```python
# tools/factors/FactorFamily.py:434
RE = (SC.delta(RF) / SC.shift(RF)).shift(-RF).shift(S - 1)
```

当用户报告 OPEN-TO-OPEN 场景下的收益率时间对齐可能有问题时，我们进行了系统性验证。

## 用户语义澄清

用户明确阐明了 OPEN-TO-OPEN 的期望语义（以 5 分钟因子为例）：

> 信号在 bar t（如 09:05），OPEN-TO-OPEN 就是 t+1 bar（09:06）的 open 买入，t+2 bar（09:11）的 open 卖出的收益率

> CLOSE-TO-CLOSE：信号在 bar t（如 09:05），就是 t bar 的 close 买入，t+1 bar（09:10）的 close 卖出的收益率

> 日度因子：信号在 T 日 15:00，OPEN-TO-OPEN 就是 T+1 日的 open 买入，T+2 日的 open 卖出的收益率

## 公式分析

### RE 公式展开

```
RE = (SC.delta(RF) / SC.shift(RF)).shift(-RF).shift(S - 1)

SC=OPEN_ADJUSTED → S=0 → RE = ret_raw.shift(-RF).shift(-1)
SC=CLOSE_ADJUSTED → S=1 → RE = ret_raw.shift(-RF).shift(0) = ret_raw.shift(-RF)

其中 ret_raw[t] = SC[t] / SC[t-RF] - 1  (RF 窗口的简单收益率)
```

### shift(-RF) 和 shift(-1) 的语义

- `.shift(-RF)`: 将收益率从"计算位置"前移到"收益实现位置"。ret_raw 在 bar t 计算的是 SC[t]/SC[t-RF]-1（回溯 RF 的收益率），shift(-RF) 让它指向收益率真正发生的时间段。
- `.shift(-1)`: 仅 OPEN-TO-OPEN 使用。代表"买入 bar"到"卖出 bar"之间的 1 bar 间隙。对于 OPEN，买在下一 bar（t+1），卖在下下 bar（t+2），需要 +1 bar 的额外偏移。

## 验证结果

### 场景 1：日频 + OPEN-TO-OPEN (RF=1d)

```
ret_raw[T]  = OA[T] / OA[T-1d] - 1
RE[T]       = ret_raw.shift(-1d).shift(-1)[T] = ret_raw[T+2]
            = OA[T+2] / OA[T+1] - 1
```

| 信号日 T | OA[T] | OA[T+1] | OA[T+2] | RE = OA[T+2]/OA[T+1]-1 | 语义 |
|---------|-------|---------|---------|----------------------|------|
| 2025-05-19 | 4173.00 | 4178.00 | 4191.00 | 0.00311154 | T+1买, T+2卖 |

**✅ RE[T] = OA[T+2]/OA[T+1]-1 = T+1日开盘买入 + T+2日开盘卖出，与用户语义一致**

### 场景 2：日频 + CLOSE-TO-CLOSE (RF=1d)

```
ret_raw[T]  = CA[T] / CA[T-1d] - 1
RE[T]       = ret_raw.shift(-1d).shift(0)[T] = ret_raw[T+1]
            = CA[T+1] / CA[T] - 1
```

| 信号日 T | CA[T] | CA[T+1] | RE = CA[T+1]/CA[T]-1 | 语义 |
|---------|-------|---------|---------------------|------|
| 2025-05-19 | 4182.00 | 4191.00 | 0.00215208 | T买, T+1卖 |

**✅ RE[T] = CA[T+1]/CA[T]-1 = 当日买入 + 次日卖出，与用户语义一致**

### 场景 3：日内 + OPEN-TO-OPEN (RF=5min, no-skip)

数据频率 1min, RF=5min=5bars：

```
ret_raw[t]  = OA[t] / OA[t-5min] - 1
RE[t]       = ret_raw.shift(-5min).shift(-1)[t] = ret_raw[t+6]
            = OA[t+6] / OA[t+1] - 1
```

A.DCE 2025-11-26 开盘 1-min K线（OA）：

| bar | time | OA | 角色 |
|-----|------|-----|------|
| 4 | 09:05 | 4105.00 | **信号 bar** |
| 5 | 09:06 | 4101.00 | 买入 bar |
| 10 | 09:11 | 4102.00 | 卖出 bar |

RE[bar4] = OA[bar10]/OA[bar5]-1 = 4102/4101-1 = 0.00024384

**✅ 信号 bar4 (09:05) → 买入 bar5 (09:06) → 卖出 bar10 (09:11)，与用户语义一致**

### 场景 4：日内 + OPEN-TO-OPEN (RF=5min, end_session_skip=YES)

跨 session 示例（2025-11-25 收盘 → 2025-11-26 夜盘开盘）：

| bar# | time | OA | gap |
|------|------|-----|-----|
| 5 | 2025-11-25 15:00 | 4107.00 | - |
| 6 | 2025-11-25 21:01 | 4115.00 | 6h01m (≥3h) |
| ... | ... | ... | ... |
| 126 | 2025-11-26 09:01 | 4110.00 | 10h01m (≥3h) |

end_session_skip=True 时：
- gap ≥ 3h 处被视为 session 边界
- SignalAlign 采样点从每个 session 起始重新计数
- **不影响 RE 内部公式**：`.shift(-5min).shift(-1)` 在所有 session 内保持一致

**✅ skip 仅改变 SignalAlign 采样点位置，RE 的 shift 语义不变**

### 场景 5：日内 + CLOSE-TO-CLOSE (RF=5min, no-skip)

```
RE[t] = ret_raw.shift(-5min).shift(0)[t] = ret_raw[t+5]
      = CA[t+5] / CA[t] - 1
```

| bar | time | CA | 角色 |
|-----|------|-----|------|
| 4 | 09:05 | 4101.00 | **信号 bar，买入** |
| 9 | 09:10 | 4103.00 | 卖出 bar |

RE[bar4] = CA[bar9]/CA[bar4]-1 = 4103/4101-1 = 0.00048768

**✅ 信号 bar4 (09:05) → 当期买入 → bar9 (09:10) 卖出，与用户语义一致**

## 完整场景矩阵

| 场景 | RE 公式 | 化简 | 语义 | 结果 |
|------|---------|------|------|------|
| daily + OA + RF=1d | ret_raw.shift(-1d).shift(-1) | OA[T+2]/OA[T+1]-1 | T+1买, T+2卖 | ✅ |
| daily + CA + RF=1d | ret_raw.shift(-1d).shift(0) | CA[T+1]/CA[T]-1 | T买, T+1卖 | ✅ |
| 1min + OA + RF=5min + noskip | ret_raw.shift(-5min).shift(-1) | OA[t+6]/OA[t+1]-1 | t+1买, t+6卖 | ✅ |
| 1min + OA + RF=5min + skip | 同上 (仅 SignalAlign 不同) | 同上 | 同上 | ✅ |
| 1min + CA + RF=5min + noskip | ret_raw.shift(-5min).shift(0) | CA[t+5]/CA[t]-1 | t买, t+5卖 | ✅ |
| 1min + OA + RF=1d + noskip | ret_raw.shift(-1d).shift(-1) | OA[t+1d+1]/OA[t+1d]-1 | 下日开盘买, 下下日开盘卖 | ✅ |
| 1min + CA + RF=1d + noskip | ret_raw.shift(-1d).shift(0) | CA[t+1d]/CA[t]-1 | 当期买, 下日同bar卖 | ✅ |

## 决定

`.shift(-1)` **不是多余的**。它是 OPEN-TO-OPEN 语义的核心组成部分：

- **CLOSE-TO-CLOSE**: 买入在信号 bar (t)，卖出在 (t+RF)。只有 `.shift(-RF)` 足够。
- **OPEN-TO-OPEN**: 买入在下个 bar (t+1)，卖出在 (t+RF+1)。需要额外的 `.shift(-1)` 来跨过买卖之间的一期间隙。

**公式正确，无需修改。**

## 验证脚本

`tests/verify_all_scenarios_v2.py` — 包含所有 7 种场景的逐步验证，使用 A.DCE 真实数据。
