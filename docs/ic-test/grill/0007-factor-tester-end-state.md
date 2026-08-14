# Grill 173.8 — FactorTester 最终职责与结果分发

Status: accepted

## 本轮问题

在 TestModule 负责测试执行、FactorEvaluationContext 负责因子求值之后，现有
`FactorTester` 是否应演进为测试结果分发器？

## 结论建议

不建议让 `FactorTester` 成为结果分发器。完成职责拆分后，旧 `FactorTester` 应退役，而不是
为了保留对象名称再承接一项新的职责。

## 生命周期冲突

异步研究路径中的 FactorTester 是 worker-local 对象：

```text
Job 开始
  -> 创建 FactorTester
  -> 因子求值
  -> Job 结束
  -> FactorTester 消失
```

测试结果却需要在 Job 结束后继续存在：

- CLI/UI 查询；
- 审计和 replay；
- 后续生成不同表格与图像；
- report 引用；
- artifact 保留；
- worker 或服务器重启后读取。

因此短命的运行对象不能成为长期结果的权威入口。若为了读取历史结果而让 FactorTester
反向依赖 JobRepository、artifact store 和 renderer，它将再次变成混合型 service locator。

## “结果分发”实际包含三个不同动作

### 运行前：请求哪些计算事实

```text
JobSpec.requested_result_ids
  -> 控制面读取 TestModule result capability
  -> 验证请求合法
  -> 冻结到 RunSpec/JobSpec
```

这里的权威对象是 TestModule 的结果能力声明，不是 FactorTester。

### 运行完成：发布计算结果

```text
TestModule.execute(runtime)
  -> TestResult
  -> 通用 Job runner
  -> WorkerSink
  -> result summary / artifact / evidence
```

这里由 Job runner 和 sink 管理运行事件与持久化边界。

### 运行之后：读取和呈现结果

```text
持久化 TestResult / artifact
  -> result query
  -> Renderer
  -> table / chart / report
```

这里需要的是稳定的结果查询与 renderer 入口，而不是恢复一个 FactorTester 实例。

## FactorTester 当前职责的去向

| 当前职责 | 目标归属 |
|---|---|
| 多 Factor 求值、预载和共享 cache | `FactorEvaluationContext` |
| 表达式内部求值参数 | `ExprEvaluateContext` |
| IC、回测等测试执行 | 各 `TestModule` |
| Job kind 解析 | 控制面的 `TestModuleRegistry` |
| Job 执行基础设施 | `TestRuntime` |
| Factor 计算结果 | `FactorEvaluationResultSet` |
| 测试结果 | 各领域 `TestResult` |
| 结果持久化和事件 | Job runner / sink / repository |
| 表格、图像和报告 | Renderer |
| 页面跨请求状态 | 单独的页面 session/runtime |
| backtest account | `BacktestRunState` |

这些职责迁出后，FactorTester 不再剩下独立且内聚的领域职责。

## 是否需要一个结果分发对象

可能需要稳定的结果访问接口，但不应预先假定必须是一个有状态“大对象”。最小形式可以是：

```text
TestResult
  -> 按 result ID 访问本次运行已经产生的计算事实

Job result query
  -> 按 Job ID 读取持久化摘要和 artifact 引用

Renderer registry
  -> 按 presentation request 选择 renderer
```

是否需要独立 `TestResultResolver`，应在后续 Grill “结果 ID 与结果对象的关系”中根据真实读取
需求决定；不能为了给 FactorTester 找新用途而创建。

## 对本地同步调用的影响

如果本地 Python 调用方需要“一行运行测试并取得结果”，可以提供无状态 facade：

```python
result = run_test(module, run_spec)
```

或由通用 runner 的进程内版本提供。它不是历史结果存储器，也不应继续叫 FactorTester。

## 已接受结论

FactorTester 完成职责迁移后退役；不把它改造成结果分发器。结果请求由 TestModule 能力声明
校验，结果发布由 Job runner/sink 完成，历史读取与呈现由结果查询接口和 Renderer 完成。
