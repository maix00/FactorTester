# Grill 173.13 — 指标级 Result ID

Status: metric granularity accepted; per-Result-ID computation model rejected by Grill 173.14

## 修正后的定义

Result ID 标识 TestModule 产生的一项独立、稳定计算事实，而不是粗粒度结果分区。

IC 示例：

```text
single_factor_ic_series
single_factor_ic_mean
single_factor_ic_std
single_factor_icir
single_factor_ic_t_stats
single_factor_ic_max
single_factor_ic_min
single_factor_ic_ac1
single_factor_ic_series_acf_half_life
single_factor_ic_valid_count
single_factor_ic_missing_ratio
```

最终清单必须在 IC 功能逐项 Grill 后确定；本文件只确定粒度原则。

## Artifact 直接声明指标依赖

```python
ArtifactDefinition(
    artifact_id="single_factor_summary_table",
    required_result_ids=(
        "single_factor_ic_mean",
        "single_factor_ic_std",
        "single_factor_icir",
        "single_factor_ic_t_stats",
    ),
    supplemental_result_ids=(
        "single_factor_ic_valid_count",
        "single_factor_ic_missing_ratio",
    ),
)
```

不再引入 `ic.summary` 作为中间 Result ID。`single_factor_summary_table` Renderer 直接取得上述
各项指标并组成列。

## 原领域结果示例的修正

本文件原来把 `ICResult` 画成预先按 Result ID 填充的 dict，容易暗示 TestModule 会逐个
Result ID 计算。该模型不接受。

修正为：Artifact IDs 先形成统一需求，IC 模块再把多个 Result IDs 组织成少量共享
computation kernels；一次 kernel 可以通过矩阵运算产生多个指标。TestModule 返回
`ICComputationResult`，Result Resolver 再从中取得指标级 Result Values。详见 Grill 173.14。

## 计算依赖仍可存在（由 kernel 组织）

这些指标通常来自同一条 IC series：

```text
single_factor_ic_series
  -> single_factor_ic_mean
  -> single_factor_ic_std
  -> single_factor_icir
  -> single_factor_ic_t_stats
```

Artifact 只列自己直接需要的指标。TestModule 把这些指标映射到共享 computation kernel，
不能把每个 Result ID 当成一次独立函数调用。

## 当前代码映射

当前 `ic_stats()` 已分别计算：

- `mean`；
- `std`；
- `IR`；
- `t_stat`；
- `max`；
- `min`；
- `ac1`；
- `ic_series_acf_half_life`；
- `acf_vals`。

现在它们被放在一个 pandas Series 中，再由 `_build_ic_response()` 手工拼表。新模型应把这些
稳定统计事实分别映射到 Result ID；是否对外生成 Artifact 则由 ArtifactDefinition 决定。

## Result ID 与维度

同一个指标会在多个维度上出现：

- factor；
- IC method（Rank/Pearson）；
- forward return horizon；
- entry delay / lag；
- product group；
- sample window。

推荐 Result ID 只标识“指标是什么”，这些变化作为结果值的显式维度，而不是产生大量 ID：

```text
single_factor_ic_mean
```

对应结果可以是：

```text
factor × method × horizon × lag × product_group × sample_window -> value
```

否则若把每个维度编码进 ID，会形成 `single_factor_rank_ic_mean_5d_lag1_...` 等不可维护目录。

## 下一项待确认

是否接受：Result ID 保持指标级稳定名称，例如 `single_factor_ic_mean`；Factor、Rank/Pearson、
forward horizon、lag、产品组和样本窗口作为该 Result 的结构化维度，不编码进 Result ID？
