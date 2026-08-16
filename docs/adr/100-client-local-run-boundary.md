# ADR 100: 客户端本地测试运行与 7997 显式上传边界

## 状态

已接受。

## 决策

客户端选择“本地运行”后，产品/频率可用性由本地 Bundle manifest 判断；
不满足条件时在启动测试前失败，不把请求转成服务器任务。客户端现有
`catalog.sqlite` 增加本地运行记录、文件清单和 durable outbox，outbox
只同步任务元数据、结果摘要和文件 manifest。

本地生成物与提交物默认留在客户端隔离目录。服务器 Manager 只保存
summary-only projection，不能从同步 JSON 得到源码或本地路径。用户在 Swift
任务详情中明确点击上传后，客户端先向 7998 获取一次性 upload capability，
再通过既有 7997 数据面上传；完成回执必须匹配当前用户、任务、文件名、大小、
SHA-256 和 `job_submission` transfer，服务器确认后才把文件标为可下载。

本地运行任务在 Manager 任务列表中标记为 `local`，服务器只提供只读摘要和
文件清单；普通 Web 页面仍不获得本地文件系统或本地 SQLite 渲染能力。

## 容错与安全

- outbox 先写本地 SQLite；Manager 不在线时保留 `pending/error`，过期的
  `sending` claim 可重新领取；操作 ID 和 projection hash 保证重复同步幂等。
- 本地 artifact 上传只允许客户端根目录内的真实文件，拒绝符号链接、路径
  穿越和不完整 SHA-256。
- 服务器不信任客户端直接提交的 `uploaded` 标记，也不接受任意已完成的
  transfer ID 来伪造上传状态；只有 7997 完成并通过字段匹配后才开放下载。
- PostgreSQL 不进入本地运行、摘要投影和 7997 字节传输的关键路径。

## 不做的事

本 ADR 不把研究图推进、常驻 Agent 或本地 Python 执行引擎重新放回 Manager；
运行代码包的按需获取与本地执行器由客户端运行时边界负责，服务器仅提供
声明式目录和已有 7997 对象数据面。
