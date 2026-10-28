# ADR-188：执行节点、来源安装与可移植数据需求

状态：拓扑及身份合同确定；中立匹配合同与部署环境修正已实施，远程调度尚未实施。
跟踪 #448；取代 ADR-187 将 Manager server_id 当作缓存设备身份的单节点假设。
审计基线 215b2619b，2026-10-28 Asia/Taipei；工作区有其他所有者的未提交修改。

## 用户确定的拓扑

一个 Manager 管理本机或远程的执行节点。执行节点安装测试服务与数据源，不要求另起
Manager。不同执行节点安装的同一 Bundle 是不同数据源，包括同一物理主机上的两个
独立节点。Bundle 包的逻辑 ID 不因换机而改名；具体来源身份包含节点与安装身份。
RunSpec 与具体来源解耦，以同一产品、同一 Bar 类型的数据需求匹配兼容安装。

| 身份 | 责任与生命周期 |
|---|---|
| manager_id / authority | 认证、权限、Job 权威与调度控制域 |
| node_id | 稳定执行环境身份；独立节点不得共用，不从 IP/端口/hostname 推导 |
| service_id + deployment_ref | 节点内服务及其准确实现版本；端口仅为路由属性 |
| bundle_id + version + metadata fingerprint | 包及适配实现元数据；不是行情内容摘要 |
| installation_id + node_id + authority + owner | 节点上的安装；同包多安装显式区分 |
| source_ref | 安装及 member 的稳定引用，包更新不改变安装身份 |
| storage domain | 同内核、同底层文件及可信缓存的作用域；既不等于 Manager，也不等于节点 |

同一主机可以有不同节点，共享缓存域也不会合并来源身份。Docker Desktop 虚拟机与
macOS 原生进程属于不同内核域。声明相同 storage domain 不能自动证明物理页共享。
Compose 使用 TR_EXECUTION_NODE_ID 声明节点，TR_SHARED_STORAGE_ID 映射缓存 device；
FACTORTESTER_SERVER_ID 继续只表示现有控制权威。未执行部署或改写现存环境文件。

## RunSpec、匹配与执行冻结

RunSpec 的 BarRequirement 只保存规范产品引用、instrument-independent Bar spec、
价格口径、Bar 时间/可用时刻合同、所需字段与输入区间（包括 warmup）。它不含 Bundle、
节点、本地路径或源修订。相同需求在不同节点具有相同 requirement_ref。

同一产品及 Bar spec 构成候选等价基础；raw/复权、LAST/BID/ASK、Bar 起止/可用时刻不一致
不得冒充相同语义。Bar spec 使用来源声明的规范完整类型，不能只比较 MIN1 显示标签。
匹配不验证价格逐字节相等，也不因匹配成功自动复用另一来源的缓存。

1. 既有认证的服务投影提供当前可用、授权可见的安装与能力元数据；目录不实例化插件、
   不读远程路径、不查询全部行情。元数据覆盖未知时不作为可直接执行候选。
2. 平台按测试类型、节点、产品、Bar 语义、字段与覆盖范围过滤；未知或不足的覆盖需要
   源侧有限预检后重新规划，不在这里猜测覆盖或静默选另一个来源。
3. 显式选择具体 source_ref。多个兼容来源都保留；重复身份/不兼容选择拒绝，不能按
   名称或列表第一项回退。选择与 RunSpec 分开进入 ExecutionPlan。
4. BoundBarInput 保存原需求、服务部署与安装包版本/指纹。执行端在加载前按当前已授权
   投影重新核对。包升级、部署变化、离线、覆盖缩小使原计划失效。
5. 每轮读回执记录源自己提供的观察修订及读取范围。可变行情依 ADR-158 由源管理；不强制
   引入跨运行字节冻结。来源若提供快照则按其专有引用处理。

traderesearch_data/execution.py 是标准库中立合同，匹配仅运行于规划/执行准入阶段，
不进入逐 Bar 路径；不新增数据库、注册中心、调度器或另一个行情加载器。权限过滤及
注册真实性由现有 Manager/队列接入负责，调用纯合同函数不授予权限。

## 后续实施顺序与验收

本批尚未把新合同接入正在修改的 RunSpec 编译器、实际分发或前端，不把新增类当作
远程拓扑已运行。现有 FrozenBundleInput 仍是旧接线；后续用本合同替换来源选择职责，
只保留源专有 mapping/related-members 回执，不能长期并存两套安装匹配权威。

