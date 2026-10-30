# 系统图例与关键流程图

本章把分散在架构和运维文档中的角色关系汇总成可审阅的图。图示是阅读导航；具体能力以相邻章节中的状态说明、代码和部署验收记录为准。

## 全书通用图例

<div class="figure-legend">

| 符号 | 含义 |
|---|---|
| 蓝色实线箭头 | 已实现的控制面请求或任务调度方向 |
| 青绿色实线箭头 | 同主机数据读取、Arrow 批次或结果数据流 |
| 紫色双向虚线 | Manager 之间经过身份校验的互联；需要目标端授权 |
| 琥珀色虚线箭头 | 规划中或尚未完成端到端验收的连接 |
| 琥珀色边框 | 用户所有、本地启动、生命周期由用户控制 |
| 红色叉号 | 明确禁止的调用或越权路径 |
| 主机外框 | 一个独立的 OS/容器网络边界；容器进程内存并不因此共享 |

</div>

## Manager、执行节点、数据节点与桌面本机节点

<figure>
\centering
\begin{tikzpicture}[font=\scriptsize,>=Stealth]
  % Manager hosts
  \draw[trHost] (-7.8,2.0) rectangle (-1.7,6.4);
  \node[font=\small\bfseries,text=trInk] at (-4.75,6.08) {公网 Manager 主机};
  \node[trManager] (pubmgr) at (-5.7,4.95) {Manager\\登录会话、RunSpec、Job 与调度};
  \node[trIdentity] (pubid) at (-2.9,4.95) {Keycloak\\公网登录与角色};
  \node[trStore] (pubstore) at (-4.3,3.15) {PostgreSQL · CouchDB · RabbitMQ\\控制记录、Job 对象、任务队列};
  \draw[trControl] (pubmgr) -- (pubstore);
  \draw[trControl] (pubmgr) -- (pubid);

  \draw[trHost] (1.7,2.0) rectangle (7.8,6.4);
  \node[font=\small\bfseries,text=trInk] at (4.75,6.08) {机构内网 Manager 主机};
  \node[trManager] (orgmgr) at (2.9,4.95) {Manager\\本地登录、RunSpec、Job 与调度};
  \node[trIdentity] (orgid) at (5.7,4.95) {Keycloak\\机构用户与层级组};
  \node[trStore] (orgstore) at (4.3,3.15) {本地控制库 · Job 对象 · 队列\\离线时继续本地认证和管理};
  \draw[trControl] (orgmgr) -- (orgstore);
  \draw[trControl] (orgmgr) -- (orgid);
  \draw[trFederation] (pubmgr.south east) to[bend left=16] node[above,sloped,text=trViolet] {经授权的身份/能力互联} (orgmgr.south west);

  % Managed execution and data services
  \draw[trHost] (-7.8,-2.15) rectangle (-1.7,1.35);
  \node[font=\small\bfseries,text=trInk] at (-4.75,1.02) {Manager 管理的执行主机};
  \node[trCompute] (worker) at (-5.7,.05) {Nautilus worker\\消费该 Manager 的冻结任务};
  \node[trData] (workerio) at (-2.9,.05) {Data I/O\\有界 Arrow 缓存};
  \node[trData] (bundle) at (-4.3,-1.42) {数据 Bundle\\留在数据所在主机};
  \draw[trDataFlow] (worker) -- (workerio);
  \draw[trDataFlow] (workerio) -- (bundle);
  \draw[trControl] (pubmgr.south) -- node[left,text=trBlue] {Job} (worker.north);

  \draw[trHost] (1.7,-2.15) rectangle (7.8,1.35);
  \node[font=\small\bfseries,text=trInk] at (4.75,1.02) {数据专用主机（可选）};
  \node[trData] (dataio) at (3.0,.05) {Data I/O\\Arrow 列式缓存};
  \node[trData] (databundle) at (6.0,.05) {Bundle 与本地文件};
  \node[font=\scriptsize,text=trInk,align=center] at (4.5,-1.25) {不安装 Manager 或 Nautilus worker};
  \draw[trDataFlow] (dataio) -- (databundle);
  \draw[trPlanned] (workerio.east) -- node[above,text=trAmber] {跨主机 Arrow Flight 尚未接通} (dataio.west);

  % User-owned desktop runtime, deliberately outside Manager dispatch.
  \draw[trHost,dashed,draw=trAmber] (-3.1,-6.35) rectangle (3.1,-2.85);
  \node[font=\small\bfseries,text=trAmber] at (0,-3.15) {桌面用户的个人电脑};
  \node[trClient] (desktop) at (-1.55,-4.25) {桌面客户端\\用户发起本机运行};
  \node[trClient] (localruntime) at (1.55,-4.25) {本机 Nautilus\\仅供该用户使用};
  \node[trData] (localdata) at (0,-5.65) {本机数据与有界缓存};
  \draw[trControl] (desktop) -- (localruntime);
  \draw[trDataFlow] (localruntime) -- (localdata);
  \draw[trPlanned] (pubmgr.south west) to[bend right=14] node[left,text=trAmber,align=center] {仅登录授权\\与签名包下载} (desktop.north west);
  \draw[trBlocked] (0.12,-2.05) -- (0.72,-2.65);
  \draw[trBlocked] (0.72,-2.05) -- (0.12,-2.65);
  \node[font=\scriptsize\bfseries,text=trRed,align=center] at (1.45,-2.38) {Manager 不得调用或调度本机节点};
