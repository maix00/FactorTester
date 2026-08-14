# Grill 173.10 — 多个 Result Component 的导出

Status: superseded in request semantics by Grill 173.11

## 术语修正

一个 TestModule 执行产生一个领域 `ICComputationResult`。多个 Result ID 对应的是 resolver
从共享计算矩阵中取得的多个 **Result Values**，不是多个完整 TestResult 再嵌套进另一个
TestResult。

例如：

```python
ICComputationResult(
    dimensions=...,
    ic_series_matrix=...,
    summary_stats_matrix=...,
)
```

对应：

```text
single_factor_ic_mean    -> summary_stats_matrix["mean"]
single_factor_ic_std     -> summary_stats_matrix["std"]
single_factor_icir       -> summary_stats_matrix["IR"]
single_factor_ic_t_stats -> summary_stats_matrix["t_stat"]
```

这些 Result Values 可以是矩阵视图、Series、数组或专门值对象，不要求为每项重跑计算。

## 导出选择（已修正）

本文件原提案允许用户在 JobSpec 直接请求一个或多个 Result ID：

```json
{
  "requested_result_ids": [
    "single_factor_ic_mean",
    "single_factor_ic_std",
    "single_factor_icir"
  ]
}
```

该公开请求方式不接受。用户只请求 Artifact ID；控制面根据 Artifact 定义生成内部
ResultPlan。TestModule 仍只执行一次并返回一个 `ICComputationResult`，resolver 再按内部
ArtifactPlan 从共享 kernel 输出中取得 Result Values。

## 导出 envelope

一份导出可以包含多个 component：

```json
{
  "test_kind": "ic",
  "components": {
    "single_factor_ic_mean": {
      "storage": "inline",
      "value": {}
    },
    "single_factor_ic_std": {
      "storage": "inline",
      "value": {}
    },
    "single_factor_icir": {
      "storage": "artifact",
      "artifact_ref": "artifact:...",
      "content_hash": "sha256:..."
    }
  }
}
```

这只是示意结构，schema 与 identity 字段后续再定。本轮只确定：

- 小型 component 可以内联；
- 大型 component 保存为 artifact，envelope 只保留引用、hash 和必要摘要；
- 未被内部 ResultPlan 选中且不是强制保留的 component 不进入导出；
- 同一领域 TestResult 可以按不同请求产生不同导出；
- 导出选择不要求重跑 TestModule；
- `TestResultExport` 是传输/持久化投影，不是第二个领域 TestResult。

## 与当前 sink 的关系

当前 `_WorkerSink.emit_result(data)` 接受一个自由 dict，再统一压缩成 summary，并按
`output_requests` 生成回测图表。这会把领域结果、保留策略和 renderer 混在一起。

目标流程应为：

```text
领域 ComputationResult
  -> 按内部 ArtifactPlan 解析 Result Values
  -> TestResultExport
  -> sink 决定 inline / artifact 持久化
  -> Renderer 另行消费已保留 components
```

sink 不解释 IC 或回测字段；TestModule/结果 adapter 不决定文件路径和数据库写入。

## 保留结论

同一次测试的多个 Result ID 可以由共享 computation result 解析，并出现在同一份
`TestResultExport` 中；小值内联、大值使用 artifact 引用；该 export 是领域 computation
result 的传输/持久化投影，不是新的领域结果。选择哪些 Result ID 的权威输入由 Artifact
驱动。
