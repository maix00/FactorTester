# Grill 173.27 — TestFlowComposition 的所有权

Status: accepted

## 问题

固定 Flow 组合可以由两处产生：

1. `TestModule` 明确声明；
2. 全局 Flow registry 根据已注册 provider 自动拼装。

两者看似都能生成同一 DAG，但所有权和失败方式不同。

## 方案一：全局 Registry 自动拼装

全局 registry 保存所有 TestModule 的 Flow，再根据 ResultRef 和 Artifact 需求寻找 provider。

问题：

- worker 必须加载与当前测试无关的模块；
- 相同 ResultRef 容易出现多个候选 provider；
- 新插件被导入后可能悄悄改变既有测试计划；
- registry 同时承担“有哪些 Flow”和“某种测试应该如何运行”两种职责；
- 很难回答某个 mandatory Flow 为什么属于 IC 或回测。

这与此前“不让一个测试进程注册全部测试类”的决定冲突。

## 方案二：TestModule 拥有组合

推荐：

```python
class BacktestModule(TestModule):
    composition = TestFlowComposition(
        mandatory_flows=(BACKTEST_LIFECYCLE,),
        result_providers=(
            RETURN_PATH,
            RISK_METRICS,
            PORTFOLIO_PROJECTION,
        ),
        artifacts=(...),
    )
```

```python
class ICTestModule(TestModule):
    composition = TestFlowComposition(
        mandatory_flows=(IC_OBSERVATION,),
        result_providers=(IC_SUMMARY, IC_ROLLING, IC_ACF),
        artifacts=(...),
    )
```

职责划分：

| 对象 | 职责 |
|---|---|
| `TestModuleRegistry` | 根据 Job test kind 找到 TestModule factory；不加载所有实现 |
| `TestModule` | 拥有测试语义、RunSpec 校验和 TestFlowComposition |
| module-local `FlowCatalog` | 索引该测试获准使用的 Flow/provider 定义 |
| `FlowPlanner` | 使用 composition、Artifact IDs 和冻结输入生成 FlowPlan |
| `FlowPlanExecutor` | 执行已验证计划，不自行发现或选择测试语义 |

共享 Flow 可以被多个 TestModule 显式引用，但不能因为“已在全局注册”就自动进入另一种测试。
这使计划变更只能通过 TestModule 组合变更发生，便于审计和回归。

## 运行过程

```text
Job(test_kind, artifact_ids)
→ TestModuleRegistry.load(test_kind)
→ selected TestModule.validate(RunSpec)
→ selected TestModule.composition
→ module-local FlowCatalog
→ FlowPlanner.plan(...)
→ FlowPlanExecutor.execute(...)
```

Execution Worker 只加载被 Job 选中的 TestModule 及其显式依赖，不扫描全部测试模块。

## 已确认

`TestFlowComposition` 应由 `TestModule` 拥有。Registry 只解决身份到 factory/定义的查找，
不能替 TestModule 决定固定组合。

已接受：

> `TestModule` 是 `TestFlowComposition` 的语义所有者；全局 `TestModuleRegistry` 只按
> test kind 定位 factory，模块自己的 `FlowCatalog` 只索引显式获准的 Flow；Planner 不从
> 全局 provider 池自动拼装测试，从而避免加载无关测试和组合随插件导入发生漂移。
