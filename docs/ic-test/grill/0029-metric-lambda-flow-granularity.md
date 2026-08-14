# Grill 173.30 — 指标 lambda 与 Result Flow 的粒度

Status: accepted

## 问题

Sharpe、最大回撤等当前只是：

```python
ResultMetric(key, label, compute_function)
```

若为每一个 metric function 创建一个 Flow 类和独立节点，会造成：

- 大量无意义类和声明；
- planner 节点膨胀；
- 相同收益路径被反复读取；
- max drawdown、Calmar 等重复扫描；
- 函数调用和 receipt 数量远大于实际研究计算；
- Agent 和维护者需要理解一张由标量指标组成的碎片图。

因此 Result ID 的细粒度不能直接等于 Flow/kernel 的粒度。

## 当前代码审计

`tools/analytics/result_metrics.py` 当前已经采用“一个 context、多个 metric function”：

```text
ResultMetricContext(equity, returns)
→ annual_return lambda/function
→ sharpe lambda/function
→ max_drawdown lambda/function
→ ...
```

但还有三个问题：

1. `compute_result_metrics()` 总是计算全 registry；
2. `_calmar_ratio()` 会重新调用 annual return 和 max drawdown，重复工作；
3. `avg_turnover` 与其他指标共用只含 equity/returns 的 context，因此当前只能固定返回 `0.0`，
   它真实需要 execution/turnover 输入，不属于同一个计算组。

## 推荐的分层

### Result ID：保持细粒度

```text
backtest.annualized_return
backtest.sharpe
backtest.max_drawdown
backtest.sortino
backtest.calmar
backtest.win_rate
```

Artifact 可以精确声明需要哪些事实。

### Intermediate Result：按共享数据组织

```text
PerformancePathResult
  - return_series
  - drawdown_series
  - return moments / common aggregates

PerformanceSummaryResult
  - annualized_return
  - sharpe
  - max_drawdown
  - sortino
  - calmar
  - win_rate
  - skewness
  - kurtosis
```

### Flow/kernel：按一次有意义的共享计算组织

```text
PerformancePathFlow
  equity_path
  → PerformancePathResult

PerformanceSummaryFlow
  PerformancePathResult
  → PerformanceSummaryResult

TurnoverSummaryFlow
  execution_trace
  → TurnoverSummaryResult
```

因此 Sharpe 和 max drawdown 的函数仍然可以是普通函数或 lambda。它们是
`PerformanceSummaryFlow` 内部的 metric definitions，不各自成为 Flow。

## 示例

```python
PERFORMANCE_SUMMARY = MetricSetOperation(
    metrics=(
        ResultMetric(SHARPE, compute_sharpe),
        ResultMetric(MAX_DRAWDOWN, read_min_drawdown),
        ResultMetric(ANNUALIZED_RETURN, compute_annualized_return),
        ResultMetric(CALMAR, compute_calmar_from_shared_values),
    ),
)
```

```python
PerformanceSummaryFlow(
    inputs=(PERFORMANCE_PATH_RESULT,),
    output_type=PerformanceSummaryResult,
    operation=PERFORMANCE_SUMMARY,
)
```

执行器调用一次 Flow；Flow 内部执行若干轻量 metric functions；最后原子发布
`PerformanceSummaryResult` 提供的多个 Result IDs。

## 按需与复杂度的平衡

不建议初版为了“只请求 Sharpe 就绝不算 win rate”而让每个 metric 变成独立 Flow。

建议分三档：

1. 同一内存对象上的廉价标量统计：放进一个多输出 MetricSet Flow；
2. 输入依赖不同或需要额外扫描的数据：拆成另一个 Flow；
3. bootstrap、Deflated Sharpe、HAC 等昂贵方法：独立按需 Flow。

廉价 MetricSet 即使多算几个 lambda，成本也远低于加载、对齐和扫描 pandas 序列。真正应
避免的是重复构造收益、回撤和成交路径。

如果以后基准表明某个 metric 昂贵，可以把它从 MetricSet 提升为独立 Flow，不改变其
Result ID 或 Artifact 契约。

## Flow 是否必须是复杂类

不必须。Flow 是静态声明加 operation：

```python
FlowDefinition(
    contract=...,
    operation=MetricSetOperation(...),
)
```

它不要求为每个指标继承新类。只有 IntermediateResult 需要明确类型/schema；metric function
继续是简单纯函数。

## 已确认

保留现有 `ResultMetric` 小函数思想，但把它们按共享输入和计算边界组成少数多输出
MetricSet Result Flows。Result ID 细、Flow 粗。

已接受：

> Sharpe、最大回撤等继续是普通函数/lambda 和独立 Result IDs，不各自封装成 Flow；回测先
> 用 `PerformancePathFlow` 统一生成收益/回撤等共享路径，再由一个多输出
> `PerformanceSummaryFlow` 批量计算廉价指标；换手和 bootstrap 等因输入或成本不同而拆成
> 独立 Flow。
