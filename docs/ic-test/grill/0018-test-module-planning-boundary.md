# Grill 173.19 — Planning Worker 与 TestModule 的边界

Status: accepted

## 为什么需要继续区分两个 plan

当前全局 `build_execution_plan(kind, data)` 根据 `kind` 分支处理 IC、回测等测试。它生成：

- 产品、时间范围和数据要求；
- cache keys；
- notices；
- confirmation requirement；
- resolved hash。

新的 Result DAG 还需要另一类规划：

- requested Artifact IDs；
- required/supplemental Result IDs；
- 需要执行的 kernels；
- kernel 拓扑和输出类型。

两者目的不同：

```text
资源与输入计划
  回答：运行需要哪些数据、缓存、来源和权限

结果计算计划
  回答：为了 requested Artifacts，需要执行哪些 Result kernels
```

不能继续由全局 `if kind == "ic"` 规划第一部分，再由 ICTestModule 在执行时完全重新猜第二部分。

## 推荐的 TestModule 协议

让 Planning Worker 和 Execution Worker 都通过同一个 TestModule contract：

```python
class TestModule:
    @classmethod
    def plan(
        cls,
        frozen_run_spec,
        requested_artifact_ids,
        planning_runtime,
    ) -> TestExecutionPlan:
        ...

    @classmethod
    def from_run_spec(cls, frozen_run_spec):
        ...

    def execute(
        self,
        execution_plan,
        runtime,
    ) -> TestComputationResult:
        ...
```

`TestExecutionPlan` 可以包含两个明确区段：

```text
input_plan
  data requirements
  cache keys
  source/factor identities
  notices

result_plan
  artifact IDs
  result IDs
  kernel IDs
  dependency order
```

这是一个冻结执行合同，不是两条独立 Job，也不要求把 kernel 中间结果持久化。

## Planning Worker

新 IC 路径中，Planning Worker：

1. 根据 Job 的 `test_module_id` 解析唯一 TestModule binding；
2. 只导入 ICTestModule；
3. 调用 `ICTestModule.plan(...)`；
4. 返回有界、可预览的 `TestExecutionPlan`；
5. 不加载历史数据矩阵，不执行 IC 统计。

这样可以在运行前明确展示：

- 使用什么输入；
- 将生成什么 Artifact；
- 需要哪些 Result IDs；
- 将执行哪些 kernels；
- 是否有不支持的 Artifact 或缺失能力。

## Execution Worker

Execution Worker：

1. 接收冻结 RunSpec、TestModule binding 和 TestExecutionPlan；
2. 校验 plan identity/source revision；
3. 加载 ICTestModule；
4. 构造 TestRuntime；
5. 执行已经规划的 kernel DAG；
6. 输出 requested Artifacts。

它不再调用全局 `build_execution_plan("ic", ...)`，也不通过 `run_ic` 重新组装输入。

## 迁移边界

本期：

```text
IC planning
  -> ICTestModule.plan()

IC execution
  -> ICTestModule.execute()

其他测试 planning/execution
  -> 旧 build_execution_plan + LegacyRunnerBinding
```

全部模块迁移后，删除全局按 `kind` 分支的 planning 实现；每个 TestModule 通过同一 contract
负责自己的领域输入计划，并复用通用 Result planner。

## 已确认

> Planning Worker 调用 `TestModule.plan()` 冻结输入计划与 Result DAG；Execution Worker 调用
> `TestModule.execute()` 执行该计划；TestRuntime 仍只提供执行资源，不负责领域规划。
