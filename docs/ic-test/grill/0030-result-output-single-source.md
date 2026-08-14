# Grill 173.31 — Flow 输出与 IntermediateResult 的单一事实源

Status: withdrawn as overdesigned; replaced by Grill 173.32

> “顶层 ResultRef 自动展开 component providers”的方案增加了不必要的间接层。
> [Grill 173.32](0031-direct-flow-ports.md) 改为 Flow inputs/outputs 直接声明
> `StateRef` 或 `ResultID`。

## 问题

当前设计中可能同时出现：

```python
FlowDefinition(outputs=(SHARPE, MAX_DRAWDOWN, ...))
```

以及：

```python
class PerformanceSummaryResult:
    result_outputs = {
        SHARPE: ...,
        MAX_DRAWDOWN: ...,
    }
```

若两处都手写 Result IDs、类型和 schema，会形成两个事实源：

- 新增指标时可能只改一处；
- Flow manifest 与运行结果类型可能不一致；
- Planner 认为 Flow 提供某个结果，但返回对象没有 resolver；
- 返回对象声明了结果，Planner 却找不到 provider；
- schema 漂移需要重复校验代码。

## 推荐模型

Flow 只声明它直接发布的顶层 `ResultRef`：

```python
PERFORMANCE_SUMMARY = ResultRef[PerformanceSummaryResult](
    "backtest.performance_summary",
    schema=PerformanceSummaryResult,
)

PerformanceSummaryFlow(
    inputs=(PERFORMANCE_PATH,),
    outputs=(PERFORMANCE_SUMMARY,),
    operation=MetricSetOperation(...),
)
```

`PerformanceSummaryResult` 是 component Result IDs 的唯一所有者：

```python
class PerformanceSummaryResult(IntermediateResult):
    result_outputs = {
        SHARPE: ResultOutput(
            value_type=float,
            resolve=lambda result: result.sharpe,
        ),
        MAX_DRAWDOWN: ResultOutput(...),
    }
```

Planner 从顶层 ResultRef 的 schema 展开：

```text
PerformanceSummaryFlow
  directly publishes: backtest.performance_summary
  schema provides:
    backtest.sharpe
    backtest.max_drawdown
    backtest.annualized_return
```

因此没有第二份手写 outputs 清单。

## 单结果 Flow

不是所有 Flow 都必须创建 IntermediateResult 类。一个只产生单一稳定事实的 Flow 可以直接：

```python
ResultRef[float]("statistical.bootstrap_sharpe")
```

其 operation 返回标量，Flow outputs 就是该 ResultRef。只有一项计算自然产生多个可复用事实
时，才使用 IntermediateResult。

这样不会为了遵循架构而制造大量一字段 dataclass。

## StateRef 输出

复合 Flow 内部的 Lifecycle Flow 继续直接声明 `StateRef` outputs：

```python
outputs=(CURRENT_POSITION_STATE,)
```

它们不使用 IntermediateResult resolver，因为：

- 允许更新；
- 不进入外层 PublishedResultStore；
- 生命周期由内部 scheduler 管理。

外层 `BacktestLifecycleFlow` 只直接输出：

```python
BACKTEST_RESULT = ResultRef[BacktestResult](...)
```

其 component Result IDs 由 `BacktestResult.result_outputs` 提供。

## Provider 索引

module-local FlowCatalog 建立两层索引：

```text
direct provider:
  backtest.performance_summary
    → PerformanceSummaryFlow

component providers:
  backtest.sharpe
    → PerformanceSummaryFlow
      via PerformanceSummaryResult.result_outputs[SHARPE]
```

component provider 不是另一个 Flow，也不会导致重复执行。多个 component Result IDs 命中同一
Flow 时，Planner 只加入一次。

## 懒解析与原子性

为了不提前物化所有大结果：

1. operation 返回顶层 IntermediateResult；
2. executor 校验顶层类型；
3. 对本计划实际 demand 的 component 调用 resolver 并校验 schema；
4. 顶层结果和已 demand component 一次性发布；
5. 未 demand component 只登记 deferred binding，不运行 resolver；
6. 后续同一 Job 中首次使用时解析并 memoize。

resolver 必须是纯函数。若被 demand 的 resolver 失败，整个 Flow publication 失败，不允许只
发布一半指标。

## 输出清单的规范来源

| 信息 | 唯一所有者 |
|---|---|
| Flow 直接输出哪些顶层 refs | `FlowDefinition.outputs` |
| IntermediateResult 可提供哪些 component Result IDs | `IntermediateResult.result_outputs` |
| component 类型/schema/resolver | 对应 `ResultOutput` |
| Artifact 需要哪些 Result IDs | `ArtifactDefinition` |
| TestModule 允许哪些 Flow | `TestFlowComposition` |

每类事实只有一处声明。

## 推荐

不要让 FlowDefinition 和 IntermediateResult 重复手写同一批 Result IDs。Flow 声明顶层输出，
IntermediateResult 声明 component outputs。

## 待确认

是否接受：

> Flow 只声明直接发布的顶层 `ResultRef`；如果该 Ref 的类型是 IntermediateResult，component
> Result IDs、schema 和 resolver 只由该结果类型声明，FlowCatalog 自动展开 provider
> 索引；单结果 Flow 可以直接输出标量 ResultRef，不强制创建包装类。