\end{tikzpicture}
\caption{控制面、执行面、数据面和个人本机运行时的边界。桌面本机节点不在 Manager 的执行节点目录或任务队列中。跨主机 Arrow Flight 标为待实现；图中 Manager 间互联也必须按目标 Manager 的授权策略处理。}
\end{figure}

## Keycloak 身份、机构层级与授权范围

<figure>
\centering
\begin{tikzpicture}[font=\small,>=Stealth]
  \node[trIdentity,text width=5.3cm,minimum height=.9cm] (realm) at (0,4.1) {当前 Manager 的 Keycloak Realm};
  \node[trRole] (super) at (-4.2,2.75) {超级管理员角色\\跨机构管理权限};
  \node[trRole,text width=4.2cm] (org) at (0,2.75) {机构组\\每个用户都属于一个机构};
  \node[trRole] (guest) at (4.2,2.75) {访客低权限身份\\禁止自助注册};
  \node[trRole,text width=4.0cm] (orgadmin) at (0,1.35) {机构管理员\\FGAP 限定本机构及下级};
  \node[trRole,text width=3.2cm] (level1) at (-2.7,-.05) {层级 A\\层级管理员可管下级};
  \node[trRole,text width=3.2cm] (level2) at (.0,-.05) {层级 B\\继承上级可见范围};
  \node[trRole,text width=3.2cm] (members) at (2.7,-.05) {层级成员\\仅有明确获授权限};
  \draw[trControl] (realm) -- (org);
  \draw[trControl] (realm) -- (super);
  \draw[trControl] (realm) -- (guest);
  \draw[trControl] (org) -- (orgadmin);
  \draw[trFederation] (orgadmin) -- node[right,text=trViolet] {受限子树} (level2);
  \draw[trControl] (level1) -- (level2);
  \draw[trControl] (level2) -- (members);
  \node[draw=trInk!40,fill=trPaleGray,rounded corners=2pt,align=left,text width=12.5cm,inner sep=7pt] at (0,-1.65) {\textbf{彼此独立的能力：}公网登录角色 · 用户设备白名单 · 桌面本机包下载角色 · 对象读取/写入授权。登录成功不会自动获得这些权限；公网注册由管理员创建用户，不开放自助注册。};
  \node[font=\scriptsize,text=trInk,align=center] at (0,-2.55) {内网离线时仍由内网自己的 Keycloak 管理本地用户；允许同步的身份在用户访问公网时按策略懒同步，不复制密码或 MFA 凭据。};
\end{tikzpicture}
\caption{Realm 内的组织层级和权限边界示意。具体角色与组由各 Manager 的 Keycloak 配置决定；FGAP 的授权范围不能由用户名或机构名称硬编码。}
\end{figure}

## RunSpec 到 Nautilus Job 的数据与执行链路

