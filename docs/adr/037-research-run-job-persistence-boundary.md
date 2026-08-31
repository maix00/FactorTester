# ADR-037：研究运行与任务的持久化边界

## 状态

已接受，取代 ADR-036 中关于生命周期和持久化的决策。

## 背景

异步研究任务必须在提交它的 HTTP 请求、浏览器页面、CLI 进程或 Flask worker 消失后仍可查询。
把每个 SSE 活动和进度更新都持久化，会把 SQLite 变成高频事件传输层，明显拖慢真实回测，也不能因此
让计算具备可恢复能力。

系统还必须区分用户请求的配置与执行时解析出的具体产品、数据源、字段、频率和数据版本。

## 决策

研究所有权链为 `user -> ResearchWorkspace -> ResearchRun -> JobAttempt`。Run 冻结用户请求的
RunSpec。每次分析尝试拥有一个 `job_id`，并在执行前异步生成紧凑、不可变的 ExecutionPlan。重试创建
新尝试；重新运行已完成的提交创建新 Run。历史配置不能覆盖后来已经改变的工作区；恢复历史配置时创建
新工作区。

任务是可持久化且与页面无关的。刷新、关闭页面、SSE 断开、CLI 退出和仅 API 重启都不改变任务状态。
取消必须显式请求。`page_uuid` 与 `view_uuid` 仍是临时 UI/运行时身份，不是任务所有者或取消键。

SQLite WAL 只存储低频规范事实：

- Run/Job 身份、所有者、工作区、类型、重试链和时间戳；
- 冻结的 RunSpec/hash，以及紧凑的 ExecutionPlan/hash/notice；
- 状态、取消请求/原因、执行/部署元数据；
- 根据权限得出的调度资格和用户的一个队列置顶项；
- 紧凑结果摘要或错误/traceback；
- 生成物身份、完整性、大小、状态和用户配额。

SQLite 不存储进度、活动记录、SSE 历史、活动 manifest、Worker 心跳、进程槽位续租、缓存清单、
DataFrame、完整曲线/详情或 step 引擎状态。实时进度和有界事件环属于任务 daemon。重连时 daemon 发送
当前内存快照；cursor 不可用时显式发送 reset。数据库状态仍是生命周期和终态摘要的权威。

任务元数据和紧凑摘要不会静默过期。用户可以显式删除终态历史。临时传输/暂存文件由 TTL 管理；保留结果
的策略由 ADR-039 定义。

状态模型为：

```text
submitted -> planning -> awaiting_confirmation -> queued -> running
                                      |                       |-> paused
                                      |                       |-> succeeded
                                      |                       |-> failed
                                      `---------------------->|-> cancelled
```

普通 auto 解析只提供信息。语义回退必须是 warning。排除产品、裁剪时间范围，或替换显式数据源/频率都
必须要求确认；无法满足的要求使 planning 失败。

## 后果

- Web 和 CLI 使用同一套工作区/Run/Job API。
- 个人任务视图不依赖浏览器本地状态即可重建生命周期状态。
- 移除数据库事件回放是有意决策；进度连续性依赖活动 daemon，生命周期连续性依赖 SQLite。
- `test_job_events`、持久化的最新进度/manifest、视图拥有的任务租约、可续租 SQLite 进程槽位和
  生命周期策略兼容分支均已退出当前设计。
- Step 模式仍驻留在单个 Worker 内存中。API 重启不影响它，但 daemon 重启后不可恢复，必须显式失败。
