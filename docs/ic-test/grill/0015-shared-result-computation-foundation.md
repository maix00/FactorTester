# Grill 173.16 — 所有 TestModule 共享的结果计算基础层

Status: accepted

## 已确认的范围修正

Result DAG、Result ID、IntermediateResult 和 Artifact 机制不属于 IC 测试专属代码。它们要
成为所有 TestModule 可接入的通用结果模块。

IC 只是第一个使用者。后续至少包括：

- IC 测试；
- 回测；
- 因子类型分析；
- 分组/单调性测试；
- 稳健性和统计有效性测试；
- 未来的多因子测试。

## 通用层只负责什么

推荐通用层只定义五类协议：

```text
ResultID
IntermediateResult
ComputationKernel
ArtifactDefinition
ComputationPlan / ResultGraphExecutor
```

以及以下确定性行为：

1. 从 Artifact IDs 展开 required/supplemental Result IDs；
2. 根据 TestModule 提供的 kernel 集合找到 Result provider；
3. 递归解析 kernel 依赖；
4. 检查缺失 provider、重复 provider 和循环；
5. 拓扑执行；
6. 保存本次运行的内存 Result Store；
7. 调用 Artifact renderer；
8. 生成 kernel 执行摘要、warning 和缺失 supplemental result 记录。

通用层不知道 IC、收益率、手续费、保证金、分组或统计学的含义。

## TestModule 应注册什么

每个具体 TestModule 只向通用结果模块提供自己的定义集合：

```python
class ICTestModule(TestModule):
    result_kernels = (
        ICSeriesKernel,
        ICSummaryStatsKernel,
        ICCoverageKernel,
    )
    artifacts = (
        SingleFactorICSummaryTable,
        SingleFactorICSeriesChart,
    )
```

```python
class BacktestModule(TestModule):
    result_kernels = (
        PortfolioSeriesKernel,
        ReturnSeriesKernel,
        PerformanceStatsKernel,
        DrawdownKernel,
    )
    artifacts = (
        BacktestSummaryTable,
        EquityCurveChart,
        DrawdownChart,
    )
```

这些是类上的静态定义，不要求为每次运行把全局 TestModule 全部注册一遍。控制面可以发现所有
模块的 manifest；执行 worker 只加载当前 Job 选中的 TestModule 及其 kernel/artifact 定义。

## 与领域结果的关系

通用结果模块不能要求所有测试返回相同的数据结构。

例如：

```text
ICComputationResult
BacktestComputationResult
FactorTypeAnalysisComputationResult
```

都可以实现共同的最小接口：

```text
run_identity
result_store
executed_kernel_ids
warnings
```

但各自仍可保留领域中间结果，例如 IC series matrix、PortfolioResult、fills 或分类统计矩阵。
通用层只通过 Result ID 和中间结果类型访问它们。

## 与现有对象的边界

### native backtest ResultStore

当前 `tools/testers/backtest/engines/native/result_store.py` 的 `ResultStore` 按 Strategy 保存回测
历史和最终字段，是回测运行状态的一部分。它不是通用 Result ID Store，不应直接扩展成新的
共享层。

### BacktestResult

当前 `BacktestResult` 是回测领域的最终计算事实，应该继续存在。它可以作为一个整体 Result
被后续 performance kernel 消费，而不是被通用层替代。

### result_metrics

当前 `tools/analytics/result_metrics.py` 注册并全量计算回测指标。以后可以把其中的计算按 Result
ID 需求接到 backtest kernels，但不能让这个 registry 变成跨所有 TestModule 的 Artifact
planner。

## 推荐代码归属

最终目录名要等实现阶段结合现有导入关系确定，语义上应接近：

```text
tools/testers/results/
  ids.py
  intermediate.py
  kernels.py
  artifacts.py
  planner.py
  executor.py
  store.py
```

IC 专属实现放在：

```text
tools/testers/ic_test/results/
```

回测专属实现放在：

```text
tools/testers/backtest/results/
```

文件夹用于表达共享协议与领域实现的边界，不能一开始就把所有具体 kernel 塞进一个大型
`results.py`。

## 最小接入协议

一个新的 TestModule 接入时只需提供：

```text
module_id
kernel definitions
artifact definitions
领域 ComputationResult 类型
```

Job runner 仍只调用：

```text
TestModule.execute(TestRuntime, requested_artifact_ids)
```

TestModule 内部把自己的定义交给通用 planner/executor。Job runner 不理解任何 Result ID，也
不参与 Artifact 计算。

## 已确认

> TestModule 拥有领域计算入口，并调用共享结果模块；TestRuntime 只提供数据、缓存、进度、
> 取消和 artifact sink 等执行基础设施。这样不会让 TestRuntime 反过来理解每种测试的 kernel
> 和领域结果。

迁移方式见 `0016-ic-first-strangler-migration.md`。
