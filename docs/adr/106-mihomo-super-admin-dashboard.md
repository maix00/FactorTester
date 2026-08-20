# ADR 106：通过 Manager 7998 提供受控 Mihomo Dashboard

## 状态

已接受。

## 背景

传统 Dreamacro Clash 已停止维护。本机和公网 FactorTester 仍需要一个
可选的管理员网络代理控制面，但不应为代理、控制器或 Dashboard 增加新的
公网入站端口，也不应把控制器密钥交给浏览器。

## 决策

1. 使用 MetaCubeX Mihomo 二进制和官方 `metacubexd` 静态 Dashboard，并在
   FactorTester 镜像中固定版本与归档 SHA-256。Dashboard 只作为静态资源随
   应用发布，不在运行时访问 GitHub。
2. Manager 7998 增加一个仅超级管理员可见的主页模块。模块只提供启动、停止
   和官方 Dashboard iframe；生命周期状态由 Manager 的本地
   `MihomoSupervisor` 管理。
   `start` 只有在 9090 控制器和 7890 混合代理监听均可连接后才报告成功，避免
   Agent 在代理尚未就绪时立即发起请求而得到瞬时连接错误。
3. Mihomo 的 REST/WebSocket 控制器绑定 `127.0.0.1:9090`，混合代理绑定
   `127.0.0.1:7890`。浏览器不能直接访问这两个端口；Manager 在已认证的
   7998 请求中执行有限的同源转发。
4. Dashboard 的配置从部署密钥目录提供。Manager 启动前复制为 `/state` 下
   的服务用户私有文件，并强制覆盖 loopback、关闭 LAN、TUN 和控制器密钥，
   使订阅配置不能改变网络暴露边界。缺少配置时服务保持停止。
5. Dashboard 只允许读取控制器数据、关闭连接和切换代理；任意配置写入、
   外部控制器地址和新增监听器都不通过该桥接暴露。
6. 不新增安全组规则。公网容器继续只发布既有的 FactorTester 7998/7997
   与 WireGuard 端口；Mihomo 9090/7890 以及 Dashboard 代理路由均复用
   Manager 认证边界。
7. 每个模型 Provider 显式保存 `direct` 或 `manager_proxy` 网络策略。
   `direct` 永远不受 Mihomo 生命周期影响；`manager_proxy` 只在 Mihomo
   已运行时向该 Profile 的 CC Switch 上游连接注入标准代理环境。代理不可用
   必须明确失败，不得静默回退直连。Manager 自身、其他 Provider 和其他服务
   不继承该代理。

## 后果

- 管理员可以在手机或浏览器的现有 7998 页面打开原生 Mihomo Dashboard，
  并在需要时启停；普通用户和访客不会看到该模块。
- Manager 进程或容器重启后 Mihomo 默认保持停止，避免无人值守地启用代理。
- 选择 `manager_proxy` 的 Provider 在重启后必须等待管理员重新启动 Mihomo；
  这属于显式的 Provider 网络状态，不会改变为直连。
- Dashboard 依赖本地 Mihomo 配置和二进制；配置错误只影响该模块，不阻断
  FactorTester Manager、7997 数据面或 PostgreSQL 容器。
- 代理流量仍由宿主/容器自身发起。该模块不是对外开放的公共代理入口，
  不允许把 7890、7891 或 9090 加入安全组。

## 参考实现

- Mihomo releases：<https://github.com/MetaCubeX/mihomo/releases>
- Official Dashboard：<https://github.com/MetaCubeX/metacubexd>
