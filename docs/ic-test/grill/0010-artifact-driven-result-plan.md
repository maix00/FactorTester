# Grill 173.11 — Artifact 驱动内部 ResultPlan

Status: accepted

## 用户可见请求

用户、UI 和公开 CLI 只声明需要的逻辑 Artifact ID，例如：

```text
single_factor_summary_table
single_factor_ic_series_chart
single_factor_ic_coverage_table
backtest.equity_curve
```

用户不能直接声明内部 Result ID。Result ID 是 TestModule 与 Artifact Renderer 之间的计算
契约，不是面向用户的产品接口。

这里的 Artifact ID 是逻辑产物类型，不等于最终文件名。一次 artifact instance 可以生成
SVG、JSON data 和 receipt 等多个物理文件。

## Artifact 定义

每种 Artifact 由服务器登记定义：

```python
ArtifactDefinition(
    artifact_id="single_factor_summary_table",
    renderer_id="single_factor_summary_table@1",
    required_result_ids=(
        "single_factor_ic_mean",
        "single_factor_ic_std",
        "single_factor_icir",
        "single_factor_ic_t_stats",
    ),
    supplemental_result_ids=(
        "single_factor_ic_valid_count",
    ),
)
```

### `required_result_ids`

生成该 Artifact 必须存在的计算事实。缺少任何一项时：

- 运行前规划应拒绝不支持的请求；
- 运行中计算失败则该 Artifact 不能声称生成成功；
- 运行后若没有保留所需 component，不能只靠 Renderer 补造。

### `supplemental_result_ids`

用于增强 Artifact 内容、解释或审计，但不是渲染最小核心所必需的计算事实。规划器总是尝试
计算；失败时记录 omission，但不阻塞 required Artifact，也不单独导致 Job 失败。

不能使用模糊的“附加字段”自由 JSON；每项仍必须是 TestModule 登记过的 Result ID。

## 规划流程

```text
用户请求 Artifact IDs
  -> Artifact Registry 解析每个定义
  -> 合并 required Result IDs
  -> 合并 supplemental Result IDs
  -> 对照 TestModule result capabilities
  -> 计算依赖闭包
  -> 生成内部 ResultPlan
  -> 冻结进 ExecutionPlan
  -> TestModule 按 ResultPlan 计算
  -> TestResult / Result Components
  -> Renderer 生成请求的 Artifacts
```

内部 `ResultPlan` 可表达：

```json
{
  "required": [
    "single_factor_ic_mean",
    "single_factor_ic_std",
    "single_factor_icir",
    "single_factor_ic_t_stats"
  ],
  "supplemental": [
    "single_factor_ic_valid_count"
  ],
  "requested_artifacts": [
    "single_factor_summary_table"
  ]
}
```

它由程序生成，用户不能手写或覆盖。

## 多个 Artifact 的合并

一次 Job 请求多个 Artifact 时，规划器对 Result ID 去重并计算一次：

```text
single_factor_summary_table
  -> single_factor_ic_mean
  -> single_factor_ic_std
  -> single_factor_icir
  -> single_factor_ic_t_stats

single_factor_ic_series_chart
  -> single_factor_ic_series

single_factor_ic_coverage_table
  -> single_factor_ic_valid_count
  -> single_factor_ic_missing_ratio
```

同一个 TestModule 执行一次，产生相应 components；三个 Renderer 再分别消费。这避免为了三种
展示重复运行 IC。

## 与当前实现的关系

当前 `output_requests` 已经接近 Artifact ID：

- 用户请求 `equity_curve`、`fee_detail` 等逻辑输出；
- `OUTPUT_DEFINITIONS.requires` 声明需要 `result`、`group_execution`、`order_audit`；
- sink 根据 request 生成 SVG、JSON 和 receipt。

当前问题是：

- `requires` 指向存储 artifact name，而不是领域 Result ID；
- 所有定义集中在 backtest report outputs；
- sink 同时解释领域结果、保留策略和 Renderer；
- IC 等 TestModule 没有自己的 result capability。

重构应保留“用户请求 Artifact”的产品语义，把依赖从物理存储名提升为领域 Result ID。

## 运行后新增 Artifact

运行后请求新 Artifact 时：

- 若 required Result Components 已持久化，可直接调用 Renderer；
- 若未持久化，不能伪造或从摘要猜测；
- 是否允许创建一个新 Job 重新计算缺失 Result Components，后续另行 Grill。

## 已接受方向

1. 用户、UI 和公开 CLI 只能请求 Artifact ID；
2. Artifact 定义声明依赖的 Result IDs；
3. 控制面生成内部 ResultPlan；
4. TestModule 按 ResultPlan 计算；
5. 用户不能直接提交或覆盖 Result IDs；
6. 多个 Artifact 的 Result ID 依赖合并去重后只计算一次。

## Supplemental Result ID 的已接受语义

规划器总是尝试计算 supplemental Result IDs；成功则增强 Artifact，失败或不支持时记录明确
omission，但只要所有 required Result IDs 成功，Artifact 仍可生成且 Job 不因此失败。
