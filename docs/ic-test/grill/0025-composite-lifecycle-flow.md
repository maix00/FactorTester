# Grill 173.26 — 将回测生命周期作为统一计划中的复合 Flow

Status: accepted

## 已接受的前提

以下语义沿用 Grill 173.25：

- `FlowRef[T]` 是共同端口基类；
- `StateRef[T]` 表达可变运行状态；
- `ResultRef[T]` 表达 write-once 结果事实；
- 回测完成后的收益、风险指标、最终投影和 Artifact 与 IC 共用 Result Flow；
- 回测事件循环内部仍需要 phase、event kind、order 和可变状态。

本轮修正的是执行器层级。Lifecycle 和 Result 不再作为两个并列的顶层 executor；它们参与
同一个外层 Flow 计划。

## 统一后的两层结构

```text
FlowPlanExecutor                         ← 唯一顶层执行器
├── Atomic Result Flow
│   ├── IC observation/statistics
│   └── 回测收益、风险指标、图表所需序列
└── Composite Flow
    └── BacktestLifecycleFlow
        ├── PRE_REPLAY
        ├── PER_EVENT event loop
        ├── mutable POST_REPLAY finalizers
        └── Freeze BacktestResult
```

`BacktestLifecycleFlow` 对外是一个普通 Flow provider：

```python
BacktestLifecycleFlow(
    inputs=(
        FROZEN_RUN_SPEC,
        FACTOR_DEFINITIONS,
        DATA_BINDINGS,
        STRATEGY_DEFINITIONS,
    ),
    outputs=(BACKTEST_RESULT,),
    operation=BacktestLifecycleOperation(...),
)
```

它对内才使用当前 native scheduler、FlowContext、EventQueue 和 `StateRef`。外层
`FlowPlanExecutor` 不理解事件循环，也不为每根 bar 调度一次该节点；它只调用一次复合
operation，并接收一次原子发布的 `BACKTEST_RESULT`。

因此实现了执行器融合，同时没有把事件循环错误展开成普通 Result DAG。

## 共同 Operation Interface

顶层只需要一个小 Interface：

```python
class FlowOperation(Protocol):
    def execute(
        self,
        inputs: FlowInputs,
        runtime: FlowRuntime,
    ) -> OutputBundle: ...
```

两类 Implementation：

```text
KernelOperation
    直接计算一个或多个 ResultRef

CompositeFlowOperation
    内部运行自己的子图/状态机，最终返回 ResultRef
```

`BacktestLifecycleOperation` 是 `CompositeFlowOperation`。当前 native scheduler 变成它的内部
Implementation，而不是与 `FlowPlanExecutor` 并列的公共执行器。

## 固定 Flow 组合

每种 TestModule 必须声明一个版本化、确定性的 `TestFlowComposition`：

```python
@dataclass(frozen=True)
class TestFlowComposition:
    composition_id: CompositionID
    mandatory_flows: tuple[FlowID, ...]
    result_providers: tuple[FlowID, ...]
    artifact_catalog: tuple[ArtifactDefinition, ...]
```

回测的组合定义：

```text
mandatory_flows:
  - backtest.lifecycle

result_providers:
  - backtest.return_path
  - backtest.risk_metrics
  - backtest.portfolio_projection
  - backtest.equity_path
```

IC 的组合定义不需要 Lifecycle：

```text
mandatory_flows:
  - single_factor.ic_observation

result_providers:
  - single_factor.ic_summary
  - single_factor.ic_rolling
  - single_factor.ic_acf
```

这里的“必选”是测试执行语义，不是所有 UI 预览都必须运行。例如 RunSpec preview 不启动
回测；一旦 Job 进入 backtest execution，`backtest.lifecycle` 必须出现在计划中。

## 为什么生命周期必然在指标之前

不能仅设置数字顺序：

```text
backtest.lifecycle order=0
risk.metrics order=100
```

这种排序没有表达数据因果，未来插入 Flow 时容易绕过。

正确结构是：

```text
BacktestLifecycleFlow
        │ publishes
        ▼
BACKTEST_RESULT
        │ required by
        ▼
ReturnPath / RiskMetrics / PortfolioProjection
        │
        ▼
Artifacts
```

Planner 执行固定组合：

1. 放入 TestModule 声明的 `mandatory_flows`；
2. 从用户请求的 Artifact IDs 反向展开 Result providers；
3. 合并共享 intermediate computations；
4. 验证回测所有结果路径都依赖 `BACKTEST_RESULT`；
5. 做唯一 provider、missing seed 和 cycle 检查；
6. 对完整计划做一次拓扑排序。

因此 `BacktestLifecycleFlow` 是外部冻结输入之后的必选根节点；依赖它的指标只能排在其后。
如果日后某些不可变数据准备也被提取成外层 Flow，它们可以作为生命周期 Flow 的输入 provider
自然排在前面，而不破坏“生命周期先于回测结果推导”的语义。

