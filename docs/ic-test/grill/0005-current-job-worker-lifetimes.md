# Grill 173.6 — 当前 Job、队列、worker 与 FactorTester 生命周期

Status: lifetimes audited; direct TestModule invocation accepted; factor-evaluation context split to Grill 173.7

## 本轮问题

先解释现有系统中：

- Job 队列是否长期存在；
- 一个 Job 是否固定使用一个 worker；
- 哪些对象长期存活；
- scheduler 如何把任务布置给 worker；
- FactorTester 是否必须作为 Job 到测试模块之间的转发层。

## 持久化队列不是内存 Queue

HTTP 提交研究任务时，`research_jobs` 表新增一条 `JobRecord`，初始状态为
`SUBMITTED`。因此权威队列是 SQLite 中按状态保存的 Job：

```text
SUBMITTED
  -> PLANNING
  -> AWAITING_CONFIRMATION 或 QUEUED
  -> RUNNING
  -> SUCCEEDED / FAILED / CANCELLED
```

`JobRepository` 对象可以长期存在，但它不长期持有数据库连接。每次 repository 操作打开
连接、完成事务并关闭连接；长期存在的是数据库文件及其中的 Job 事实。

worker 内的 `multiprocessing.Queue` 不是权威 Job 队列，只是 scheduler 已经选定 worker
之后，把一项任务送入该 worker 的进程间传输通道。

## 长期存活对象

### 独立 Job daemon 进程

`scripts/research_job_daemon.py` 启动一个独立进程，内部创建：

- `JobDaemonServer`：Unix socket IPC 服务；
- `ResearchJobScheduler`：调度器；
- 一个 scheduler polling thread；
- `EventBroker`：有上限的实时事件内存环；
- planner worker pool；
- execution worker pool。

daemon 重启后，SQLite Job 记录仍存在；内存事件、运行中集合和 worker 会消失。当前恢复逻辑
把重启时仍为 `PLANNING`、`RUNNING` 或 `PAUSED` 的 Job 标成失败。

### Scheduler

`ResearchJobScheduler` 与 daemon 同寿命。默认每秒执行一次 `tick()`：

1. 收取 planner 和 executor 的输出消息；
2. 处理取消；
3. 查询数据库中的 `SUBMITTED` Job；
4. 把它们交给空闲 planner；
5. 查询数据库中的 `QUEUED` Job；
6. 按用户并发额度、优先级、pin 和 cache affinity 交给空闲 executor。

### LongLivedWorkerPool 与 worker 进程

默认存在两个 pool：

- planner pool：默认 1 个长期 worker；
- executor pool：默认 2 个长期 worker。

worker 在 pool 创建时通过 `multiprocessing` 的 `spawn` 启动。它从自己的 `task_queue`
循环读取任务；完成一个 Job 后不会退出，而是等待下一个 Job。只有以下情况会被替换：

- worker 崩溃；
- Job 取消超过 grace period 后被强制终止；
- daemon/pool 关闭。

每个 worker 同一时刻只执行一个任务。pool 会保存有限的 `cache_keys`，后续任务优先分配给
缓存更匹配的空闲 worker。

## 一个 Job 是否只用一个 worker

不是“一条 Job 永久绑定一个 worker”，而是分阶段占用：

```text
同一个 Job
  -> planning 阶段占用一个 planner worker
  -> plan 持久化并进入 QUEUED
  -> execution 阶段占用一个 executor worker
```

planner worker 与 executor worker 属于不同 pool，不是同一个进程。执行阶段开始后，
`JobRecord.worker_pid` 记录本次 executor PID。Job 完成后 worker 解除占用，可以执行其他
Job。

如果没有空闲 worker，Job 留在数据库的待处理状态，scheduler 下一次 tick 再尝试，不会为每个
Job 临时无限创建进程。

## scheduler 如何把任务送出去

```text
HTTP / CLI / UI
  -> JobRepository.create(JobRecord, SUBMITTED)
  -> Unix socket wake daemon
  -> scheduler tick 查询 SUBMITTED
  -> planners.submit(...)
  -> task_queue.put(planning task)
  -> planner 生成 execution_plan
  -> scheduler 持久化 plan 并转为 QUEUED
  -> scheduler 选择空闲 executor
  -> executors.submit(...)
  -> executor.task_queue.put(execution task)
  -> worker 动态 import runner_path
  -> runner 通过 WorkerSink 发事件到 output_queue
  -> scheduler 消费事件
  -> 实时事件进入 EventBroker
  -> result/artifact/终态进入 SQLite 和 artifact 存储
```

这里存在两种不同 Queue：

1. SQLite Job 状态：持久、权威、可在进程重启后读取；
2. worker `multiprocessing.Queue`：短路径 IPC，只承载已分配任务和运行事件。

## FactorTester 的真实寿命

FactorTester 不是常驻 scheduler、Job 队列或 worker pool 的一部分。

当前有两种使用方式：

1. 页面交互路径可以把 FactorTester 登记到 `PageRuntime`，跨多个 HTTP 请求使用；
2. 异步 Job 的 IC、因子评估和因子类型分析通过
   `create_isolated_factor_tester_for_run()` 为本次运行创建 worker-local FactorTester，
   不登记到 PageRuntime，运行结束后不作为结果持久化。

FactorTester 当前实际承担：

