# Grill 173.28 — BacktestLifecycleFlow 的输出粒度

Status: accepted

## 问题

前文暂时把复合回测 Flow 的输出写成：

```text
BACKTEST_RESULT
```

如果它只是一个完全不透明的大对象，所有下游指标都只能依赖整个对象：

- Planner 看不到净值、成交、持仓和保证金等真实依赖；
- 一个只需要净值的 Sharpe kernel 也会表现成依赖全部 execution trace；
- Artifact 无法按 Result ID 复用基础事实；
- 容易重新形成一个“万能结果对象”。

但把复合 Flow 改成几十个独立返回对象同样不好：

- Freeze 需要构造并发布大量重复容器；
- 多个结果可能来自同一份 Portfolio/curve 内存；
- 原子性和一致性更难保证；
- 每个下游 Flow 可能重新整理同一份回测状态。

## 与既有 IntermediateResult 决定对齐

推荐复用已经接受的 intermediate result 机制：

```python
class BacktestResult:
    overall_result_id = ResultID("backtest.result")

    result_outputs = {
        ResultID("backtest.equity_path"): ResultOutput(
            value_type=EquityPath,
            resolve=lambda result: result.equity_path,
        ),
        ResultID("backtest.execution_trace"): ResultOutput(
            value_type=ExecutionTrace,
            resolve=lambda result: result.execution_trace,
        ),
        ResultID("backtest.position_path"): ResultOutput(...),
        ResultID("backtest.margin_path"): ResultOutput(...),
        ResultID("backtest.evaluation_split"): ResultOutput(...),
    }
```

这里不是新增另一个 `BacktestSnapshot` 对象。现有领域 `BacktestResult` 演进成冻结的
IntermediateResult：

- 整体有 `backtest.result` Result ID；
- 类属性声明它可提供的基础 Result IDs；
- resolver 只是固定在代码中的轻量属性；
- resolver 不版本化、不写数据库；
- Result Store 可以 memoize 已解析 component；
- Artifact 可以消费整体或具体 component；
- 指标 Flow 用真正需要的 component Result ID 声明依赖。

## Flow 输出与原子发布

`BacktestLifecycleFlow` 的逻辑输出仍是一个完整 OutputBundle：

```text
BacktestLifecycleFlow
  → constructs BacktestResult once
  → validates its declared component schemas
  → atomically publishes overall + provided ResultRefs
```

“发布多个 ResultRef”不表示复制多份数据。Result Store 中的 component slot 可以保存对同一
`BacktestResult` 的 resolver binding 或首次解析后的只读引用。

例如：

```text
RiskMetricsFlow
  requires: backtest.equity_path

TurnoverFlow
  requires: backtest.execution_trace

BacktestAuditArtifact
  requires: backtest.result
```

这样 Planner 保留 Result ID 粒度，同时 Freeze 只构造一个领域结果对象。

## 当前 BacktestResult 的迁移边界

当前 `tools/testers/backtest/engines/native/contracts.py` 已有 frozen `BacktestResult`，但当前
native worker 实际仍在 scheduler 返回后拼装 dict，并未使用该对象作为统一结果边界。

迁移时应：

1. 保留 `BacktestResult` 领域身份，不创建平行 Snapshot 类型；
2. 将 scheduler 后的 portfolios/target trace 组装移入复合 Flow 的 Freeze；
3. 从 `metrics` 字段移出可按需计算的风险指标，避免 Lifecycle 全量计算；
4. `diagnostics` 只保存运行事实与 warning，不塞 Renderer 输出；
5. 检查 frozen dataclass 内部的 Mapping/Series 所有权，不能把 `frozen=True` 误当深层不可变；
6. 以 resolver 提供基础 Result IDs，不把每个 component 复制或 JSON 化。

## Result ID 范围

基础 Result ID 只登记能够作为其他计算或 Artifact 输入的稳定事实，不为每个内部字段制造 ID。

初步候选：

```text
backtest.result
backtest.portfolios
backtest.equity_path
backtest.position_path
backtest.notional_path
backtest.margin_path
backtest.execution_trace
backtest.target_trace
backtest.evaluation_split
```

Sharpe、最大回撤、年化收益率等不是 Lifecycle 的基础输出，而由后续 Result Flow 提供：

```text
backtest.return_series
backtest.sharpe
backtest.max_drawdown
backtest.annualized_return
```

具体 Result ID 清单在逐个审计回测指标 kernel 时确定；本轮只确定输出模型。

## 性能

该方案不会按 Result ID 重复调用重型函数：

- Freeze 一次构造 `BacktestResult`；
- resolver 只做字段访问、视图选择或轻量投影；
- 非轻量 resolver 的结果在本 Job 中 memoize；
- 多指标扫描仍由一个多输出 kernel 聚合；
- 大曲线不在 component publication 时复制；
- 未被 Artifact 或下游 kernel 需求的 component 不必提前物化。

## 已确认

复合回测 Flow 应返回一个 `BacktestResult` IntermediateResult，并通过类属性 resolver 声明可
提供的基础 Result IDs。不要创建平行 `BacktestSnapshot`，也不要把它保持成只能整体消费的
不透明结果。

已接受：

> `BacktestLifecycleFlow` 只构造一次现有领域 `BacktestResult`，把它作为可整体消费的
> IntermediateResult；该类通过固定 resolver 声明净值、成交、持仓、保证金等基础 Result
> IDs，外层原子发布这些逻辑槽位但不复制数据；Sharpe、回撤等继续由后续 Result Flow 按需
> 计算。
