# Grill 173.20 — Artifact 请求与冻结执行合同

Status: accepted

## 当前问题

用户只请求 Artifact IDs，Artifact 再决定所需 Result IDs 和 kernels。因此 Artifact 请求会改变
实际计算计划，不能只作为 UI 展示偏好。

但 Artifact 请求也不是领域测试参数：

- IC method、forward horizon、lag、样本区间属于 RunSpec；
- 汇总表、IC 序列图、coverage 表属于 Artifact 请求。

把 Artifact IDs 塞进 RunSpec 会混淆“研究计算语义”和“本次要求交付什么输出”。

## 推荐对象边界

不新增独立数据库对象。JobSpec 中保存：

```text
TestExecutionRequest
  frozen_run_spec
  requested_artifact_ids
  test_module_id
```

三者共同参与 JobSpec/执行合同 hash，但 RunSpec hash 只描述领域运行配置。

Planning Worker 生成：

```text
TestExecutionPlan
  input_plan
  result_plan:
    requested Artifact IDs
    required Result IDs
    supplemental Result IDs
    kernel IDs
    dependency order
```

这能同时保证：

- 运行前知道将计算和输出什么；
- Artifact 改变时执行合同会改变；
- 同一个领域 RunSpec 可以请求不同 Artifact 组合；
- 不需要创建 ArtifactRequest 数据表。

## 与当前 output_requests 的关系

当前 `output_requests` 已经位于 JobSpec，而不是 RunSpec，这个边界方向正确。但现有实现只支持
回测报告，并由 `_WorkerSink.emit_result()` 在领域计算完成后：

```text
读取完整 dict result
  -> build_report_artifacts()
  -> 生成图表/CSV/JSON
```

它的问题是：

- Artifact 请求没有参与 TestModule computation plan；
- worker sink 理解 equity curve 等回测领域输出；
- IC 没有接入同一契约；
- `OUTPUT_DEFINITIONS` 把用户请求、source artifact 和最终文件混在一起；
- 默认无请求时隐式生成 equity curve，是回测专属行为。

新 IC 路径不应把 Artifact 生成继续放在 `_WorkerSink.emit_result()`。`TestRuntime` 提供通用
artifact sink，但：

```text
ICTestModule / shared Result pipeline
  决定计算和渲染什么

artifact sink
  只负责写入、配额、hash、content type 和回传引用
```

## 运行后新增 Artifact

如果运行完成后用户再请求另一个 Artifact：

1. 所需 Result IDs 已按 retention policy 持久化：
   - 可直接创建新的 render Job；
   - 不重复 IC 计算。
2. 只保留了摘要，缺少必要 Result：
   - 不能假装可以生成；
   - 需要用相同 RunSpec 创建新的 TestExecutionRequest；
   - planner 只加入缺失 kernels，但数据是否可复用由 cache/retention 决定。

这不改变原 Job 的冻结执行合同；新 Artifact 有自己的生成记录。

## 已确认

> `requested_artifact_ids` 留在 JobSpec/TestExecutionRequest，与 RunSpec 一起冻结并参与执行合同
> hash，但不进入领域 RunSpec；TestModule 在 planning 阶段据此生成 Result DAG；artifact sink
> 只负责存储和回传，不再理解 IC 或回测领域输出。