- 持有 `FactorTesterState`；
- 提供 products、时间范围、factor cache 和 results 等状态访问；
- 为核心 Factor/FactorFamily 代码提供 `_active_tester` 所需的 duck-typed 上下文；
- 转发 `calc_factor`、`resolve_factor` 等底层因子操作；
- 唯一在完整测试层调用 `dispatch()` 的现有路径是 backtest。

IC、因子评估、因子类型分析都使用 FactorTester 的因子计算状态，但没有通过
`FactorTester.dispatch(test_kind)` 分发完整测试。

## FactorTester 是否需要成为测试转发层

当前代码证据不支持再把 FactorTester 扩大成 Job/TestModule Registry 的路由器。

更小的边界是：

```text
Scheduler / Job execution binding
  -> 选择并创建 TestModule
  -> TestModule 按需要创建或接收 FactorTester
  -> FactorTester 提供因子计算上下文
```

即：

- Job 调度不依赖 FactorTester；
- TestModule 选择不依赖 FactorTester；
- FactorTester 仍可作为需要计算因子的 TestModule 的运行依赖；
- 不需要 FactorTester 再做一次 `kind -> TestModule` 转发；
- 不需要因本次架构调整立刻重写依赖 `_active_tester` 的因子求值体系。

backtest 当前通过 `FactorTester(products=[]).dispatch("backtest")`，但真实回测状态在
`BacktestRunState`。这更像历史兼容入口，不足以证明所有 TestModule 都应经 FactorTester
分发。

## Job runner 如何直接调用 TestModule

当前 worker 固定调用：

```python
runner(payload, sink, cancel_event)
```

因此不需要为 TestModule 再增加一层 FactorTester 分发。可以把四个
`process_runners.run_*` 收成一个稳定入口：

```text
server.jobs.testing.runner:run_test_module
```

控制面在提交 Job 时已经把 `kind` 解析成单项 `TestModuleExecutionBinding`。通用 runner
执行以下固定步骤：

```text
run_test_module(payload, sink, cancel_event)
  -> 读取并校验冻结 binding
  -> 只加载 binding 指定的 TestModule 子类
  -> verify_execution_plan(binding.kind, payload)
  -> 建立本次 TestRuntime
  -> module = ModuleClass.from_run_spec(frozen_run_spec)
  -> result = module.execute(runtime)
  -> sink.emit_result(result)
```

建议的最小接口为：

```python
class TestModule(ABC):
    kind: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_run_spec(cls, run_spec: Mapping[str, Any]) -> Self:
        ...

    @abstractmethod
    def execute(self, runtime: TestRuntime) -> TestResult:
        ...
```

`TestRuntime` 只携带执行期依赖，例如：

- `sink`；
- `cancel_event`；
- owner 和已验证的运行身份；
- artifact 写入能力；
- 按需创建 `FactorCalcContext` 的 factory。

它不持有 TestModule Registry，也不解释某类测试结果。最终结果由模块返回，通用 runner
统一交给 sink；进度和 artifact 可在执行中通过 runtime 发布。

迁移初期，现有 IC、回测等函数可以由各自 TestModule adapter 调用，先保证运行语义不变；
不需要同时重写所有计算内核。

## FactorTester 是否应改名（原提案，待重新 Grill）

如果新边界确定为“因子计算上下文”，继续使用 `FactorTester` 确实会误导。但不能只把类名
机械改成 `FactorCalcContext`，因为当前对象还混有：

- `UniqueNameObject` 页面身份；
- `PageRuntime` 登记；
- product selection 页面元数据；
- `dispatch()` 任务表；
- backtest 的 `account`；
- 因子求值所需的 active context、缓存和方法。

上一轮曾建议直接定义：

```python
class FactorCalcContext:
    products
    start_dt
    end_dt
    user
    results

    def calc_factor(...): ...
    def resolve_factor(...): ...
    def get_result(...): ...
    def discard_result(...): ...
```

该建议尚未接受。代码审计发现已经存在 `FactorExpr.EvaluateContext` 和
`EvaluationBatchContext`；若直接增加上述对象会形成第三套重叠上下文。真实求值层级与命名
改在 `0006-factor-evaluation-context.md` 重新 Grill。

当前页面需要跨请求保存上下文时，可以由 PageRuntime 保存 `FactorCalcContext`；页面会话
身份、选择元数据是否应有单独的 `FactorResearchSession`，需要在迁移时按真实调用点拆分。
`dispatch("backtest")` 和 `account` 不进入新的 `FactorCalcContext`。

仓库目前约有 107 个 Python 文件引用 `FactorTester`，所以这是一次独立、可测试的语义迁移，
不能夹在 IC 统计计算修改中做字符串替换。最终目标可以删除旧 `FactorTester`，但必须先使
所有因子求值路径使用新的 context contract。

## 已接受部分

1. 通用 Job runner 直接调用已经绑定的 TestModule；
2. 调用协议为
   `ModuleClass.from_run_spec(frozen_run_spec).execute(TestRuntime)`；
3. 最终 TestResult 返回给通用 runner，再统一交给 sink；
4. FactorTester 不参与 Job kind 到 TestModule 的分发。

## 未决部分

TestModule 从 TestRuntime 取得的因子求值依赖究竟是什么对象，以及旧 FactorTester 如何
拆分，进入 Grill 173.7。
