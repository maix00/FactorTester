# ADR 080：离线登录使用现有本地 SQLite 与 Manager 作用域身份

- **状态**：已接受
- **日期**：2026-08-14
- **范围**：Manager 密码登录、注册和账户身份

## 背景

PostgreSQL 是用户、组织、层级、配额和注册设备的权威控制库。即使 PostgreSQL 或公共 Manager 故障，内网 Manager 仍可能通过 7998 直接可达。每个部署节点已经有由 `.settings` 配置的统一本地 SQLite，其中 `accounts` 表包含本地账户行和 PBKDF2 密码校验值。

不同 Manager 不一定拥有同一个注册命名空间：内网 feature Manager 管理 `GTHT`，公共 main Manager 管理 `default`。没有显式部署覆盖时，从 Manager 角色选择作用域。规范用户名格式为 `organization@alias@numeric-suffix`；alias 区分大小写，不能含 `$` 或 `@`。

## 决策

1. PostgreSQL 可用时，密码和设备认证继续使用 PostgreSQL 权威。
2. 精确查找完整规范用户名；仅有 alias 时，只在当前 Manager 作用域内解析；`organization@alias` 是作用域简写。歧义 alias 必须提供完整用户名，比较区分大小写。
3. 注册和离线注册要求目标组织属于 Manager 作用域；空组织使用第一个作用域组织。本地 SQLite 必须可写，首次本地写入不要求 PostgreSQL。
4. 密码认证抛出 `ControlDatabaseError` 时，Manager 读取现有 SQLite `accounts`；密码校验值有效即可登录，缺失账户或错误密码拒绝。
5. PostgreSQL 不可用期间注册时，在现有 `accounts` 表事务中写新行和 `pending_account_registrations` outbox 行；下一次可达 PostgreSQL 的请求再懒性推送。该离线注册是普通用户，绝不是本地 bootstrap 超级管理员。
6. 不创建认证快照、租约元数据或设备缓存表；outbox 只用于明确创建的本地注册的最终投递。
7. 设备白名单读取、设备挑战、注册和撤销仍要求 PostgreSQL；故障时返回 unavailable，而不使用过期设备数据。
8. 密码、角色/层级和配额变更在 PostgreSQL 已配置时不写本地 SQLite，必须走控制库管理路径。
9. 本地回退只捕获控制库可用性失败，不用于错误密码、禁用公共设备或其他授权拒绝。

## 一次性身份迁移与清理

旧账户 `18717974771` 由 `scripts/migrate_account_identity.py` 迁移。默认 dry-run；应用前必须提供显式哈希 manifest、`--delete-other-users`、SQLite 备份和 `pg_dump` 备份。迁移保留密码 salt/verifier，把规范身份改成 `GTHT@MaxJJW@<random-digits>`，并更新两套数据库中的组织、层级、Profile、配额、设备、授权和源码引用。

应用步骤删除其他活动中央账户以及明确归用户所有、本地 SQLite 中不为空的其他列值，并归档不再出现在 `accounts` 的孤立行；`__public_jobs__`、`__public_graph__` 等公共服务主体保留。`device-registry.json`、`device-authorizations.json`、`sessions.json` 可通过一个或多个 `--state-root` 纳入；设备公钥和会话 token 哈希保留，只改用户名/主体。浏览器 IndexedDB 私钥对服务器不可见，不能复制或重建。

只有显式提供 `--user-root-parent` 才触碰主体工作区目录；目标目录改名，其他活动子目录移入备份中的 `user-roots/`，命令不能猜数据盘位置。

迁移必须在拥有数据库 WireGuard peer 的 Manager 网络命名空间执行。当前内网 Docker 节点用 Manager 容器数据库接口（10.79.0.2）连接远端数据库（10.79.0.1:5432）；FactorTester 联邦地址（10.77.0.1）不是 PostgreSQL 端点，Mac 上的 host 测试不是有效数据库路径测试。本地 127.0.0.1:2222 SSH/Session-Manager 转发只是运维传输，不是公共数据库或应用端口。

## 后果

只要 Manager 本地 SQLite 有该账户，内网密码登录可在中央数据库离线时继续；公共访客和设备管理在 PostgreSQL 故障时仍 fail-closed。本地账户变更和中央撤销不会由该回退即时传播，控制库恢复后重新成为权威。不增加额外端口、后台认证同步器、认证/设备同步表或缓存清理进程，只有显式注册 outbox 行。
