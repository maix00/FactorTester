# ADR 082：Profile 注册通过 Manager 控制面投影

## 状态

已接受，纳入 Issue #208 实施。

## 背景

本地 Profile 在 Swift/CLI 客户端创建，包含执行元数据、Agent 绑定和本地研究引用。公共 Manager 不能挂载该客户端目录，因此 Profile 列表必须是存储在 PostgreSQL `control_profiles` 中的净化投影，PostgreSQL 不可用时使用 Manager 本地投影缓存。

执行服务与 Manager 是不同端点。Profile 可能使用 8000、7999 或 8141 等执行/worktree 端口；控制面投影必须发送到 7998。把执行 URL 当作数据库同步 URL 会让本地注册 Profile 在公共 Manager 不可见。

## 决策

1. `client profile create` 先写本地 Profile，再立即通过 Manager 7998 的 `/api/client/profiles/sync` 发送净化投影。Swift 优先使用单独配置的 `ManagerConfig` URL；CLI 只有兼容回退时才从同一主机和 scheme 推导 7998。
2. Manager 认证使用 CLI Keychain 中已有的 URL 作用域 bearer token，旧 cookie 会话只作兼容回退；客户端绝不直连 PostgreSQL。
3. Manager 或 PostgreSQL 故障不回滚本地 Profile 创建，返回 `server_visibility_pending`；Manager 可达而 PostgreSQL 故障时，本地安全投影缓存记录 pending，恢复后 flush。
4. Profile 投影和研究发布分开。Profile 同步后可被列出，不代表任何私有研究报告公开；只有显式上传且可见的 publication 进入共享研究目录。
5. 写投影前校验认证主体。过期本地主体是迁移问题，不能静默绑定到另一个账户。

## 后果

正常 PostgreSQL/控制面成功后，Profile 注册会在多个 Manager 可见；执行 URL 与报告/生成物引用保持原含义，不把执行端口改成 7998。离线本地创建可用，但远端可见性明确标记 pending。身份迁移仍是显式迁移操作，之后必须同步 Profile，不能通过网络读取或显示名称猜主体。
