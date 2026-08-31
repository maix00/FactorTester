# ADR-138：浏览器本地的有界 tab 工作区缓存

> **编号迁移说明：** 本文原文件名为 `119-browser-local-tab-workspace-cache.md`。
> 因 ADR-119 已用于 Profile Agent 的 CC Switch gateway，本文迁移为 ADR-138；决策内容不因重编号改变。

## 状态

已接受。

## 背景

FactorTester 使用持久左栏 tab 作为独立工作区。用户希望在切换、刷新或同一
浏览器重新登录后恢复路由、草稿、overlay 和阅读位置，但无限期保留所有 DOM
会造成无界内存增长；把瞬时 UI 状态同步到 PostgreSQL 或 Manager 联邦也会把
展示状态带进服务器通信而没有收益。

## 决策

缓存按 Manager origin 和认证用户名隔离，分三层：

1. 最多保留最近三个活跃/非活跃 DOM 视图，使用确定性的 LRU；
2. 更旧视图冷却为 `sessionStorage` 中的小型控件/滚动快照，按稳定语义键恢复；
3. tab 注册表和带版本的持久投影放在 `localStorage`。测试页只保存用户写的草稿，
   不保存目录、结果、Promise、DOM、凭据或服务器响应。

有意义的草稿变化以及 `visibilitychange`/`pagehide` 时 checkpoint；不使用
`unload`。关闭 tab 删除其持久会话。schema 不匹配或数据损坏时丢弃快照并安全
重载路由。

窗口滚动位置总是保留；长期表格、树、报告和分析滚动容器通过
`data-ft-scroll-state` opt in。临时 popover 和下拉菜单不保存滚动位置。

研究报告额外按稳定 `component_id` 保存当前章节和展开状态。首次没有本地阅读
状态时，初始懒加载章节完成后从报告底部打开；之后恢复保存的位置。

该状态不在 Manager、浏览器或设备之间同步。恢复时页面通过正常懒加载 API
重新校验账户、目录、任务和生成物；认证改变时只清理 DOM 缓存，保留各账户
独立命名空间的工作区。

## 后果

刷新和同一浏览器重新登录可以恢复打开的 tab 与活动 tab，同时不把恢复路径依赖
PostgreSQL 或联邦。长会话只保留有界 DOM，冷 tab 重开时支付正常懒渲染成本。
新增持久页面类型必须显式提供可序列化投影和 schema 版本，不能序列化任意应用
状态。
