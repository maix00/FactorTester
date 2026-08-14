# Grill 173.29 — Artifact 是终端呈现任务，不是 Result Flow

Status: accepted

## 发现的语义漂移

Grill 173.26 的示意图把 `ArtifactFlow` 与风险指标 Flow 并列，并在
`result_providers` 示例中写了 `backtest.equity_curve_artifact`。

这与已接受的领域语言冲突：

- Result Flow 产生规范化计算事实；
- Renderer 消费 Result 并产生 Presentation Artifact；
- Artifact ID 是用户请求的呈现类型，不是 Result ID；
- 新增或修改 Renderer 不应改变测试计算事实。

因此“Artifact Flow”是错误命名，需要修正。

## 正确计划结构

仍然只需要一个顶层计划执行入口，但计划包含两个不同阶段：

```text
requested Artifact IDs
        ↓
ArtifactDefinitions 展开 Result ID 需求
        ↓
FlowPlan
  ├── mandatory Composite Flow
  └── demand-selected Result Flows
        ↓
PublishedResultStore
        ↓
ArtifactRenderTasks
        ↓
tables / charts / report fragments
```

可以把完整对象称为：

```python
@dataclass(frozen=True)
class TestExecutionPlan:
    flow_plan: FlowPlan
    artifact_plan: ArtifactPlan
```

顶层仍由一个 executor/orchestrator 执行：

```python
TestExecutionExecutor.execute(plan)
```

或者保留已接受的 `FlowPlanExecutor` 名称，由它在 Flow 完成后调用 Renderer Adapter。无论
最终命名如何，Renderer 不是 `FlowDefinition`，也不向 PublishedResultStore 发布 ResultRef。

## ArtifactDefinition 的职责

```python
ArtifactDefinition(
    artifact_id="backtest.equity_curve_chart",
    required_results=("backtest.equity_path",),
    supplemental_results=("backtest.evaluation_split",),
    renderer=EquityCurveRenderer,
)
```

它负责：

- 把用户请求映射成 required/supplemental Result IDs；
- 指定 Renderer；
- 声明 Artifact schema、media type 和输出限制；
- 在 FlowPlan 完成后生成表格、图片或报告片段。

它不负责：

- 提供 Result ID；
- 参与 Result provider 竞争；
- 计算新的研究统计事实；
- 改写 IntermediateResult。

如果 Renderer 为了画图需要新计算，例如滚动 Sharpe 序列，该序列必须先成为
`backtest.rolling_sharpe` Result ID，由 Result Flow 计算；Renderer 只做坐标、样式与文件
输出。

## 为什么仍然可以按需

Renderer 不成为 Flow，不影响 Artifact 驱动计算：

1. 用户请求 Artifact ID；
2. ArtifactDefinition 声明 Result ID 需求；
3. Planner 据此裁剪 Result Flow；
4. Flow 执行完后 Renderer 消费已有结果。

同一 Result Store 可以生成多个 Artifact，不重跑测试。只修改颜色、布局或 Markdown 格式时，
也不需要重新执行 IC 或回测。

## 缓存与持久化

```text
Result cache key:
  frozen RunSpec + Flow/kernel implementation + input identities

Artifact cache key:
  Result refs/hashes + Renderer implementation/config
```

两个 cache identity 分开，避免呈现修改使回测结果缓存失效。Artifact 文件可以按产品存储策略
清理，Result/Evidence 的保存规则另行决定。

## 对既有文档的修正

已把 Grill 173.26 中：

```text
ArtifactFlow
backtest.equity_curve_artifact 作为 result_provider
```

修正为：

```text
ArtifactRenderTask
backtest.equity_curve_chart 作为 ArtifactDefinition
```

`TestFlowComposition` 可包含 `artifact_catalog`，但 Artifact 不进入 `result_providers`。

## 已确认

指标、曲线所需的数值序列和统计事实属于 Result Flow；表格、图像和报告排版属于 Renderer。
它们由一个顶层 Test execution 计划串联，但不能使用同一个 Flow 类型。

已接受：

> Artifact ID 仍驱动 Flow 选择，但 Artifact Renderer 只是统一执行计划末端的
> `ArtifactRenderTask`，不是 Result Flow；所有具有研究语义的统计计算必须先产生 Result
> ID，Renderer 只负责表格、图像和报告呈现，从而允许不重跑测试就重新渲染。
