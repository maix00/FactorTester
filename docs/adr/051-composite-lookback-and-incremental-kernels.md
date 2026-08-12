# ADR-051：复合回看契约与增量滚动内核

- **日期**：2026-08-10
- **状态**：已采纳（第一阶段）
- **相关**：ADR-050

## 背景

因子可以把多个回看算子串联或并联，例如：

```text
rolling_mean(rolling_mean(CLOSE, 3), 2) + shift(CLOSE, 1)
```

批量求值、自动 warm-up 和实时增量求值如果各自遍历表达式树，很容易对
串行窗口少加、对并行分支多加，或者在共享子树上因去重而漏掉一条依赖路径。
另一方面，实时 `rolling_ema` 原先每根 bar 都重建完整历史 DataFrame，运行
时间随样本长度呈二次增长。

## 决策

统一使用 `LookbackContract` 遍历 FactorExpr 形状：

- 串行回看算子（rolling、shift）将自身窗口与最长子路径相加；
- 复合、where、横截面等并行节点取子路径最大值；
- `RollingOp` 只遍历 data operands，不把 window 或 truncation 参数当作历史；
- 无法在当前单位解析的窗口标记为 unknown，调用方不得声称使用了更短的
  warm-up；
- 契约同时记录最大单窗、串行深度和节点数量，供审计使用。

实时 rolling EMA 使用与 pandas 默认 `adjust=True, ignore_na=False` 等价的
分子/分母递推状态；普通 rolling mean/std/var/min/max/sum/skew、corr/cov 和
argmin/argmax 使用 NumPy 窗口内核，避免每根 bar 构造 pandas DataFrame。

## 迁移与边界

该阶段不改变 FactorExpr 的批量定义，也不改变信号时间戳。交易日/交易时段
相关的日历窗口仍须由调用方解析为具体 bar 数；增量编译器不会把未知日历
窗口静默解释成固定 bar。

## 验收

- 嵌套和并行回看表达式的 batch 与 live 结果逐时间戳、逐品种比较；
- EMA 缺失值行为与 pandas 默认语义一致；
- 实时计划暴露同一份 lookback contract；
- 长序列不再调用“每根 bar 重建全历史 DataFrame”的路径；
- 结果误差保持在浮点容差内，性能基准记录线性增量路径与旧实现的对照。

