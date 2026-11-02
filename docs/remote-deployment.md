# 远端 main 容器发布

远端 `main` 的 Manager 与控制库由 `factortester-public` Compose 项目管理：

- `factortester-public`：公开 7998 Manager、7997 生成物数据面和 51820/UDP FactorTester WireGuard；固定 8000 由 Manager 在容器内启动，不直接映射到宿主机。
- `postgresql-control`：运行控制库和独立的 51821/UDP PostgreSQL WireGuard；5432 只在容器私网和数据库隧道内可达，不向公网开放。

Keycloak、CouchDB、RabbitMQ 和独立计算/数据节点由各自的部署项目管理；它们不因此
成为另一个 Manager，也不随一次应用发布自动清除。

## 唯一发布命令

在干净的本机 `main` worktree 中运行：

```bash
./scripts/server/publish_public_main.sh
```

旧入口仍可作为兼容别名：

```bash
./scripts/push_main_to_server.sh
```

旧的 `--start` 参数仍可接受，但不再改变行为。默认执行完整发布；显式设置
`TR_PUBLIC_PREPARE_ONLY=1` 时仅准备产物和镜像，见下文两阶段发布。准备成功不能作为
新版本已切换或业务健康的证据。

## 同步事务

一次发布按以下顺序在前台同步完成：

1. 检查本机 `main` 已提交且工作区干净，并从本机推送 GitHub `main`。
2. 通过配置好的维护 SSH/阿里云 Session Manager，把缺少的 Git 对象直接推送到远端 `/opt/factortester/repo.git`。远端服务器不会连接或拉取 GitHub。
3. 按完整提交 SHA 建立 detached release，并利用 Docker 层缓存构建 `factortester-public:<SHA>`。
4. 备份 PostgreSQL，只切换 FactorTester 应用容器，不重建 PostgreSQL 容器。
5. 等待应用容器、7998、7997 和固定 8000 就绪，执行控制库结构与备份恢复检查。
6. 全部通过后记录 verified release 并清理超出保留数量的旧应用镜像；任一步失败则命令返回失败，并在已经切换时恢复上一版本。

因此，Git push、重载、服务恢复和验证是同一条命令的组成部分，不依赖人或 Agent 在推送后再执行第二条命令。默认维护入口 `launch-advisor` 使用阿里云 Session Manager，不要求安全组开放公网 22；本机 2222 转发只是一种可选的人工维护入口，不是服务器主动访问 GitHub的通道。

## 状态与回滚材料

- `/opt/factortester/repo.git`：由本机直接推送的远端裸仓库。
- `/opt/factortester-container/releases/<SHA>`：容器应用 release worktree。
- `factortester-public:<SHA>`：可回滚应用镜像。
- `/opt/factortester/deployments.log`：verified 发布记录。
- `/opt/factortester-container/backups/`：发布前控制库备份。
- `/etc/factortester-container/public.env`：root-only 生产配置；密钥仍分别保存在各服务端自己的受限目录中。

默认保留最新三个 verified 应用版本；可以用 `FACTORTESTER_PUBLIC_RELEASE_RETENTION` 调整。清理仅允许删除匹配 `factortester-public:<40 位 SHA>` 的旧应用镜像和相应 release，不删除 PostgreSQL 镜像、数据卷、其他 Compose 项目或 Docker 全局缓存。

本机原生构建在同一独占锁内管理自有 `target-reusable`，默认限额 6 GiB，可用
`NAUTILUS_TARGET_CACHE_MAX_GB` 调整。完整适配器构建的已编译依赖实测超过 4 GiB，
因此更小预算会丢弃这部分复用能力。超限时先
删除可重建的 `release/incremental`，保留已编译依赖；仍超限才移除该自有 target。
构建前和构建后均检查，已完成 wheel 保存在 target 之外。外部 target 超限时拒绝并
保持原样，不清理其他构建目录或正在运行的构建。该策略保留可用缓存，但不保证所有
源码变更均可免编译。

原生产物按构建身份保存。上传最多四个并发分块，每块不超过 4 MiB；传输前按
SHA-256 检查已完成文件或分块，不依赖文件大小或本地进度。SSH 断线与超时最多重试
三次，先写临时文件、校验后再原子替换；完整文件校验通过后批量删除分块。
失败时保留该构建的已验证暂存分块，重跑相同发布入口续传，不重新编译 wheel。
暂存也计入原生产物的总容量预算；不能借续传绕过容量、版本或校验门槛。

控制库首次迁移与校验见 [`remote-control-postgres.md`](remote-control-postgres.md)，当前生产访问应走独立 PostgreSQL WireGuard，不应重新开放公网 5432/TCP。

## 两阶段发布

需要在新镜像中先完成经过审核的数据或权限维护时，可在已获授权、干净且同步的 main
工作区运行相同发布入口，并设置 `TR_PUBLIC_PREPARE_ONLY=1`。入口仍验证 feat/main
包含关系、原生构建身份、产物校验和与主机容量；仅准备固定源码和新镜像，不停止旧
应用、不切换生产配置、不执行数据库变更，也不记录为发布成功。

维护应使用该固定镜像的独立运维进程、明确计划、保护配置和已验证备份，不将运维
权限写入常驻 Manager。完成真实对账后取消 prepare-only，再运行相同发布入口激活。
激活重新检查当前旧版本并制作新备份；准备与激活之间发生源版本或数据变化必须重新
核对。准备阶段的 `.next-<revision>` 配置仍属于受保护文件，不提供给客户端。
