# ADR 079：控制数据库故障期间的 Profile 投影缓存

## 状态

已接受。

## 背景

PostgreSQL 是账户、组织、层级、配额、设备和同步 Profile 元数据的共享权威，但控制库暂时不可达时，Manager 仍应提供本地应用状态。公共 Manager 通常不能访问用户设备上的 Client 根；如果没有本地投影，就无法区分“空的 PostgreSQL 响应”和“尚未同步的 Profile”。

## 决策

1. 每个 Manager 在自己的 `state_root/profile-cache` 下保存有界、无源码的 Profile 投影缓存。缓存独立于 Client 根，以 owner-only 权限原子写入。
2. 文件按认证主体 SHA-256 摘要命名，只含净化后的 Profile 元数据和待同步 Profile ID；绝不写入本地路径、源码、凭据、会话引用或 access token。
3. Profile 同步先写安全本地投影；PostgreSQL 成功标记 `status=synced`，不可用标记 `status=pending`，不伪装成全局投影已提交。
4. Profile 读取合并本地 Client 数据、安全缓存和 PostgreSQL 行。pending 项在 PostgreSQL 恢复后重试 upsert，失败时缓存仍可读。
5. CLI 暴露 `factortester client profile sync [PROFILE_ID]`。引导流程使用同一认证同步路径；Manager/数据库故障只使远端可见性 pending，不使本地 Profile 无效。
6. 缓存不能把 PostgreSQL 变成安全变更的可选权威。已有 Manager 会话可按正常过期继续；新的密码/设备认证、注册、组织或配额变更在控制库不可用时必须降级失败，不能本地接受后与其他服务器静默分叉。

## 后果

公共或本地 Manager 可以在 PostgreSQL 故障期间展示已经同步的 Profile。恢复是幂等的：下一次读取或显式同步成功后清除 pending。过期缓存最多显示旧元数据，不能授予新账户、设备、配额或组织权限。将来可把模式扩展到其他有界只读投影，但原始凭据和权威撤销不能放进无界离线授权缓存。
