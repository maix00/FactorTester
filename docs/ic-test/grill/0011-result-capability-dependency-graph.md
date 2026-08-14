# Grill 173.12 — Result Capability 依赖闭包

Status: rejected in Result ID granularity; superseded by Grill 173.13

## 为什么 Artifact 不应重复声明传递依赖

本文件错误地把 `ic.summary` 当作 Result ID。用户已经明确：Result ID 是
`single_factor_ic_mean`、`single_factor_ic_std`、`single_factor_icir`、
`single_factor_ic_t_stats` 等指标级事实；`single_factor_summary_table` Artifact 直接声明
需要这些 Result IDs。

指标仍可能根据逐时点 IC 序列生成，但不能为了描述实现顺序重新引入 `ic.summary` 粗粒度
Result ID。以下原示例已作废：

```text
ic.summary_table
  -> ic.summary
  -> ic.observations
  -> ...
```

不同 Artifact 会复制并漂移同一计算依赖。Artifact 只应声明它直接消费的 Result IDs；
Result ID 之间的计算依赖由 TestModule 的 Result Capability 图负责。

## TestModule 的 Result Capability

示意：

```python
class ICTestModule(TestModule):
    result_capabilities = (
        ResultCapability(result_id="single_factor_ic_series"),
        ResultCapability(
            result_id="single_factor_ic_mean",
            compute_dependencies=("single_factor_ic_series",),
        ),
    )
```

这描述计算事实的依赖，不描述 UI、Renderer、文件名或保留方式。

只有能够被 Artifact、审计或其他稳定消费者独立引用的事实才应成为 Result ID。纯模块内部的
临时数组、循环变量或优化缓存仍是实现细节，不登记 Result ID。

## 控制面的确定性规划

```text
Artifact IDs
  -> 直接 required / supplemental Result IDs
  -> 查询 TestModule Result Capability
  -> 计算 Result ID 传递依赖闭包
  -> 校验无环、全部受支持
  -> 生成有序内部 ResultPlan
```

修正后的 Artifact 直接请求指标级结果：

```text
single_factor_summary_table
  -> single_factor_ic_mean
  -> single_factor_ic_std
  -> single_factor_icir
  -> single_factor_ic_t_stats
```

内部计划为：

```text
compute:
  1. single_factor_ic_series
  2. single_factor_ic_mean
  3. single_factor_ic_std
  4. single_factor_icir
  5. single_factor_ic_t_stats

export:
  - single_factor_ic_mean
  - single_factor_ic_std
  - single_factor_icir
  - single_factor_ic_t_stats
```

因此要区分：

- `compute_result_ids`：为了产生目标事实必须执行的完整闭包；
- `export_result_ids`：Artifact 直接请求、需要进入 TestResultExport 的组件。

依赖组件不自动导出或长期保留。若另一个 Artifact 同时请求 `ic.observations`，它才进入
export 集合。

## Required 与 Supplemental 的传播

- required Result ID 的全部依赖都是 required compute；
- supplemental Result ID 的依赖属于 supplemental compute，除非同一依赖也被 required
  路径使用；
- required 路径失败会阻止对应 Artifact；
- 仅 supplemental 路径失败按 Grill 173.11 记录 omission，不阻塞 required Artifact。

## 启动校验

控制面建立 Registry 时应确定性校验：

1. 同一 TestModule 内 Result ID 唯一；
2. depends_on 指向本模块已登记的 Result ID；
3. 依赖图无环；
4. 每个 Artifact 的 Result ID 均由其关联 TestModule 支持；
5. Artifact required 与 supplemental 列表没有无意义重复。

## 与当前 IC 代码的关系

当前 `_ICComputeResult` 已经先保存逐时点 series，再从这些 series 构造 stats、rolling IC、
autocorrelation 和 response。这说明 IC 内部实际已有依赖顺序，只是目前埋在一个手工 response
builder 中，没有形成可校验的 Result Capability 图。

## 后续

指标级 Result ID 的维度与内部计算依赖由 Grill 173.13 重新决定。
