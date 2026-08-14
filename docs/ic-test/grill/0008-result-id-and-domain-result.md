# Grill 173.9 — Result ID 与领域 TestResult 的关系

Status: accepted

## 当前存在的三个不同命名空间

### `output_requests`

当前 `equity_curve`、`fee_detail`、`margin_detail` 等描述用户希望生成的图表或表格，并声明
所需 source artifacts。它们是 presentation request，不是测试计算事实。

### Artifact name

`result`、`group_execution`、`order_audit`、`equity_curve_report`、receipt 等是持久化对象名称。
它们描述存储与下载，不是领域结果能力。

### `ResultTabDefinition`

这是前端结果页面的 tab 声明，只负责 UI，不是 TestModule result contract。

三者目前有所混用，但不能直接作为 TestModule 的 `result_id`。

## 建议的 Result ID 语义

Result ID 是某种测试能够产生的**独立、稳定计算事实 ID**。原示例粒度过粗，已经由
Grill 173.13 修正为指标级，例如：

```text
single_factor_ic_mean
single_factor_ic_std
single_factor_icir
single_factor_ic_t_stats
single_factor_ic_series
```

它不是：

- Python 字段名；
- HTTP JSON key；
- artifact 文件名；
- UI tab；
- 图表或表格请求；
- TestResult 的类名。

## 与领域 TestResult 的关系

一次 TestModule 执行仍只返回一个最适合该领域的计算结果对象，但它不需要预先按 Result ID
逐项填充，例如：

```python
ICComputationResult(
    dimensions=...,
    ic_series_matrix=...,
    summary_stats_matrix=...,
)
```

多个 Result ID 由 resolver 从共享 kernel 输出中取得：

```text
single_factor_ic_mean    -> summary_stats_matrix["mean"]
single_factor_ic_std     -> summary_stats_matrix["std"]
single_factor_icir       -> summary_stats_matrix["IR"]
single_factor_ic_t_stats -> summary_stats_matrix["t_stat"]
```

因此：

- 一个 TestResult 可以满足多个 Result ID；
- 一个 Result ID 不要求对应一个独立 Python 结果类；
- 请求多个 Result ID 不要求执行多个 TestModule；
- Result ID 也不能把领域结果强迫成通用自由 JSON。

## 与 Renderer 的关系

Renderer 声明自己需要哪些计算事实：

```text
single_factor_summary_table
  -> requires single_factor_ic_mean
  -> requires single_factor_ic_std
  -> requires single_factor_icir
  -> requires single_factor_ic_t_stats

IC monthly heatmap
  -> requires single_factor_ic_series

IC coverage table
  -> requires single_factor_ic_valid_count
  -> requires single_factor_ic_missing_ratio
```

presentation request 属于 renderer 命名空间，例如 `ic.monthly_heatmap`；它与
`ic.observations` 不是同一个 ID。

## TestModule 登记什么

TestModule 登记自己能产生的 Result ID 集合、每个 ID 由哪个共享 computation kernel 产生，
以及如何从领域 computation result 中取得。
此登记供：

- Job 提交前验证 requested result IDs；
- 模块规划必要计算；
- runner 检查返回结果是否覆盖所请求事实；
- 持久化层选择摘要或 artifact；
- Renderer 声明输入依赖。

schema、成本、依赖和保留策略分别如何声明仍需后续逐项决定；本轮只确定 Result ID 与领域
TestResult 不是一对一类关系。

## 已接受结论

每次 TestModule 执行返回一个领域 computation result；模块登记的多个指标级 Result ID
可以由同一组共享 computation kernels 一次产生，并由 resolver 从计算结果中取得。图表、
表格、artifact 和 UI tab 使用各自独立的命名空间。
