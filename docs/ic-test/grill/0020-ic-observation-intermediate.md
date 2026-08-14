# Grill 173.21 — IC 观测中间结果

Status: proposed

## 当前实现的问题

当前 IC 路径在 `collect_ic_result()` 中一次返回：

```text
factor_list
ic_series
stats
returns table
factor table
data_present_mask
```

并立即调用 `ic_stats(ic_series)`。随后：

- `_ICComputeResult` 用多层 dict 保存 series 和 stats；
- `_merge_ic_result()` 把部分数据写回 FactorRunResult；
- `_build_ic_response()` 再计算 rolling IC、autocorrelation 和 resample stability；
- coverage mask 只通过 FactorRunResult 间接保留；
- 最小截面样本数没有真正过滤 IC 观测；
- 页面 JSON 结构反过来决定计算顺序。

因此新架构的第一个 IC 中间结果不应是 summary，也不应是页面 response。

## 两个基础 kernel

### ICAlignedInputsKernel

负责：

- 取得因子值；
- 取得指定 forward-return horizon 的收益；
- 按时序和产品对齐；
- 形成实际可参与截面相关的有效 mask；
- 保留每个时间点的候选产品数、有效产品数与缺失信息。

输出整体 Result：

```text
single_factor_ic_aligned_inputs
```

这是运行期中间对象，默认不作为用户 Artifact 持久化。

### ICObservationKernel

依赖：

```text
single_factor_ic_aligned_inputs
```

按 factor、correlation method、forward horizon 和 entry delay 计算逐时点截面 IC，同时应用
`min_cross_section_count`。

输出：

```text
single_factor_ic_observations
single_factor_ic_series
single_factor_ic_valid_cross_section_count
```

它不计算 mean、std、ICIR、t-stat、rolling mean、ACF 或图表。

## ICObservationResult

不同 factor/method/horizon/delay 可能有不同时间索引，初版不强制引入 xarray，也不把缺失时点
填充成一个巨型稠密矩阵。

推荐领域对象：

```python
@dataclass(frozen=True)
class ICObservationKey:
    factor_id: str
    method: str
    forward_horizon: str
    entry_delay_bars: int

@dataclass(frozen=True)
class ICObservationSeries:
    values: pd.Series
    valid_cross_section_count: pd.Series
    candidate_cross_section_count: pd.Series

@dataclass(frozen=True)
class ICObservationResult:
    observations: Mapping[ICObservationKey, ICObservationSeries]

    result_outputs = {
        "single_factor_ic_series":
            lambda result: {
                key: item.values
                for key, item in result.observations.items()
            },
        "single_factor_ic_valid_cross_section_count":
            lambda result: {
                key: item.valid_cross_section_count
                for key, item in result.observations.items()
            },
    }
```

这里的 Mapping 是一个领域集合，不表示按 Result ID 逐项计算。底层 kernel 仍可以对兼容组合做
批量矩阵运算，再把结果组织成带类型的 key。

以后若实测所有维度都适合统一稠密矩阵，可在不改变 Result IDs 的情况下替换内部存储。

## 为什么有效截面数量必须和 IC 序列同时产生

IC 值是否存在以及是否可接受，取决于同一时点实际参与计算的产品数量。因此：

- `min_cross_section_count` 必须在 ICObservationKernel 中执行；
- 被过滤的时点保留候选数和有效数，但 IC 值为缺失；
- summary kernel 只能使用通过最低样本数要求的 IC 观测；
- coverage Artifact 可以复用相同计数，不重新扫描因子/收益矩阵；
- 运行结果可以解释某个 IC 时点为什么缺失。

## 后续 kernel

只有 Artifact 需要时才继续：

```text
ICSummaryStatsKernel
  requires: single_factor_ic_series

ICRollingStatsKernel
  requires: single_factor_ic_series

ICAutocorrelationKernel
  requires: single_factor_ic_series

ICCoverageKernel / Artifact
  requires:
    single_factor_ic_valid_cross_section_count
    single_factor_ic_observations
```

## 待确认

是否接受把新 IC 路径的第一层固定为：

> `ICAlignedInputsKernel -> ICObservationKernel -> ICObservationResult`；结果以带类型 key 的
> observation collection 表达多个 factor/method/horizon/entry-delay 组合，同时保存 IC 序列和
> 有效截面数量；summary、rolling、ACF 和 Artifact 均作为后续按需 kernel。
