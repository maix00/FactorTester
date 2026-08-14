# Grill 173.23 — Result Flow 命名与回测 Flow 复用边界

Status: naming direction retained; direct reuse under deeper audit in Grill 173.24

## 用户提出的简化

IC 结果计算可以理解为只有一个执行阶段：

```text
RESULT_COMPUTATION
```

此前所称 `ComputationKernel` 与 Flow 节点一一对应，因此可以：

- 命名上向回测 Flow 靠齐；
- 令 kernel 等同于 flow；
- 评估是否直接引用既有 Flow 基础设施。

## 命名上可以收敛

建议取消两套名字：

```text
ComputationKernel / kernel_id
```

改为：

```text
ResultFlow / flow_id
```

一个 ResultFlow：

```text
requires Result IDs
provides Result IDs
compute(inputs, runtime) -> IntermediateResult
```

它可以提供一个或多个 Result IDs。此前的 `kernel_id` 就是 `flow_id`，不再同时存在两种标识。

“kernel”只保留为实现细节用语，例如一个 ResultFlow 内部调用 NumPy、pandas 或编译后的矩阵
kernel；它不再是编排层对象。

## IC 是否需要声明一个 phase

从整个 TestModule/Job 看，IC 的确只有一个结果计算阶段：

```text
TestModule execution
  -> Result Flow graph
  -> Artifact rendering
```

但在 ResultFlowDefinition 上重复写：

```text
phase=RESULT_COMPUTATION
```

没有区分能力，只会产生恒定字段。初版可以由 ResultFlowExecutor 的类型表达这个阶段，不在每个
Flow 上声明 phase。

若以后真的出现不同执行语义的阶段，再新增绑定对象，而不是现在预留虚假的 phase。

## 为什么不能直接引用 native backtest Flow

当前 `tools/testers/backtest/engines/native/flow.py` 的 `FlowDefinition` 强制包含：

- `FieldRef` inputs/outputs；
- `Callable[..., None]`，通过可变 FlowContext 写输出；
- `Phase`；
- `EventKind`；
- `order`、`before`、`after`；
- strategy scope；
- input materialization；
- event payload inputs。

其 executor 还会：

- 在每个事件批次构造 FlowContext；
- 修改 BacktestRunState；
- 推送 EventDraft；
- 按策略和账本 scope 重复执行；
- 审计事件字段读写。

若 IC 直接引用它，只能：

- 假装 Result ID 是 backtest FieldRef；
- 给所有节点填同一个假 phase；
- 使用不会需要的 EventQueue/Strategy/Ledger 语义；
- 让 `compute()` 通过可变 context 写结果而不是返回 IntermediateResult；
- 让通用 TestModule 结果层反向依赖 native backtest engine。

这不是复用，而是让 IC 伪装成回测。

## 当前直接抽取既有 FlowDefinition 的风险

现有回测目录约有数十个 Flow/FlowDefinition 声明，并通过 `ExecutableModule.__init_subclass__`
自动填 owner。现在移动或重构共同基类会同时改变：

- 回测模块声明；
- scheduler resolve/sort/contract audit；
- FieldRef owner 绑定；
- 大量回测测试。

这会把“IC 测试加强”变成“回测 Flow 基础设施迁移”，违背当前 branch 的范围。

## 推荐边界

本期：

```text
tools/testers/results/
  ResultFlowDefinition
  ResultFlowPlan
  ResultFlowExecutor
```

```text
tools/testers/backtest/engines/native/
  FlowDefinition
  FlowBinding
  scheduler
```

两者名称和声明风格靠齐，但不互相 import。

以后若第二个 TestModule 证明共同抽象稳定，可以提取：

```text
DeclarativeFlowDefinition
  flow_id
  inputs
  outputs
  compute
```

再由两者组合扩展；不是现在让任意一方继承另一方。

## 对 Grill 173.21 的命名修正

若本提案接受：

```text
ICAlignedInputsKernel
ICObservationKernel
ICSummaryStatsKernel
```

统一改为：

```text
ICAlignedInputsFlow
ICObservationFlow
ICSummaryStatsFlow
```

其计算和依赖语义不变。

## 待确认

是否接受：

> 编排层统一使用 `ResultFlow/flow_id`，删除 `ComputationKernel/kernel_id` 概念；IC 的所有
> ResultFlow 隐含运行在一个 result-computation stage，不重复声明 phase；本期只让 API 风格
> 与回测 Flow 靠齐，不直接 import 或重构 native backtest Flow。

对 `FlowBase`、typed port 和直接复用的进一步审计见
`0023-shared-flow-declaration-audit.md`。
