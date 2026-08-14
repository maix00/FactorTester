# Grill 173.22 — Result DAG 与回测 Flow 的关系

Status: proposed

## 相同之处

用户指出两者几乎一致，这在结构层面成立：

```text
稳定节点标识
声明输入
声明输出
确定性 compute
依赖检查与排序
运行时上下文
```

新的 `ComputationKernel` 和现有 `FlowDefinition` 都属于数据流节点。若完全独立实现节点声明、
依赖索引、环检测和拓扑排序，确实可能重复造轮子。

## 不同之处

### 执行时钟

回测 Flow 绑定：

```text
PRE_REPLAY
PER_EVENT + EventKind
POST_REPLAY
```

PER_EVENT Flow 会随着事件队列，在不同时间戳和事件批次中反复执行。

Result Kernel：

```text
每个 TestModule Job 的结果构建阶段
```

每个选中的 kernel 通常只执行一次。

### 节点选择

回测 Flow 由策略激活、phase、EventKind 和配置决定，并在每个 phase/event group 中按人工
`order`、`before`、`after` 排序及校验。

Result DAG 从 requested Artifact IDs 反向展开 Result IDs，只选择能够提供所需结果的 kernel，
再按 provider 依赖拓扑排序。

### 上下文和副作用

回测 Flow：

- 读取和写入同一个 `BacktestRunState`；
- 通过 `FlowContext` 在同一事件批次传递 FieldRef；
- 可以向 EventQueue 推送新事件；
- 输出会随时间戳不断更新；
- 具有策略和账本 scope。

Result Kernel：

- 读取已经冻结的输入或前序 IntermediateResult；
- 返回新的 IntermediateResult；
- 不推送交易事件；
- 不修改订单、持仓或账本；
- 输出按 Result ID 放进一次运行的 Result Store。

### 结果语义

回测 `FieldRef` 多数是回放过程中的瞬时字段，例如订单尝试、成交、账本估值或当前权益。

Result ID 是测试完成后的可消费研究事实，例如 IC series、IC mean、equity curve 或最大回撤。

## 在未来回测 TestModule 中两者会同时存在

回测迁移到通用结果模块后，不是用 Result DAG 替换事件 Flow：

```text
Backtest event Flow
  -> 订单、成交、持仓、账本回放
  -> BacktestResult
  -> Result Kernel DAG
  -> 回测汇总表、净值曲线、回撤图等 Artifacts
```

前者负责模拟市场与账户状态变化，后者负责从已经完成的 BacktestResult 派生研究结果。

## 是否现在抽取共同基类

可以抽象出最小共同声明：

```text
ComputationDefinition
  node_id
  inputs
  outputs
  compute
```

然后：

```text
FlowDefinition
  = ComputationDefinition
  + phase/event/order/scope/side-effect contract

ResultKernelDefinition
  = ComputationDefinition
  + Result provider/schema/artifact-demand contract
```

但现在立即让既有回测 Flow 继承新的共同基类，会触碰已经稳定的回测框架，违反“先在旧架构外
搭建、当前只迁移 IC”的原则。

推荐本期：

1. 复用设计语义和必要的小型无领域算法；
2. Result DAG 在 `tools/testers/results` 中独立实现；
3. 不修改现有 `FlowDefinition`、scheduler 或 backtest FieldRef；
4. 等第二个 TestModule 接入 Result DAG 后，再审计是否值得提取共同的
   `ComputationDefinition`；
5. 即使以后共享声明，也保持事件 Flow executor 与 Result DAG executor 分离。

## 待确认

是否接受：

> Result Kernel 与回测 Flow 是同一种“声明式计算节点”的两个执行模型；本期不直接复用或
> 重构现有 Flow，而是在外部实现 IC Result DAG；等 IC 验证完成且第二个 TestModule 迁移时，
> 再决定是否只抽取最小的共同节点声明，两个 executor 始终保持分离。
