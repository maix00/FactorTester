# ADR 073：公共访客入口受入口来源约束并跳转到 IP 端点

## 状态

已接受。

## 背景

公共 Manager 同时通过稳定浏览器入口 `https://eloquence-drizzly-fencing.ngrok-free.dev` 和直接 HTTPS IP 端点可达；两者是不同浏览器来源。合规页不能在每个公共地址意外宣传访客模式，尤其不能在直接 IP 入口显示。

访客模式是本地 Manager 已提供的有界匿名投影（`FACTORTESTER_REQUIRE_LOGIN_FOR_UI=0`）：可查看服务器最新 20 条公共测试记录，但不能提交认证运行、查看私有账户数据或下载生成物。

## 决策

1. 部署在 `FACTORTESTER_PUBLIC_VISITOR_ORIGINS` 中显式列出浏览器入口来源。`FACTORTESTER_MANAGER_PUBLIC_ENDPOINT` 是访客跳转目标，不是允许显示入口的来源，因此直接 IP 合规页除非被运维显式加入列表，否则不显示访客入口。
2. 配置的入口合规页链接到 Manager `/visitor` 路由。Manager 创建短期、一次性的内存 grant，并把浏览器重定向到配置的 HTTPS Manager 端点，只携带 grant 和安全的本地 next path。
3. IP 端点消费 grant，签发绑定来源的短期访客 session cookie。手工 `?visitor=1`、过期/错误目标 grant 或其他来源 cookie 不能启用访客模式。
4. 访客模式由一个 `VisitorMode` capability 对象表示。向服务转发匿名读取时使用已有 `__public_jobs__` 投影，最多 20 个服务器 Job，不能提交工作，也不能获得生成物传输授权；账户、Profile、设置、Manager 和跨服务器操作仍走原有路由认证。
5. 访客模式的登录尝试返回类型化错误，Web 客户端回到合规页并隐藏访客入口。

## 后果

ngrok 只负责入口/选择页，活动访客会话位于部署指定的公共 IP 来源。直接 IP 在设备认证或从显式入口获得 grant 前仍只显示合规页。访客 grant 和会话是进程内匿名状态；Manager 重启使它们失效，不影响用户、设备、PostgreSQL 或 Job。公共任务投影可以展示最近任务元数据和存储计数，但不暴露生成物字节。
