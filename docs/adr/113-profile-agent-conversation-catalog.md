# ADR 113：Profile Agent 会话目录与内置历史视图

- Status: Accepted
- Date: 2026-08-19

## Context

同一个服务器 Agent 可能先后或同时服务多个研究身份。供应商的
`provider_thread_id` 只表示 Agent 运行时的线程，不应直接作为浏览器历史列表的
权限边界。直接转发供应商的 `thread/list` 也无法表达 FactorTester 的用户与
Profile 归属。

FactorTester 使用 ChatKit 的内置历史视图来完成会话列表、切换、新建、重命名和
删除；Manager 负责提供经过 Profile 权限过滤的线程协议。

## Decision

1. Manager 本地 SQLite 使用一张 `manager_agent_conversations` 表保存会话目录。
   会话归属由 `principal + profile_id` 确定；同一个 Agent 绑定多个 Profile 时，
   每个 Profile 只能读取自己的记录。
2. 浏览器看到的线程 ID 是 Manager 生成的 opaque `conversation_id`。供应商线程
   ID 只作为恢复所需的 `provider_thread_id` 映射，并通过 `provider_id` 记录其供应商；
   它不会作为 ChatKit 的浏览器线程 ID，也不会脱离当前用户与 Profile 单独授权。
   该映射只在已通过 Profile 过滤的适配器会话接口中返回。
3. `threads.list` 不通过公开 RPC 转发；ChatKit 的历史操作由适配器调用 Manager
   会话目录接口。`get`、`items`、`update`、`delete`、`turn` 每次都重新校验当前
   登录用户、Profile 和会话归属。
4. 停止、解绑或更换 Agent 不删除会话目录。重新绑定同一供应商后，按保存的线程
   映射恢复；绑定到其他供应商时拒绝直接恢复，未来由转录适配器决定是否迁移。
5. Profile 页面不再维护第二套外置会话侧栏，直接启用 ChatKit 内置历史视图，避免
   两套线程选择状态不一致。

## Consequences

- 会话目录在中央 PostgreSQL 不可用时仍能支持本 Manager 的列表与权限判断。
- 供应商线程不会因 Agent 重启而自动丢失，但供应商自身删除线程时，恢复会返回明确
  的不可用错误。
- 不同 Profile 即使绑定相同 Agent，也不会通过历史列表互相看到会话。
- 跨供应商继续同一会话不是线程 ID 复用，而是后续单独设计的转录迁移能力。
