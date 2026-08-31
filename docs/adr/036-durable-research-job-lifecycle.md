# ADR-036：可持久化研究任务生命周期

## 状态

已被 ADR-037、ADR-038 和 ADR-039 取代。

本文记录第一版可持久化任务设计。其中由视图拥有取消权、持久化进度/事件、可续租进程槽位、
基于重放的 step continuation 和 TTL 语义已经不再是当前实现。

## 背景

长时间运行的回测和因子分析过去属于浏览器页面运行时。HTTP 请求提交一个进程内闭包，读取可变的页面
因子并覆盖单一的最新结果。这会造成并发运行竞争，使刷新和重启恢复不可靠，也无法实现进程隔离。

## 决策

研究执行使用四种彼此独立的身份：

- `session_uuid` 用于 HTTP 请求认证，不拥有研究数据。
- `view_uuid` 标识一个浏览器 tab 的观察租约。刷新从 session storage 恢复同一值，关闭时标记为脱离。
- `workspace_id` 拥有研究上下文，并指向一个可变配置。
- `run_id` 拥有一个不可变 RunSpec；每个分析都有可持久化的 `job_id`，重试或 step continuation
  通过新的 Job ID 形成关联尝试。

用户配置使用一套 schema 和一张表。工作区配置与命名的可复用模板都是 `ResearchConfiguration` 行，
只是角色不同。编辑覆盖工作区行并递增乐观锁计数器，不保留草稿历史。保存或加载模板时，在配置行之间
复制同一个规范 payload。提交时把该 payload 复制为不可变 RunSpec，RunSpec 才是历史执行记录。

提交边界序列化选中的路径、因子 alias、设置、时间范围和分析选项。Worker 只接收 RunSpec payload
和可导入的 runner 路径；不会接收 Flask 请求、session、浏览器对象或 FactorTester 实例，也不查询
可变页面状态。

SQLite 是任务元数据、RunSpec、状态、取消请求、有界事件、最新进度/manifest、checkpoint、错误和
生成物元数据的权威存储。活动进程句柄和 SSE 广播仍是进程内缓存。进程槽位使用可续租的 SQLite 租约，
因此共享同一数据库的 Flask worker 仍共同遵守并发上限。

取消请求是可持久化的。调度 Worker 读取规范取消请求并转发给子进程取消事件；子进程在宽限期后仍无响应时
被终止。启动时会把已死亡的调度器协调为可读取的失败终态记录。

Step 模式持久化确定性的 flow cursor，并把尝试标记为 `paused` 后释放 Worker 槽位。`continue`、
`until` 和 `end` 创建有明确关联的新尝试。回放到 cursor 可能重新计算先前的确定性 flow；不会让 Worker
一直阻塞等待 UI 输入。

绑定观察者的 Web 任务只有在视图租约宽限期结束后才取消；刷新会续租同一租约。CLI 任务默认可持久化，
不依赖视图。终态记录和生成物在 TTL 到期前仍可查询；到期以显式状态表示，而不是直接删除。

## 后果

- Web 和 CLI 共用 `/api/test-authoring/workspaces`、`/api/runs` 与 `/api/jobs`。
- Web 和 CLI 共用配置/模板 schema 及加载/保存 API。
- 工作区 revision 是计数器，不是保存的历史快照。
- 没有直接提交任务的旁路端点，也没有按分析类型拆出的任务 API。
- SSE 支持 `Last-Event-ID` 与 `after`；保留事件出现间隙时发送 `reset`。
- 大型生成物可以迁移到文件或对象存储，不改变任务所有权；数据库保存生成物身份和完整性信息。
- 部署必须共享配置的 SQLite 数据库和生成物存储。以后把调度移到独立服务时仍保持相同 API 合约。
