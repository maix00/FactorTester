# ADR 087：共享账户域同步

## 状态

已接受，已在 Issue #214 实施。

## 背景

多个 Manager 必须暴露同一用户的账户元数据，同时在中央 PostgreSQL 暂时不可用时仍可使用。产品分类只是一个例子，同样的问题也适用于产品组、已注册 Profile、因子注册、偏好和其他小型账户记录。如果每个功能都在 Manager 之间直接复制，就会形成各自的冲突和重试协议。

## 决策

使用一个账户域同步协议，并为每种实体提供 adapter：

1. PostgreSQL 是跨 Manager 的账户元数据权威；每个 Manager 现有账户 SQLite 是持久本地镜像和离线工作副本。
2. 本地镜像通过共享 outbox 和 pull cursor 记录待处理变更。操作幂等，并带实体类型、稳定实体 ID、主体 ID、源 Manager ID、payload revision 和 tombstone 状态。
3. 读取优先使用本地镜像；PostgreSQL 可达时按需拉取更新 revision。本地写入立即持久化，能推送时同步推送，否则留在 outbox；不要求实时复制。
4. 稳定全局用户 ID 和实体 ID 是合并键；用户名和显示 alias 只是标签。并发编辑使用乐观 revision 检查，遇到冲突显式返回，不静默覆盖较新数据。
5. 大型或服务器本地对象（因子源码、生成物、提交物、研究文件）不经过 PostgreSQL。其元数据和所有权 manifest 走账户协议，字节走认证的 7997/WireGuard 数据面。研究 publication 元数据包含所有者、Profile、可见性、授权用户、generation、投影哈希和存储 Manager；撤销 publication 写 tombstone，不删除远端副本字节。
6. 运行时状态不做账户同步：Manager 会话、在线节点能力、提供方在线状态和路由选择保持本地/联邦投影。

## 后果

产品分类可在 PostgreSQL 离线时创建，恢复后经懒同步在其他 Manager 可见；数据源 bundle 与其 provider 保持不同语义；新增账户功能只需新增 adapter 和 schema 投影，不再新增 Manager 间同步协议。同步有意是懒性的：受影响视图经过主体级冷却后拉取并 flush outbox，故障期间本地登录和元数据读取仍可用，远程可见性等待恢复。

`account_domain_entities`、`account_domain_outbox`、`account_domain_cursors` 和 `account_domain_conflicts` 位于现有 Manager SQLite，对应 PostgreSQL 表只是元数据权威；不增加第二个 SQLite、端口或 peer listener。产品分类/组、因子集合/参数配置、因子源码 manifest、Profile、用户/组织/层级、因子研究任务元数据和共享研究 publication 元数据共用该 adapter seam；源码、报告投影、资产和生成物字节留在所属存储 Manager。Job 生成物/提交物继续走 7997/WireGuard 数据面，公共研究 read-through 字节路径仍需单独的研究对象 data-plane adapter。
