# ADR 081：Manager 会话使用现有本地 SQLite 生命周期

## 状态

已接受。

## 背景

PostgreSQL 共享账户、组织、设备和配额权威，但 Manager 必须在 PostgreSQL 不可用时校验已经签发的会话。每个 Manager 已有由 `.settings` 配置的本地 SQLite，包含本地账户投影和其他 Manager 可见数据。

旧会话把 token 哈希和元数据写在 `sessions.json`，缺少 `created_at`/`last_seen_at`，每次变更都重写整个文件，清理和并发访问难以推理。新存储不应静默导入旧 JSON。

## 决策

1. 在 `Settings.CACHE_DB_PATH` 解析出的现有 SQLite 中增加 `manager_sessions` 表；不在 Manager 状态目录另建会话 SQLite。
2. 只保存 token 的 SHA-256 哈希、主体、角色、认证方式、签发来源、显示 alias、`created_at`、`last_seen_at` 和 `expires_at`，不保存原始 bearer token。
3. 绝对会话寿命 30 天；在既有 7 天刷新窗口内刷新；每分钟最多更新一次 `last_seen_at`；启动和周期访问清理过期或闲置 45 天会话。
4. 会话库是本地的，与 PostgreSQL 独立；中央库恢复可以恢复权威，但不是校验已签发本地会话的必要条件。
5. 应用不读取或迁移 `sessions.json`。SQLite 版本部署并验证后，从每个部署状态目录删除精确的旧文件；回滚审计可另行保留受限备份。
6. 设备密钥自动登录仍是独立的挑战/签名流程；成功设备校验再签发 Manager 会话，设备流程失败不能被诊断为会话库故障。

## 后果

本地账户回退和会话校验共享同一 Manager SQLite 边界；现有 SQLite 增加一个认证表和三个索引，不再使用会话 JSON 或原始 token。删除旧 JSON 会使旧 cookie 失效，用户需重新登录或完成设备认证。SQLite 损坏/不可用时本地回退应 fail-closed，不能把原始会话 token 交给 PostgreSQL 处理。
