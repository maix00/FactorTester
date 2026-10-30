## 网络拓扑 {#network-topology}

TradeResearch 区分控制面、执行面和数据面。**Manager** 提供身份验证入口、Job 权威 API、配置冻结、调度和结果登记；**Nautilus 执行节点**消费 Manager 指派的任务；**Data I/O** 在数据所在主机读取 Bundle 并管理有界 Arrow 缓存。它们可以同机部署为不同容器，也可以部署在不同主机。

## 客户端与 Manager {#clients-and-manager}

电脑网页端、移动端和 CLI 通过用户选择的 Manager 发起配置与任务操作。Manager 的 Keycloak realm 管理该 Manager 的登录和访问权限。多个 Manager 之间发现服务或传递任务时，仍由服务端身份和明确的授权边界控制。

## 执行节点 {#manager-managed-execution}

执行节点是 Manager 可调度的远程服务。节点通过受限身份连接所属 Manager 的队列，并按冻结的 RunSpec 与数据 Bundle 执行。执行节点不能把自己的本地计算身份当作用户身份，也不拥有 Job 权威数据库。

## 数据专用节点 {#data-only-node}

数据专用节点可以只运行 Data I/O 和本地数据 Bundle，不安装 Manager 或 Nautilus worker。当前同主机复用 Arrow 缓存使用本机文件页与 Unix 文件描述符传递；跨主机 Arrow Flight 数据读取尚未实现，因此不能把远程数据专用节点报告成已可用于回测的数据源。

## 桌面用户的本机运行时 {#personal-desktop-runtime}

桌面客户端可以在当前用户明确授权并安装后，在这台个人电脑上启动本机运行时。该运行时只供当前用户自己的测试或交易；它**不会向 Manager 注册，不参与 Manager 的执行节点发现或自动选址，也不会接受同一或其他 Manager 派发的任务**。Manager 只负责 Keycloak 权限检查和提供经过签名校验的下载包。本机数据、缓存和运行状态属于本机用户会话。

## 图例与实现状态 {#legend-and-status}

页面中的实线表示当前代码已经支持的主机内组件关系；虚线表示仍需实现和验收的跨主机数据通道。容器同在一台机器上不意味着其进程内存可以直接共享；当前 Data I/O 通过有界 Arrow 文件缓存和同机文件映射减少重复读取。
