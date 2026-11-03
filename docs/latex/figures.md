# 系统结构图与图例

本章只展示系统角色、权限层级和组件之间的数据关系。它们是结构图，不代替用户操作流程。登录、任务运行、报告发布、因子同步和部署回退的流程图放在相应业务章节中，与操作说明相邻。图中的实现状态还须结合目标版本和验收记录判断。

## 全书通用图例

<div class="figure-legend">

| 符号 | 含义 |
|---|---|
| 蓝色实线箭头 | 已实现的控制面请求或任务调度方向 |
| 青绿色实线箭头 | 同主机数据读取、Arrow 批次或结果数据流 |
| 紫色连线 | 结构图中的双向虚线表示 Manager 互联；业务流程图中的实线按标签标出 7998/17998 已认证控制请求，并非规划链路 |
| 琥珀色虚线箭头 | 规划中或尚未完成端到端验收的连接 |
| 箭头标签中的端口 | 数据实际经过的入口；7998/7997 面向客户端，17998/17997 限于 WireGuard 对等节点 |
| 琥珀色边框 | 用户所有、本地启动、生命周期由用户控制 |
| 红色叉号 | 明确禁止的调用或越权路径 |
| 深灰实线 | 按目标部署配置执行的发布通道；不代表某个固定应用端口 |
| 主机外框 | 一个独立的 OS/容器网络边界；容器进程内存并不因此共享 |

</div>

## Manager、执行节点、数据节点与桌面本机节点

\begin{figure}[htbp]
\centering
\resizebox{\textwidth}{!}{\input{docs/latex/network-topology.tex}}
\caption{控制面、执行面、数据面和个人本机运行时的目标边界。箭头旁的编号对应图内详细说明；虚线表示规划中或尚未端到端验收。桌面本机节点不接受 Manager 调度；跨主机 Arrow Flight 和身份懒同步尚待完成。}
\end{figure}

## Keycloak 身份、机构层级与授权范围

\begin{figure}[htbp]
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

\begin{figure}[htbp]
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

\begin{figure}[htbp]
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