1. 在现有节点/服务注册上区分 manager/node/service/deployment，并投影安装清单；更新
   必须带版本、心跳期限和撤销语义。Owner/权限变化时使候选及未执行计划失效。
2. RunSpec 编译输出需求，ExecutionPlan 绑定具体安装；预览、提交、重试及 worker
   加载共用上述合同。每种输入需全部匹配，不能只因测试类型兼容就接受服务。
3. 复用 Celery/RabbitMQ 和现有 Job 权威提供认证的领取、输入/源码获取、状态和结果
   提交。远程节点不能挂载 Manager SQLite；跨节点传输须明确记账与授权。
4. 把 host memory admission 与缓存租约放到已存在的 dispatch 生命周期；排队只有弱
   提示。不可变结果跨运行复用另需完整图、参数、输入与时钟身份；可变状态不共享。
5. 在两个独立节点（可以同主机）验收：同包来源 ref 不同，RunSpec hash 相同，显式
   重绑后结果一致；相同端口不冲突；离线/升级/权限变化不静默切换；包/数据修订语义分开。
   最后验证无额外 Manager、无远程 SQLite 依赖及峰值资源预算，再另行授权部署。

本批聚焦合同测试验证节点隔离、跨节点需求可移植、包升级后的计划失效、价格/时间/
字段/覆盖不一致拒绝与显式选择；Compose 检查只验证静态环境配置，不等于容器实测。

## 2026-10-28 接线进展（不是全项完成）

执行注册/Job RPC 使用 Keycloak client credentials + introspection，不使用转移节点的
自定义签名注册。服务 token 分别绑定 node_id/manager_id、API audience 与 scopes；
联邦 execution 的 principal 必须在该服务客户端的显式委托清单中，提交另需 submit scope。
旧 transfer 认证只保留给既有文件/对象传输，不能作为 execution 的降级认证。
服务令牌内省缓存上限 256 条、最长 5 秒，权限检查在每次调用执行；控制面调用不进入
逐 Bar 计算热路径。不同 realm 的通用 token exchange 不作已支持假设。

平台控制面提供联邦 execution targets、preview、submit；发现不要求远端已有业务端口，
不读取 Bundle 字节或逐一实例化插件。RunSpec 需求与 source selection 分离，预览绑定摘要
用于提交复核，worker 在加载前检查本地安装及实际 adapter/book type。节点只持私有元数据，
不挂载 Manager Job 数据库。既有 outbox/leases、Celery/RabbitMQ、报告权威继续复用。
远程 chart 通过节点 HTTP 读取、点数/字节预算约束，无同名本地 fallback。

真实隔离验收：Keycloak 26.0、RabbitMQ、独立 Celery worker、原生 Nautilus 公共策略，
T/TL 两个产品各 10,000 根 1m Bar（2024-01-02 至 2024-03-05，含预热），3 策略共享
1 FactorActor，无 Python factor per-Bar callback。两个 Manager/节点注册分别运行的
RunSpec hash 和成交摘要一致。Manager A 客户端经真实 B peer HTTP 完成目录、预览、
提交并运行成功；预览与提交 hash 一致，903 订单、5 报告附件摘要校验。
这不是公网验收、原研报复现或完整容量验收；目录和输入 fixture 预先准备，worker 时间
不包含安装与原始 catalog staging。采样 RSS 也不等于分配器精确峰值或全宿主总内存。

## 基础设施取舍

复用 Keycloak 认证/组/机构与受限管理员能力；复用 RabbitMQ 的确认、ACL、Federation/
Shovel（只在独立 broker 确有跨域投递需求时配置）。不新增消息中转器。Globus Compute
具备 endpoint/worker、任务执行和结果回传、资源/身份隔离能力，但依赖其托管服务，
与已用 Celery 重叠；只核对能力，不引入依赖。

参考：[Keycloak](https://www.keycloak.org/securing-apps/token-exchange)、
[RabbitMQ](https://www.rabbitmq.com/docs/federation)、
[Globus endpoints](https://globus-compute.readthedocs.io/en/main/endpoints/endpoints.html)。

仍需独立收尾：用户/组/机构层级的细粒度资源授权和 `/app` 管理 UI、可下载桌面节点的
签名发布、旧用户/页面/UniqueNameObject 权威的有序移除、实际本机/公网 Docker 发布，
以及 host aggregate admission/长回测容量。操作员 execution-node Compose 不能冒充
已经完成客户端安装功能。用户已新增本机/公网 Docker 配置部署授权；本 ADR 不授予
额外 Git 集成或迁移权限。