这里“在最前”已确认采用以下精确定义：

> `BacktestLifecycleFlow` 必须先于所有回测指标与 Artifact 推导；它自身所需的外部输入
> provider 可以排在它之前。

## Freeze 属于复合 Flow 的输出提交

Grill 173.25 把 Freeze 描述成两个顶层 executor 之间的 bridge。新结构中，它成为
`BacktestLifecycleFlow` 的最后一步和输出提交边界：

```text
内部 mutable state
→ 完成所有会改变可报告事实的 finalizer
→ 构造 BacktestResult
→ 校验完整 outputs
→ 返回 OutputBundle
→ 外层原子 publish BACKTEST_RESULT
```

外层计划不暴露中间 `BacktestRunState`，其他 Flow 也不能读它。这缩小了 Interface，并防止
指标 Flow 绕过 Freeze 读取 mutable store。

## 排序的两个层级

统一顶层执行并不意味着只剩一种排序：

### 外层计划排序

- 对 Flow/Composite Flow 做 ResultRef 依赖拓扑排序；
- 负责按需裁剪、共享计算、取消、progress、receipt 和原子发布；
- `BacktestLifecycleFlow` 在这一层只出现一次。

### 复合 Flow 内部排序

- 继续按 PRE_REPLAY → PER_EVENT → POST_REPLAY；
- 每个 phase 内使用现有 event kind、order、after、before；
- 负责事件因果、账本副作用和策略生命周期。

这是同一个 Flow 的嵌套执行，而不是两个相互独立的 Job executor。

## 选择多个回测引擎

如果 RunSpec 可选择 native、backtrader 或其他引擎，固定组合不应注册多个同时可用的
`BACKTEST_RESULT` provider。TestModule 在 plan 阶段先选择一个 Implementation：

```text
backtest.lifecycle
  ├── NativeBacktestLifecycleOperation
  ├── BacktraderLifecycleOperation
  └── ...
```

Flow ID 与输出契约稳定，operation 根据已冻结 engine selection 绑定。Planner 看到的始终是
唯一 provider，不能把运行时引擎选择伪装成多个竞争 Flow。

## 性能边界

该融合不会增加每根 bar 的外层函数调度：

- 外层只调用一次 `BacktestLifecycleOperation.execute()`；
- 内层继续使用现有 scheduler；
- 大曲线只在 Freeze 时转移一次所有权；
- 指标 kernel 共享一次冻结的 `BACKTEST_RESULT`；
- 多指标 operation 可一次扫描发布多个 ResultRef；
- Artifact 未请求的昂贵指标不进入计划。

额外成本仅是一次复合 Flow 的输入/output validation 和 receipt，换来统一的选择、排序与审计。

## 迁移修正

1. 先建立新的 `FlowPlanExecutor`、`FlowOperation` 和 `TestFlowComposition`。
2. IC 以 atomic Result Flows 接入统一执行器。
3. 用 `BacktestLifecycleOperation` 包裹现有 native scheduler，不改内部事件 Flow。
4. 输出 `BACKTEST_RESULT`，以新旧结果 golden parity 验证 Freeze。
5. risk metrics 和最终投影逐项移到外层 atomic Result Flow。
6. 在全部结果一致前，生产 backtest 仍走旧入口；旁路完成后一次切换 worker dispatch。
7. 未来其他 TestModule 逐个声明自己的固定组合，不要求存在 Lifecycle composite。

## 验收

- backtest execution plan 缺少 `backtest.lifecycle` 时必须拒绝；
- RunSpec preview、protocol inspect 等非执行操作不会误启动 Lifecycle；
- `backtest.lifecycle` 在外层计划中只执行一次；
- 所有回测指标 Result Flow 都直接或间接依赖 `BACKTEST_RESULT`；
- 外层任何 Flow 都无法取得 `BacktestRunState`；
- native 内部 phase/event 顺序与既有 manifest 完全一致；
- 外层取消会传播到 composite runtime 和 event queue；
- composite 失败时不得发布部分 `BACKTEST_RESULT`；
- 同一 frozen RunSpec 选择且只选择一个 lifecycle engine implementation；
- 指标新旧路径保持数值和 schema parity；
- progress 能展示“回测生命周期”以及内部阶段，但审计记录不把每根 bar 变成顶层 Flow。

## 已确认

已接受：

> 每个 TestModule 使用固定 `TestFlowComposition`；顶层只保留一个
> `FlowPlanExecutor`；`BacktestLifecycleFlow` 是统一计划中的必选复合 Flow，内部运行现有
> phase/event scheduler，并以 `BACKTEST_RESULT` 为唯一外部输出；回测指标和 Artifact
> 所需的 Result Flow 通过该结果依赖自然排在其后，而不是用全局数字 order 强制排序。
