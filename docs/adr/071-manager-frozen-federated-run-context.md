# ADR 071：联邦 Run 提交使用 Manager 冻结上下文

## 状态

已接受，针对 Issue #185，2026-08-13。

## 背景

研究工作区及其可编辑配置由用户当前使用的 Manager 所有；执行服务可能在另一台服务器上，且不共享该 Manager 的 SQLite。只转发 `workspace_id` 和 `configuration_revision` 会让远程服务在评估数据源能力前失败；复制可编辑工作区数据库又会把冲突处理放进任务提交关键路径。

## 决策

源 Manager 在路由选择前只冻结一次 Run 请求。它解析所有者作用域的 workspace、configuration 或 snapshot、产品选择、因子 revision、数据源 manifest、分析选项和可选 Profile 身份，形成与本地执行 API 使用的相同不可变 prepared request。

Manager 把 prepared request 放入保留字段 `_manager_run_context`，封装包含 schema 版本、认证所有者、规范 RunSpec 哈希以及经过校验并冻结的 prepared request。完全相同的封装发送给每个候选端点的只读 capability preview 和最终选定服务的 Run submission。执行服务校验所有者、schema、配置指纹、RunSpec 关系和哈希，然后只执行封装，不读取自己的工作区数据库。

schema v2 还携带每个被引用、且 RunSpec 因子 revision manifest 尚未显式作为临时 Run 输入的规范因子族源码。每条源码按规范族身份索引，必须匹配已冻结的 `family_source_hash` 与 `source_access_policy`。缺失、多余、过大、重复、重新分类或哈希变化都会拒绝整个上下文；`public`/`owner_only` 仍表示源码权威，`manager_frozen` 只表示传输方式，不能改变因子 revision 身份。

保留字段中的客户端值始终由源 Manager 删除并替换。对等传输在 WireGuard 17998 上认证；执行端口保持 loopback，只通过本地 Manager capability 接收上下文。封装有大小上限，保证 Base64 联邦帧低于私有控制端点请求限制。

这是快照传输，不是工作区同步。源端后续编辑产生不同 context 和 RunSpec；PostgreSQL 不存储或中转请求，也不进入任务提交关键路径。提交时执行器把校验后的 bundle 写入既有、所有者绑定、权限 0600 的临时源码作用域，并将同样字节保留为 Job 输入生成物供重试和溯源。终态清理临时作用域，保留输入遵循 Job 生成物生命周期和配额。

## 后果

- 服务器可以执行源工作区的 Run，而无需复制工作区 SQLite。
- 能力选择评估的配置与实际提交完全一致，消除编辑/预检竞态。
- 候选端不需要重复的本地规范因子注册表，而是校验并执行 Manager 冻结的源码；缺运行时依赖或数据源仍明确报 capability 错误。
- 大文件继续走 7997/17997 数据面；控制封装只适合有界的 Run authoring 请求、源码元数据和小型内嵌源码包。
