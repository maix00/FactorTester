# ADR 101：本机 Docker 内网服务器的分层生命周期

## 状态

已接受。

## 背景

本机内网 FactorTester 由 Docker Compose 管理，但 Manager、Manager 管理的
测试服务和 Docker/WireGuard 容器不是同一个生命周期。过去这些操作分散在
Compose、Manager API 和入口脚本中，容易把“代码热重载”“服务重启”和“容器
重建”混为一谈。

## 决策

1. 本机宿主机的 `scripts/server/factortester_container.sh` 是运维入口，属于
   仓库的部署工具层，不属于 Manager API、Swift 客户端或任何业务服务容器。
   它通过本地 Compose 环境文件选择目标部署，不挂载 Docker socket 到应用容器。
2. 本机 feature/issue 服务默认启用 `FACTORTESTER_HOT_RELOAD=1`。入口脚本中的
   `watchmedo` 只监视挂载的 Python 源码并重启 Manager 子进程；公网 main 使用
   独立 Compose 项目并固定关闭热重载。
3. Manager 和 WireGuard 容器使用 `restart: unless-stopped`。进程或容器异常退出
   时由 Docker 自动恢复；Manager 重启后依据本地持久化的 service intent 恢复此前
   应保持运行的测试服务。健康检查仍由 Compose `--wait` 和运维验证显式确认。
4. Manager 容器生命周期由宿主机入口控制：
   - `manager-reload`：重启现有 Manager 容器，不构建、不重建；
   - `manager-restart`：只重建 Manager 容器，不重建 WireGuard；
   - `stack-restart`：重启整套本机 Compose 栈。
5. 测试服务生命周期必须通过 Manager 7998 的 opaque `instance_id` 控制，宿主机脚本
   只按端口解析唯一实例，不直接操作测试进程：
   - `service-reload PORT` 对应 `restart-api`，只替换 API 进程并保留 Job daemon；
   - `service-restart PORT` 对应 `restart-bundle`，排空后重启 API 与 daemon；
   - `service-start/stop/force-stop PORT` 控制端口服务的开关。
6. 所有成功的服务操作必须等待 Manager 返回的实例状态恢复，不能只根据 HTTP
   `POST` 已接受就报告成功。7998 和 7997 的连通性由 Compose health/status 和
   发布验收分别验证。

## 后果

- 修改本机 Python 源码通常无需手工重启 Manager；需要强制恢复时可以选择只重载
  Manager、重建 Manager 或重启全栈。
- 重启单个测试服务不会误重启数据库、WireGuard 或 Manager，也不会把已停止的服务
  隐式启动。
- Docker 的 `restart: unless-stopped` 负责进程/容器退出恢复，不等于对“进程仍活着
  但业务失去响应”的 unhealthy 状态自动重建；后者由健康检查与运维入口报告，避免
  在没有人工确认时破坏正在运行的任务。
