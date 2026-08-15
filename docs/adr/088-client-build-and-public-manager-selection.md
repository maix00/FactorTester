# ADR 088: 客户端构建与 Docker 服务解耦，并默认选择最近公网 Manager

## 状态

已接受

## 背景

内网 FactorTester 已由 Docker Compose 管理。Manager 7998、生成物数据面
7997 和 Manager 管理的测试服务属于服务器运行时；FTClient 的 Xcode 构建、
签名、Sparkle 发布属于客户端发布运行时。让客户端发布脚本先重启本机 Manager
再构建，会把两个生命周期错误地耦合起来，也会让宿主机上的重启逻辑与 Docker
容器实际状态不一致。

Swift 客户端还需要默认连接公网 Manager。公网地址可能变化，也可能存在多个公网
节点，客户端不能内置 IP 或自行推断地址。

## 决策

1. `scripts/build_and_run.sh` 只停止/构建/启动 FTClient；它不执行 Docker
   Compose、Manager restart、测试端口关闭/恢复或 WireGuard 操作。
2. `scripts/release/publish.py` 与 `factortester-manager client release` 只负责客户端
   构建、签名、发布和回读，不再要求 `--service-port`，也不调用
   `restart_release_service`。服务器源代码、镜像和服务重载由独立的 Docker/部署
   入口负责。
3. Manager 的 `/api/server/network-info` 返回服务器排序后的
   `public_server_targets`，以及用于客户端测速的未截断公网候选和带机构范围的
   `internal_server_targets`。客户端的引导地址与选择算法由 ADR 090 规定。
4. 自动选择只切换 Manager 控制面，不隐式创建公网设备白名单登记。已有原生设备密钥
   可以尝试挑战认证；没有密钥或认证失败时仍停留在服务器规定的合规/登录流程。
5. 用户在服务器设置中手动保存地址后，选择来源变为 `manual`，自动发现不覆盖用户
   的显式选择。

## 后果

- 本机 Docker Manager 不在线不会阻塞 FTClient 构建；客户端发布可以在没有服务器的
  环境完成。
- Docker 服务的热重载、镜像构建和容器重启可以独立回滚，不会被客户端发布隐式触发。
- 多公网节点只需更新 Manager 的目标投影；只有唯一的公网引导 IP 变化时才需更新
  Swift 构建常量。
- 具体的引导、测速缓存、机构内网优先级和手动重新选择见 ADR 090。
