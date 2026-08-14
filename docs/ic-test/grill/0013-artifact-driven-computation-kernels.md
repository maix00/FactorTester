# Grill 173.14 — Artifact 需求、共享计算 Kernel 与 ICComputationResult

Status: partially accepted; generalized by Grill 173.15

## 用户修正

指标级 Result ID 已对齐，但不能据此让 ICResult 先按 Result ID 逐项计算和填充。

正确方向是：

1. 用户请求一个或多个 Artifact IDs；
2. Artifact 定义列出直接需要的指标级 Result IDs；
3. 组织层合并所有 Artifact 的需求；
4. IC 模块把多个 Result IDs 归并到共享计算 kernel；
5. 一个 kernel 可以通过一次矩阵运算同时产生多个指标；
6. IC TestModule 返回与 Artifact 无关的中间计算结果；
7. Result Resolver 再把该结果投影为 Result ID 对应的值；
8. Renderer 使用这些值组织 Artifact。

## Artifact 不拥有统计计算实现

Artifact 决定“需要什么”和“如何呈现”，但不应各自实现 IC mean、std、ICIR 或 t-stat 的
统计算法。否则同一个 `single_factor_ic_mean` 可能在不同 Artifact 中出现不同实现。

推荐边界：

```text
ArtifactDefinition
  -> required/supplemental Result IDs
  -> renderer 与输出组织

ICTestModule
  -> Result ID 到 computation kernel 的映射
  -> IC 统计语义和算法
```

因此 Artifact 驱动是否需要进行某项计算，但计算方法仍由 TestModule 统一拥有。

## 两层规划

### 通用 Artifact Planner

```text
requested Artifact IDs
  -> 合并 required Result IDs
  -> 合并 supplemental Result IDs
  -> 去重
```

它不理解 IC 的矩阵算法。

### TestModule Computation Planner

```text
desired Result IDs
  -> 映射到 IC computation kernels
  -> 合并相同 kernel
  -> 计算 kernel 依赖顺序
  -> 生成 ICComputationPlan
```

只有 ICTestModule 知道哪些指标可以一次计算。

## 示例

用户请求：

```text
single_factor_summary_table
single_factor_ic_distribution_chart
```

Artifact 需求合并为：

```text
single_factor_ic_mean
single_factor_ic_std
single_factor_icir
single_factor_ic_t_stats
single_factor_ic_series
```

ICTestModule 可以规划：

```text
kernel: single_factor_ic_series_matrix
  produces internal IC series matrix

kernel: single_factor_ic_summary_stats_matrix
  consumes IC series matrix
  jointly makes available:
    single_factor_ic_mean
    single_factor_ic_std
    single_factor_icir
    single_factor_ic_t_stats
```

不是调用四次：

```text
calculate_mean()
calculate_std()
calculate_icir()
calculate_t_stats()
```

而是对 factor × method × horizon × lag × group/window 维度的矩阵做一次或少量共享运算。

## TestModule 返回什么

推荐返回：

```python
ICComputationResult(
    identity=...,
    dimensions=...,
    ic_series_matrix=...,
    summary_stats_matrix=...,
    coverage_matrix=...,
    executed_kernel_ids=...,
)
```

名称中的 “ComputationResult” 表明：

- 它是 IC TestModule 的最终计算返回值；
- 它是 Artifact/Renderer 的上游中间结果；
- 它不按页面布局组织；
- 它可以只包含本次 ICComputationPlan 实际执行的 kernel 输出；
- 它不要求把每个 Result ID 复制成一个独立对象。

从 TestModule 边界看它是 result；从 Artifact 管线看它是 intermediate。

## Result Resolver

Result ID 通过轻量 resolver 从 `ICComputationResult` 中取得：

```text
single_factor_ic_mean
  -> summary_stats_matrix["mean"]

single_factor_ic_std
  -> summary_stats_matrix["std"]

single_factor_icir
  -> summary_stats_matrix["IR"]

single_factor_ic_t_stats
  -> summary_stats_matrix["t_stat"]
```

Resolver 不重新做重型计算，只做已计算矩阵的选择、命名、schema 检查和必要的零拷贝视图。

## 与当前代码的关系

当前实现已经有两个雏形：

- `_ICComputeResult` 保存多 horizon、lag、method、factor 的 series 和 stats；
- `ic_stats()` 一次计算 mean、std、IR、t_stat、max、min、AC1 和半衰期等多个统计量。

问题不在于缺少共享计算，而在于：

- `_ICComputeResult` 是私有可变容器，没有稳定 identity/schema；
- `_build_ic_response()` 同时负责 Result 选择、JSON 拼装和展示兼容；
- 当前 Artifact 请求没有参与 IC computation plan；
- Result ID 尚未映射到 kernel 输出。

## 对 compute/export 关系的修正

内部计划不应只是 Result ID 的逐项拓扑排序，而应表达：

```text
ArtifactPlan
  -> desired Result IDs

ICComputationPlan
  -> required shared kernels

ICComputationResult
  -> kernel outputs

Result Resolver
  -> Result ID values

Renderer
  -> Artifacts
```

## 待确认

本提案中以下部分已接受：

- Artifact ID 驱动所需 Result IDs；
- Result ID 是稳定的细粒度消费契约；
- 共享矩阵计算不能退化为逐指标重复计算；
- Artifact 可以使用 Result Resolver 取得指标。

以下部分需要修正：

- 中间计算不只由 ICTestModule 内部的固定 planner 管理，而应建模为可依赖其他 Result ID
  的确定性中间计算模块；
- 中间结果可以提供一个或多个 Result ID；
- IC 序列自身就是一个中间结果；
- 中间结果也可以作为 Artifact 的整体输入；
- Result Resolver 应属于中间结果的稳定输出契约，而不只是统一从一个大型
  `ICComputationResult` 取字段。

修正后的模型见 `0014-intermediate-result-dataflow-dag.md`。
