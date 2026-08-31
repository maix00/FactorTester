# ADR 113：Profile Agent 会话目录与内置历史视图

- **状态**：已接受
- **日期**：2026-08-19

## 背景

同一个服务器 Agent 可能先后或同时服务多个研究身份。供应商的
`provider_thread_id` 只表示 Agent 运行时的线程，不应直接作为浏览器历史列表的
权限边界。直接转发供应商的 `thread/list` 也无法表达 FactorTester 的用户与
Profile 归属。

FactorTester 使用 ChatKit 的内置历史视图来完成会话列表、切换、新建、重命名和
删除；Manager 负责提供经过 Profile 权限过滤的线程协议。

## 决策

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
6. Provider thread 是会话正文的唯一权威来源。Manager SQLite 只保存会话目录、
   Profile 归属、权限与 `provider_thread_id`/`provider_id` 绑定，不保存消息、工具
   调用或推理摘要副本；旧的 `manager_agent_conversation_items` 表在切换时移除。
7. 会话所属 Manager 通过 Codex `thread/read(includeTurns=true)` 读取本地 Provider
   thread，并在该 Manager 上转换成 ChatKit 原生 item。普通与只读视图使用完全
   相同的转换结果；只读差异只来自 locked thread 与变更接口拒绝。
8. 历史按完整 Provider turn 分页。默认仅返回最近 10 个 turn；游标锚定本页最早
   turn 的稳定 ID，新增 turn 不会移动后续“向上读取”边界。Codex app-server 当前
   没有 turn 分页参数，因此所属 Manager 读取 thread 后切页，但跨服务器与浏览器
   只传当前页，不复制或缓存正文。`items.list` 遵循 ChatKit 的 `order=desc|asc`
   协议；默认 `desc`，最新 item 在前，向上翻页继续读取更旧的完整 turn。
9. 默认“结果”视图只返回用户提问与 `agentMessage.phase=final_answer`；用户切换到
   “过程”后才按页读取可见 reasoning summary、commentary、命令、工具、搜索、
   文件变更、计划与错误。原始 reasoning content 不属于可展示内容。
10. Agent 停止或 claim 已释放时，会话所有者仍可读取历史。Manager 为历史读取启动
    可短时复用的只读 app-server；它不检查模型网络、不启动 CC Switch、不签发
    FactorTester Agent 会话，也不改变 Agent 生命周期。

## 后果

- 会话目录在中央 PostgreSQL 不可用时仍能支持本 Manager 的列表与权限判断。
- 供应商线程不会因 Agent 重启而自动丢失，但供应商自身删除线程时，恢复会返回明确
  的不可用错误。
- 不同 Profile 即使绑定相同 Agent，也不会通过历史列表互相看到会话。
- 跨供应商继续同一会话不是线程 ID 复用，而是后续单独设计的转录迁移能力。
- 请求方 Manager 不保留正文缓存；源 Manager 离线时明确报错，不展示可能过期的
  历史副本。
