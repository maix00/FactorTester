# Grill 173.7 — Factor 求值上下文与缓存边界

Status: accepted

## 本轮问题

如果 FactorTester 不再分发测试，那么所谓 `FactorCalcContext` 是否应当表示多个 Factor
一起 evaluate 时的上下文和缓存？它是否属于 `FactorExpr.evaluate` 的延伸？当前功能是否
已经混在多个对象中？

## 当前真实调用链

```text
FactorTester.calc_factor(factors)
  -> factor_tester_tasks.calc_factor(state, factors)
  -> 按显式 source frequency 对 Factor 分批
  -> 多个兼容 Factor 调用 evaluate_factors(...)
  -> 建立 EvaluationBatchContext
       - products / freq / window
       - 一次预载所需数据列
       - panel timeline
       - shared expression cache
       - shared structural keys
  -> 对每个 Factor 调用 Factor.evaluate(...)
  -> Factor.evaluate 建立/取得 FactorRunResult
  -> FactorExpr.evaluate 建立 EvaluateContext
  -> 表达式 DAG 各节点 _evaluate(EvaluateContext)
  -> 结果通过 _active_tester 写回 FactorTesterState.results
```

无法组成兼容 batch 的 Factor 则走单 Factor 或多个线程分别 `Factor.evaluate()` 的旧路径，
不会共享同一个 `EvaluationBatchContext`。

## 当前已有的两个 evaluate context

### `FactorExpr.EvaluateContext`

这是表达式 DAG 内部的单次递归求值上下文，包含：

- products；
- frequency；
- data source；
- cache；
- preloaded data；
- start/end/warmup window；
- 当前 `run_result`；
- panel timeline；
- shared cache keys。

每个表达式节点只需要从该对象读取输入并产出 DataFrame。

### `EvaluationBatchContext`

这是多个兼容 Factor 根节点共享的 batch 上下文，包含：

- 同一 products；
- 同一 frequency；
- 同一时间窗口和 warmup；
- 合并所有因子 ColumnRef 后的一次数据预载；
- 共用 panel timeline；
- 只缓存跨多个表达式重复出现的结构节点；
- compatibility assertion，防止错误复用。

它已经基本对应“多个 Factor 一起 evaluate 时的上下文和 cache 管理”。

## 当前混合与断裂

虽然已有 batch context，但职责仍分散：

1. `FactorTesterState` 同时保存产品、时间、Factor 列表和
   `dict[Factor, FactorRunResult]`；
2. 同一个 state 还保存页面 product selection 元数据、筛选状态和 backtest account；
3. `FactorRunResult` 同时包含因子求值事实、IC series/stats 和 returns，混入测试结果；
4. `EvaluationBatchContext` 管共享 IO/cache，但不正式拥有或返回整批 Factor 结果；
5. Factor 通过全局 `_active_tester` 找到结果存储位置，依赖是隐式的；
6. 没有 active tester 时，Factor 又把数据写回自身 `_data`/`_source_data`，形成另一种缓存
   所有权；
7. `EvaluateContext` 与 `EvaluationBatchContext` 字段高度重叠，但一个是内部表达式视图，
   一个是批量调度对象，命名没有体现层级。

因此不是缺少求值上下文，而是已有三个所有权边界没有对齐：

```text
表达式执行上下文
批量因子求值上下文
Factor 结果存储上下文
```

## 是否属于 FactorExpr.evaluate 的延伸

它属于 **FactorExpr 求值管线的上层 orchestration**，但不应成为 FactorExpr 子类或把批量状态
塞进表达式对象。

推荐层级：

```text
FactorEvaluationContext
  -> 管理一个兼容 batch 的多个 Factor、预载、共享缓存和结果
  -> 为每个 Factor 构造 ExprEvaluateContext

Factor.evaluate
  -> 处理 Factor 语义、频率、SignalAlign 和 Factor 结果

FactorExpr.evaluate(ExprEvaluateContext)
  -> 只递归执行一棵表达式 DAG
```

`FactorExpr` 应继续表达“算什么”，上下文表达“本次在什么产品、数据、窗口和缓存边界下
计算”。让表达式对象自己拥有跨 Factor cache 会造成跨 Run/Trial 数据泄漏。

## 命名建议

推荐使用 `FactorEvaluationContext`，而不是 `FactorCalcContext`：

- 现有领域方法使用 `evaluate`；
- 它不仅计算数值，还处理数据预载、时间轴、对齐、缓存和 provenance；
- 可明确对应 `Factor.evaluate` 与 `FactorExpr.evaluate`。

现有 `EvaluateContext` 应收窄并改为内部名称 `ExprEvaluateContext`。现有
`EvaluationBatchContext` 则演进为公开的 `FactorEvaluationContext`，不再新建第三套平行
对象。

## 建议的职责

`FactorEvaluationContext` 表示**一个兼容求值 batch**，可包含一个或多个 Factor：

```python
class FactorEvaluationContext:
    identity: FactorEvaluationIdentity
    preloaded: Mapping
    panel_timeline: PanelTimeline
    shared_cache: MutableMapping

    def evaluate(self, factors: Sequence[Factor]) -> FactorEvaluationResultSet:
        ...
```

`FactorEvaluationIdentity` 至少冻结：

- products；
- source/frequency；
- start/end/warmup window；
- 数据快照或 provenance 身份。

不同 identity 不得共用 cache。一个 TestModule 若研究多种频率或不兼容数据源，可以建立多个
`FactorEvaluationContext`，不能把整个 Job 强塞进一个 context。

`evaluate()` 返回 `FactorEvaluationResultSet`。context 可以在执行期间持有临时 result
builder，但最终计算事实必须显式返回，不能要求消费者再从全局 `_active_tester` 猜测结果。

单个 `FactorEvaluationResult` 只保存因子求值事实，例如：

- source/func/aligned table；
- data-present mask；
- panel timeline；
- provenance。

IC series、IC statistics、future returns 和回测结果不属于它们；这些由对应 TestModule 的
TestResult 保存。

## 对 `_active_tester` 的处理

目标接口应显式传递 context/result builder：

```text
FactorEvaluationContext.evaluate(factors)
  -> Factor.evaluate(..., evaluation_context=...)
  -> FactorExpr.evaluate(ctx=ExprEvaluateContext(...))
```

迁移期间可以用一个改名后的 ContextVar 作为内部 bridge，但它不能继续成为结果所有权的唯一
来源。最终消费者应读取显式返回的 `FactorEvaluationResultSet`。

## 已接受结论

不新增泛化的 `FactorCalcContext`；把现有 `EvaluationBatchContext` 演进为
`FactorEvaluationContext`，负责一个兼容 batch 中一个或多个 Factor 的预载、共享 DAG
cache、时间轴和求值结果；把现有 `EvaluateContext` 收窄为表达式内部的
`ExprEvaluateContext`；IC、returns 和回测结果从 Factor 求值结果中移出。
