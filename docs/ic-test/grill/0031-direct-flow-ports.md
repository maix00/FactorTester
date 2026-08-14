# Grill 173.32 — Flow 直接传递 StateRef 与 ResultID

Status: proposed

## 纠正

Flow 不需要“顶层 ResultRef → IntermediateResult component → 自动展开 provider”三层模型。

Flow 声明的 inputs/outputs 直接就是端口对象：

```text
FlowPort[T]
├── StateRef[T]   可变运行状态端口
└── ResultID[T]   write-once 结果端口
```

`ResultID[T]` 本身同时表达：

- 结果身份；
- 值类型/schema；
- Flow DAG 上的输入或输出端口；
- Result Store 的读取/发布 key。

不再额外引入 `ResultRef` 包装 `ResultID`。

## 声明与运行时值

Flow 定义保存的是 typed port，不是某次 Job 的大型 DataFrame：

```python
PerformanceSummaryFlow(
    inputs=(EQUITY_PATH,),
    outputs=(SHARPE, MAX_DRAWDOWN, ANNUALIZED_RETURN),
    operation=compute_performance_summary,
)
```

运行时 executor 根据端口取出实际对象：

```python
input_values = {
    EQUITY_PATH: pd.Series(...),
}

output_values = operation(input_values)

# {
#   SHARPE: 1.21,
#   MAX_DRAWDOWN: -0.13,
#   ANNUALIZED_RETURN: 0.18,
# }
```

executor 验证返回 key 与 declared outputs 一致，再原子发布。

## IntermediateResult 只是普通输出值

如果一次矩阵计算自然形成一个值得整体复用的对象：

```python
IC_STATS_MATRIX = ResultID[ICStatsMatrix]("single_factor.ic_stats_matrix")

ICStatsFlow(
    inputs=(IC_SERIES,),
    outputs=(IC_STATS_MATRIX,),
    operation=compute_ic_stats_matrix,
)
```

Artifact 或下游 Flow 可以直接读取 `IC_STATS_MATRIX`。

如果 mean、std、ICIR 也需要独立 Result IDs，Flow 就直接列出：

```python
ICStatsFlow(
    inputs=(IC_SERIES,),
    outputs=(IC_STATS_MATRIX, IC_MEAN, IC_STD, ICIR),
    operation=compute_ic_stats,
)
```

operation 可以让这些值引用同一矩阵对象的列或视图，不要求复制。

因此：

- IntermediateResult 不再拥有另一套 `provided_result_ids`；
- 不需要 Planner 自动展开 component provider；
- 不需要 resolver registry；
- Flow outputs 是 provider 关系的唯一事实源；
- ResultID 是结果身份和端口的唯一事实源。

普通局部 lambda 仍可用于从共享矩阵取值，但它只是 operation 内部实现，不是架构对象。

## 回测复合 Flow

回测同样直接声明：

```python
BacktestLifecycleFlow(
    inputs=(FROZEN_RUN_SPEC, DATA_BINDINGS, FACTOR_DEFINITIONS),
    outputs=(BACKTEST_RESULT,),
    operation=BacktestLifecycleOperation(...),
)
```

后续整理 Flow 可以直接把领域结果拆成稳定基础结果：

```python
BacktestPathsFlow(
    inputs=(BACKTEST_RESULT,),
    outputs=(
        EQUITY_PATH,
        POSITION_PATH,
        MARGIN_PATH,
        EXECUTION_TRACE,
    ),
    operation=extract_backtest_paths,
)
```

这些输出可以是对 `BacktestResult` 内已有对象的只读引用，不做深拷贝。Sharpe 等指标 Flow
随后只依赖真正需要的 `EQUITY_PATH`。

## 与 StateRef 的统一

复合 Flow 内部的 lifecycle 声明同样使用 inputs/outputs：

```python
LedgerFlow(
    inputs=(ORDER_STATE, CASH_STATE),
    outputs=(POSITION_STATE, CASH_STATE),
)
```

区别只来自端口类型：

| 端口 | 更新规则 | 调度范围 |
|---|---|---|
| `StateRef` | 可按生命周期重复写入 | Composite Flow 内部 |
| `ResultID` | 每 Job 原子发布一次 | 外层统一 FlowPlan |

无需再创造另一种 input/output 语法。

## 对此前 resolver 决定的影响

此前把 resolver 设为 IntermediateResult 类属性，是为了解决“一个对象隐式提供多个 Result
IDs”。直接端口模型不再需要这层机制：

- 想整体消费，就输出一个整体 ResultID；
- 想分别消费，就在同一 Flow outputs 直接声明多个 ResultIDs；
- operation 内可以用普通函数/lambda 从共享计算对象取值；
- Planner 只看显式 outputs，不推断对象内部结构。

这删除了 component Result、deferred binding 和自动 provider 展开等概念。

## 谁提供结果

直接模型中只有四个明确职责：

| 职责 | 提供者 |
|---|---|
| 声明某 Result ID 由哪个计算产生 | Flow 的 `outputs` |
| 计算并返回 Result ID 对应的实际值 | Flow 的 operation |
| 建立 `ResultID → Flow` provider 索引 | module-local `FlowCatalog` |
| 校验并保存实际值 | `FlowPlanExecutor` / Result Store |

例如：

```python
ICStatsFlow(
    inputs=(IC_SERIES,),
    outputs=(IC_STATS_MATRIX, IC_MEAN, ICIR),
    operation=compute_ic_stats,
)

def compute_ic_stats(inputs):
    matrix = calculate_matrix(inputs[IC_SERIES])
    return {
        IC_STATS_MATRIX: matrix,
        IC_MEAN: matrix["mean"],
        ICIR: matrix["mean"] / matrix["std"],
    }
```

这里 `matrix["mean"]` 或一个 lambda 只是 operation 内部普通代码，不是需要注册的 resolver。
`FlowCatalog` 看到 outputs 后，自然知道三个 Result IDs 都由 `ICStatsFlow` 提供。

## 推荐

采用直接端口模型。它最接近现有 backtest Flow，也最容易让 IC、回测和未来 TestModule 共用。

## 待确认

是否接受：

> `Flow.inputs/outputs` 直接列 `StateRef` 或 `ResultID`；定义阶段保存 typed identity，执行阶段
> 按 identity 传递实际对象；一个 Flow 若产生多个结果就直接列多个 ResultIDs，IntermediateResult
> 只是可选的普通结果值，不再另外声明 provider 或 resolver。
