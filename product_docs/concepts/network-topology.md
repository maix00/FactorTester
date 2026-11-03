## 网络中的角色 {#network-topology}

系统按控制面、执行面和数据面分工。Manager 是业务 API、身份校验、RunSpec 冻结、Job 状态和结果引用的权威；Nautilus 执行节点消费 Manager 派发的任务；Data I/O 在数据所在主机读取 Bundle，并提供有界 Arrow 批次和缓存。

执行节点、数据设施可以与 Manager 同机，也可以部署在独立主机。一台主机可运行多个服务，但进程内存不因此共享；不同服务的数据接口和资源限制仍应分别定义。

## 客户端能连接到哪里 {#clients-and-manager}

电脑网页端、桌面客户端、移动端和 CLI 都是客户端，不会因安装了本机运行时就自动成为服务器节点。每个机构有自己的内网 Manager；公网有获授权访问的 Manager。用户可以连接所属机构的内网服务，并在具备公网登录权限时连接公网服务；其他机构的内网服务不可因“网络可达”而直接连接。

每台 Manager 使用自己的 Keycloak Realm 和授权策略。客户端会话按 Manager 地址隔离；相同用户名或显示名称不代表同一身份。多个 Manager 之间发现对象、同步身份或传递任务，必须由服务器验证主体、对象引用、目标能力和明确授权。

## 执行节点与数据节点 {#manager-managed-execution}

执行节点由所属 Manager 调度，凭受限服务身份连接队列，并按 RunSpec 和本地安装的 Bundle 工作。它不拥有 Job 数据库，也不能把本地计算身份当作提交用户身份。若节点权限、运行版本或数据能力不匹配，Manager 应拒绝派发并返回原因。

数据专用节点可以只部署 Data I/O 和本地 Bundle，不安装 Manager 或 Nautilus worker。同机数据读取可复用文件页和有界缓存；跨主机 Arrow Flight 尚未接通，不能把远端数据节点描述为已可用于回测的数据源。

## 桌面用户的个人运行时 {#personal-desktop-runtime}

个人电脑上的 Nautilus/Alpha 运行时只供当前用户自己的测试或交易。它不会向任一 Manager 注册，不参与远程节点发现和自动选址，也不接受 Manager 派发。桌面安装包须经 Manager 授权和签名校验；包下载链路尚未完成时，不能将“允许下载”写成“已经可用”。

## 端点与数据类别 {#network-endpoints-and-data}

| 网络路径 | 发送方 → 接收方 | 传递内容 | 边界 |
|---|---|---|---|
| 客户端控制面 TCP 7998 | React、Swift、CLI → 当前选定 Manager | 登录会话、业务 JSON、预览/提交、任务状态、对象访问授权请求 | 每个 Manager 独立验证主体和权限；浏览器不直连 Keycloak 内部地址或测试服务端口 |
| 客户端数据面 TCP 7997 | 客户端或 Manager 本机传输代理 → 当前 Manager 数据面 | 经短期 bearer 授权的文件字节 | bearer 限定对象、操作、主体、范围与有效期；不发送 Manager 会话 Cookie |
| Manager 控制同步 TCP 7998 | Manager B 与已登记 Manager A | account-domain outbox/cursor 与稳定对象/版本索引；已启用时也承载独立的 Job 投影 | 小型、分页元数据；各域有自己的权限、cursor 和冲突策略。身份变更流采用独立合同，尚未完成两端端到端验收 |
| WireGuard peer control TCP 17998 | 已登记 Manager 节点之间 | 签名服务代理、Transfer/Attempt 上下文、短期 peer ticket | 仅私有 overlay；不向浏览器公开，也不作为普通客户端 API |
| WireGuard peer data TCP 17997 | 请求所有者节点与来源/目标节点 | 源码、附件、提交文件和 Artifact 等受授权字节 | 端点、对象身份、长度、SHA-256 和传输 Attempt 必须核验 |
| Manager → RabbitMQ → worker | Manager dispatcher → 目标队列 → 执行节点 | `job_id`、`attempt`、deployment/service 路由和规范 hash | 小型版本化信封；行情数组、源码正文和结果文件不进入消息 |

不同 Manager 之间并非一条无差别的“同步线”。例如，因子版本索引走账户域元数据通道，因子源码仍由来源节点经对象数据面提供；报告章节投影和 Evidence 文件也各走自己的授权路径。回测 worker 只读取它所在节点可访问的 Bundle；跨主机 Arrow Flight 仍未接通。Manager 软件版本可以不同，互通判断依据端点、权限、API 与节点能力合同，不能要求设备以版本号相同来改变网络角色。

## 实现状态与版本 {#legend-and-status}

图中实线表示已经实现的连接；虚线表示规划中或未完成端到端验收的路径。客户端、Manager、执行节点和数据节点可以采用不同版本。验收按目标 Manager 公布的能力和接口契约判断；版本号相同本身既不证明拓扑兼容，也不是网络角色变更的理由。
