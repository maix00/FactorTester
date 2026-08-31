# ADR-066：在容器运行时隔离服务器身份

## 状态

已接受。当前容器、端口和联邦身份的最终边界还要结合 ADR-068、ADR-069、
ADR-111 的现行实现检查；本文不定义业务 API。

## 背景

开发 Mac 可能同时运行 FactorTester 特征服务器和 Native Swift 客户端，二者
不能共用 WireGuard 私钥或节点身份。服务器还拥有多个 Git worktree，需要向
局域网暴露 Manager 7998 和生成物 7997，而不能公开动态执行端口。

公共主机的 WireGuard hub、PostgreSQL 控制库和 FactorTester 应用也必须能
独立恢复，构建或回滚应用不能拖垮控制库。

## 决策

1. 非公共 FactorTester 服务器使用带 WireGuard sidecar 和 FactorTester
   Manager 的 Compose 部署。只有 sidecar 挂载服务器私钥；Manager 可共享
   网络命名空间但不能读取私钥。每个狭窄路由接口使用独立的 key/address。
2. Manager 7998、生成物 7997 和 Manager 启动的测试进程共用网络命名空间，
   Compose 只发布 7998/7997；动态端口绑定 loopback，由 Manager 按 ADR-056
   代理访问。
3. 宿主机端口是部署参数，例如 staging 的 `27998 -> 7998` 和
   `27997 -> 7997`；联邦仍使用容器 WireGuard 地址上的固定 7998/7997。
   17998/17997 仅预留给独立的服务器间传输工作。
4. Git 公共仓库、Manager 源码 worktree、只读 `.settings`、Manager 状态和
   数据根目录按原绝对路径只读/读写挂载，以保持 linked-worktree 身份和数据
   亲和性。镜像只含 Linux 运行时与依赖；应用从明确挂载的源码 worktree
   导入并以 Git 提交识别版本，不挂载 Docker socket。
5. 配置的 WireGuard 接口是容器存活条件；对端握手和 PostgreSQL 不构成存活
   条件。广域网/控制库故障只影响相关请求，不能让本地 Manager 重启消失。
6. Swift 客户端使用独立的 native key/address，不加入服务器 Compose 命名空间。
7. 公共主机使用两个业务容器：`factortester-public` 拥有一个 WireGuard
   身份、Manager 7998、生成物 7997 和固定 8000 的 main 测试服务；
   `postgresql-control` 拥有另一身份、数据库卷和备份生命周期。公共容器不
   自动发现或启动 feature/issue worktree。
8. 两个公共 WireGuard 身份使用不同 key、子网和 UDP 监听端口。8000 不对外
   发布，公共 TCP 5432 保持关闭；同主机应用与数据库走未发布的 Docker 网络，
   授权服务器通过数据库专用隧道访问 PostgreSQL。
9. 内网部署使用宿主网络命名空间产生的短期 LAN 地址快照，不保存固定宿主
   IP，也不向客户端公布 loopback、容器桥或 WireGuard 地址作为 LAN 目标。
   动态生命周期由 ADR-111 定义。
10. 本地 feature/issue 部署可以在挂载 Python 变化时只重启 Manager 子进程；
    公共 main 禁用热加载，只通过有版本的部署和重启换代码。
11. 联邦 TLS 校验必须开启；公共 Manager CA/证书以只读方式挂载，镜像和部署
    配置均不得关闭证书校验。

## 后果

- 启停本地 Compose 项目会同时启停服务器隧道身份。
- LAN 客户端使用 Mac LAN 地址和发布的 7998/7997；对等服务器使用容器
  WireGuard 地址。
- 应用进程即使被攻破也不能直接读取 WireGuard 私钥，但可以使用已经建立的
  网络命名空间。
- Docker Desktop 是间歇性 feature 节点的前置条件，不应成为公共 hub 或
  PostgreSQL 权威的隐含依赖。
- 公共 FactorTester 更新与 PostgreSQL 重启/恢复解耦，独立 WireGuard 身份
  便于精细授权和撤销。
