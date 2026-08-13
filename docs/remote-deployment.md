# 远端 main 容器发布

远端 `main` 由 `factortester-public` Compose 项目管理，正式运行两个容器：

- `factortester-public`：公开 7998 Manager、7997 生成物数据面和 51820/UDP FactorTester WireGuard；固定 8000 由 Manager 在容器内启动，不直接映射到宿主机。
- `postgresql-control`：运行控制库和独立的 51821/UDP PostgreSQL WireGuard；5432 只在容器私网和数据库隧道内可达，不向公网开放。

## 唯一发布命令

在干净的本机 `main` worktree 中运行：

```bash
./scripts/server/publish_public_main.sh
```

旧入口仍可作为兼容别名：

```bash
./scripts/push_main_to_server.sh
```

旧的 `--start` 参数仍可接受，但不再改变行为。现在不存在“只准备、不重载”的发布模式；只要命令返回成功，新版本就已经完成切换，7998、7997 和容器内固定 8000 均已通过健康检查。

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

控制库首次迁移与校验见 [`remote-control-postgres.md`](remote-control-postgres.md)，当前生产访问应走独立 PostgreSQL WireGuard，不应重新开放公网 5432/TCP。
