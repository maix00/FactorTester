# 远端 main / Manager 部署

远端每台主机由三个 systemd 单元组成：

- `factortester-manager.service`：7998，对等控制面和跨主机唯一入口；
- `factortester-main.service`：8000，远端 `main` API；
- `factortester-main-daemon.service`：与 8000 配套的任务队列 daemon。

推送脚本使用 Git 原生 push，只传输远端 bare repo 尚未拥有的对象；服务器按完整提交 SHA 建立 `releases/<SHA>` worktree，再原子切换 `current`。默认命令只同步、安装依赖、准备 release 和 systemd 文件，不启动任何服务：

```bash
./scripts/push_main_to_server.sh
```

确认要启动后才使用：

```bash
./scripts/push_main_to_server.sh --start
```

部署会保留以下版本记录：

- `/opt/factortester/repo.git`：远端完整 Git 历史；
- `/opt/factortester/current/.deployment-revision`：当前 release SHA；
- `/opt/factortester/deployments.log`：部署时间、SHA、旧 release 和健康状态。

数据设置位于 `/opt/factortester/releases/.settings`，默认指向 `/data`，其中 `LocalCNFutures` 映射到 `/data/sources/LocalCNFutures`。除非设置 `FACTORTESTER_UPDATE_SETTINGS=1`，脚本不会覆盖已有数据设置。

控制库的 PostgreSQL 一次性初始化见 [`remote-control-postgres.md`](remote-control-postgres.md)。远端 PostgreSQL 使用 `5432/TCP`；本机 Manager 只向该端口发起出站连接，不需要新增本机数据库监听端口。

脚本首次准备时会在 `/opt/factortester/manager-state/` 生成权限为 600 的 Manager capability 和联邦登记令牌，并在终端打印登记令牌。将它填入另一台机器的超级管理员“远端挂载”设置；跨主机请求始终走对端 7998，不直接访问对端 8000。