<figure>
\centering
\begin{tikzpicture}[font=\scriptsize,>=Stealth]
  \node[trClient,text width=2.55cm] (client) at (-6.0,2.0) {React / CLI\\选测试、Bundle 与策略};
  \node[trManager,text width=3.0cm] (manager) at (-2.5,2.0) {Manager\\授权、冻结 RunSpec};
  \node[trStore,text width=2.8cm] (plan) at (1.0,2.0) {ExecutionPlan\\节点与 Bundle 匹配};
  \node[trStore,text width=2.7cm] (queue) at (4.6,2.0) {Celery / RabbitMQ\\任务投递};
  \node[trCompute,text width=3.0cm] (worker) at (4.6,-.1) {Nautilus worker\\回测 / 模拟交易};
  \node[trData,text width=2.6cm] (data) at (.8,-.1) {Data I/O\\分块读取与缓存};
  \node[trData,text width=2.8cm] (source) at (-2.5,-.1) {源 Bundle\\来源节点保有数据};
  \node[trCompute,text width=3.0cm] (alpha) at (-2.5,-2.2) {Alpha Rust Plan\\共享因子与因果对齐};
  \node[trManager,text width=3.0cm] (result) at (2.0,-2.2) {Job 结果与生成物\\分块持久化、可审计};
  \node[trClient,text width=2.55cm] (viewer) at (6.0,-2.2) {React 结果页\\图表与明细};
  \draw[trControl] (client) -- node[above,text=trBlue] {HTTPS} (manager);
  \draw[trControl] (manager) -- (plan);
  \draw[trControl] (plan) -- (queue);
  \draw[trControl] (queue) -- (worker);
  \draw[trDataFlow] (worker) -- (data);
  \draw[trDataFlow] (data) -- (source);
  \draw[trDataFlow] (data) -- (alpha);
  \draw[trDataFlow] (alpha) -- (worker);
  \draw[trDataFlow] (worker) -- (result);
  \draw[trControl] (result) -- (viewer);
  \node[font=\scriptsize,text=trInk,align=center] at (1.0,3.0) {RunSpec 冻结测试输入\\ExecutionPlan 冻结执行位置与部署};
\end{tikzpicture}
\caption{一次 Manager 管理的回测任务：Bundle 的数据身份与 RunSpec 解耦，调度时由节点安装清单匹配。多个策略共享同一输入与因子 Plan 时只维护一份计算状态；账户、订单与持仓状态按 Nautilus 配置隔离。}
\end{figure}

## 因子定义到交易与审计结果

<figure>
\centering
\begin{tikzpicture}[font=\scriptsize,>=Stealth]
  \node[trIdentity,text width=3.0cm] (family) at (-6.0,1.3) {因子家族\\固定源码与版本};
  \node[trData,text width=3.0cm] (expr) at (-2.0,1.3) {嵌套 FactorExpr\\参数与时间语义};
  \node[trCompute,text width=3.2cm] (plan) at (2.0,1.3) {共享 Rust Plan\\warmup + 因果采样};
  \node[trRole,text width=3.0cm] (strategy) at (6.0,1.3) {策略家族\\阈值 / 横截面分组};
  \node[trManager,text width=3.0cm] (venue) at (-2.0,-1.1) {Nautilus Venue / Account\\撮合、资金与持仓};
  \node[trData,text width=3.0cm] (events) at (2.0,-1.1) {信号、订单、成交\\费用与结算事件};
  \node[trStore,text width=3.0cm] (evidence) at (6.0,-1.1) {Run / Job / 结果\\指标、图表、明细};
  \draw[trControl] (family) -- (expr);
  \draw[trDataFlow] (expr) -- node[above,text=trTeal] {共享子表达式} (plan);
  \draw[trControl] (plan) -- (strategy);
  \draw[trControl] (strategy) -- (venue);
  \draw[trDataFlow] (venue) -- (events);
  \draw[trDataFlow] (events) -- (evidence);
  \draw[trPlanned] (expr.south) to[bend right=18] node[below,text=trAmber,align=center] {LaTeX、参数代入式\\中间结果只读视图} (evidence.north west);
  \node[draw=trInk!40,fill=trPaleGray,rounded corners=2pt,align=left,text width=12.8cm,inner sep=7pt] at (0,-2.6) {因子序列与回测信号共用同一数学定义。改变频率、交易日历或可用时间会改变计算语义，必须和版本一起冻结；展示公式不触发第二次完整计算，也不自动保存整段历史。};
\end{tikzpicture}
\caption{因子计算、策略使用、Nautilus 交易状态和可审计 Job 结果的职责链。琥珀色虚线表示独立的只读公式/中间结果查看路径，完成状态须以相邻章节记录为准。}
\end{figure}

## 图示状态核对

图中使用的跨主机数据线、签名本机运行包、跨 Manager 身份同步以及对象授权都必须结合部署版本查看。**有代码或界面不等于已部署验收。** 当前工作树的 PDF 会记录源码快照与各源文档的修改状态；部署版本仍以 Manager 和 Keycloak 的实际回执为准。
