# ADR-126：Profile Agent 文件系统隔离与保留的助手草稿

## 状态

已接受；当前实现以 `profile_agent_sandbox.py`、Agent app-server 启动器和
工作区资源浏览器为准。

## 背景

服务器 Profile Agent 过去虽然有 Profile 工作目录和 Codex home，却与其他
Profile 使用同一 Unix 用户，shell 因而可能通过绝对路径读取共享 `/tmp`、
兄弟 Profile 或服务器存储。页面助手候选 JSON 也曾被随意写到 Profile 根或
临时目录。

## 决策

1. Agent 只能在 fail-closed 的 Bubblewrap mount namespace 中启动。Profile 工作
   区是 `/workspace` 唯一可写挂载；`/tmp` 是独立 tmpfs；服务器用户存储和
   兄弟 Profile 不挂载；
2. 运行时、FactorTester CLI、Codex、证书和选定 Skill 只读挂载；网络可以保留，
   因为 Agent 需要调用已认证的 Manager 和模型提供方；
3. 页面助手草稿通过认证 CLI/API 创建，作为平铺 JSON 保留在
   `manifests/assistance-drafts/`；服务器生成身份、页面 revision、内容哈希、
   状态和时间戳；
4. 草稿状态为 `draft`、`validated`、`queued`、`applied` 或 `rejected`。应用
   成功不自动删除；配额达到上限时警告并拒绝新草稿，不静默删除旧草稿；
5. 复用现有 Profile 工作区资源浏览器列出、下载和由所有者明确删除这些文档，
   不新增文件管理器、认证系统或存储协议；
6. 草稿记录来源 tab 只用于审计，可在页面类型、助手协议版本和文档 schema
   兼容时应用到当前活动 tab。应用使用目标 tab 的当前 revision，不把来源
   revision 带入新 tab；不同页面类型仍然拒绝。

## 后果

Profile 相对当前目录不再被视作安全边界；绝对路径扫描不能到达兄弟 Profile
或共享临时空间。Agent 使用结构化草稿协议，文档在用户明确删除前可见且可
恢复。关闭配置 tab 不会让草稿失去归属，兼容的新 tab 可以继续应用。没有
Bubblewrap 的部署拒绝启动服务器 Profile Agent。
