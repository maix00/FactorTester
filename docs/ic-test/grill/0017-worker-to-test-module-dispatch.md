# Grill 173.18 — Worker 直接执行 TestModule

Status: accepted

## 用户修正

新架构的旁路应从 Job execution worker 开始，而不是保留：

```text
worker -> run_ic() -> ICTestModule
```

最终正确调用链是：

```text
worker -> ICTestModule.execute(TestRuntime)
```

因此 `run_ic`、`run_group`、`run_factor_type_analysis` 这一组专用函数不是新架构的最终接口。

## 当前 worker 的真实行为

当前执行 worker 收到：

```text
runner_path
payload
artifact_root
retention_mode
```

然后 `_worker_entry()` 执行：

```python
runner = _load_runner(task["runner_path"])
runner(task["payload"], sink, cancel_flag)
```

IC 的 `runner_path` 是：

```text
server.modules.single_factor_test.process_runners:run_ic
```

因此当前 worker 并不知道 TestModule，只知道任意可调用函数路径。

## 迁移期的执行目标

迁移期 Job 需要表达两种执行目标，但 IC 只使用新目标：

```text
LegacyRunnerBinding
  runner_path

TestModuleExecutionBinding
  module_id
  module_import_path
  module_contract
  requested_artifact_ids
```

执行 worker 根据绑定类型分发：

```text
TestModuleExecutionBinding
  -> 只导入绑定的 TestModule
  -> TestModule.from_run_spec(frozen_run_spec)
  -> 构造 TestRuntime
  -> TestModule.execute(runtime, requested_artifact_ids)

LegacyRunnerBinding
  -> 原 runner_path 调用
```

这不是让 worker 注册或导入全部测试类。控制面/规划阶段先解析 `module_id`，冻结唯一 binding；
worker 只加载当前 Job 的一个 TestModule。

## 是否需要另一组 worker 进程

不需要为了迁移再常驻一组 IC worker。现有长期 worker pool 可以继续负责进程隔离、取消、进度
和 sink；改变的是 worker 内部的执行目标协议。

推荐：

```text
same LongLivedWorkerPool
  -> TestModule binding path   # IC
  -> legacy runner path        # 尚未迁移的测试
```

而不是：

```text
legacy worker pool
new IC worker pool
```

否则迁移期间会增加常驻进程、调度容量和资源亲和管理，且这些复杂度在全部模块迁移后还要删除。

## LongLivedWorkerPool 的真实作用

`LongLivedWorkerPool` 不是 IC runner，也不是 TestModule registry。它管理一组可重复使用的子
进程，当前负责：

- daemon 启动时提前创建 worker，避免每个 Job 重新 spawn Python 进程；
- 一个空闲 worker 同时只接收一个 Job；
- 通过 task queue 把任务送进子进程；
- 通过 output queue 回传 progress、artifact、result 和 error；
- 保存 Job 到 worker 的对应关系；
- 传递取消标志，并在宽限期后终止不响应取消的 worker；
- worker 崩溃或被终止后识别 worker loss；
- 按 cache keys 选择更可能已有数据缓存的空闲 worker；
- Job 完成后保留进程，继续处理下一项任务。

因此它解决的是进程生命周期、隔离、IPC、取消和缓存亲和问题，不决定“做 IC 还是做回测”，
也不应该理解 Result ID 或 Artifact。

## 最后删除什么、不删除什么

最后不删除 `LongLivedWorkerPool`。应保留：

```text
LongLivedWorkerPool
  process lifecycle
  task/output queues
  cancellation
  crash recovery
  cache affinity
```

全部 TestModule 迁移后删除的是旧的函数执行协议：

```text
runner_path
_load_runner()
LegacyRunnerBinding
process_runners.py
```

worker 的最终任务协议只剩：

```text
TestModuleExecutionBinding
  -> selected TestModule
  -> TestRuntime
```

“删除 Legacy binding”不能表述成“删除 worker pool”。

## Job、Planner 和 Worker 的职责

### Job

保存：

- `test_module_id`；
- 冻结 RunSpec；
- requested Artifact IDs；
- 执行绑定；
- source revision 和输入 identity。

它不保存 IC 专属函数名。

### Planning worker

使用控制面的 TestModule manifest：

- 校验 RunSpec 与 Artifact IDs；
- 解析唯一 TestModule binding；
- 生成数据/cache 需求和有界 execution plan；
- 不运行统计 kernel。

### Execution worker

- 导入唯一 TestModule；
- 构造 TestRuntime；
- 把 computation request 交给 TestModule；
- 将进度、取消、错误和 Artifacts 接回通用 sink。

### TestModule

- 解释领域 RunSpec；
- 调用共享 Result planner/executor；
- 运行领域 kernels；
- 返回领域 computation result 和 requested Artifacts。

## IC 首次切换

本期只有：

```text
kind=ic
  -> TestModuleExecutionBinding(module_id="single_factor.ic")
```

继续使用旧路径的：

```text
kind=backtest
kind=factor_evaluation
kind=factor_type_analysis
```

新 IC 路径不经过 `process_runners.run_ic`，也不需要它作为适配器。

完成真实 Job 验收后，删除：

- IC 的 `runner_path` 映射；
- `process_runners.run_ic`；
- 只被旧 IC runner 使用的响应组装代码。

其他专用 runner 只有在各自 TestModule 迁移时才删除。

## 最终状态

当全部测试模块迁移后：

```text
Job Queue
  -> Planning Worker
  -> frozen TestModuleExecutionBinding
  -> Execution Worker
  -> selected TestModule
  -> Result DAG
  -> Artifacts
```

届时删除：

- `runner_path` Job 字段；
- `_load_runner()`；
- legacy runner branch；
- `process_runners.py`。

## 已确认

> `LongLivedWorkerPool` 作为通用执行基础设施长期保留；迁移期 task 支持
> `LegacyRunnerBinding | TestModuleExecutionBinding`；IC 只使用后者；所有模块迁移完成后只
> 删除 Legacy binding 和 runner-path 调用，不删除 worker pool。
