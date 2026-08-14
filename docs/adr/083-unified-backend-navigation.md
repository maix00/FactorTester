# ADR-083：统一后端导航目录与研究身份选项卡

## 状态

已接受

## 背景

Web 与 Swift 客户端此前分别维护模块入口，导致同一账号在不同客户端看到的模块、管理员入口和研究身份入口可能不一致。研究身份本质上属于研究报告工作流，不应再作为顶层模块出现。

## 决策

1. Manager 7998 的 `GET /api/modules` 是客户端导航的权威来源，返回当前会话已经过滤过的模块树。
2. `research` 是顶层模块；`research.profiles` 作为其子选项卡，路由为 `/research?section=profiles`。
3. `roles`、`requiresAuth` 与 capability 过滤在 Manager 完成。超级管理员能力由服务端会话推导；普通客户端不自行推断管理员权限。
4. `sidebarVisible`、`homeVisible`、`pinned` 和 `tab_behavior` 由后端返回，Web/Swift 只负责把已授权目录映射到各自的显示控件。
5. Manager API 临时不可用时，Web 和 Swift 可以使用内置的最小公共入口回退以保持页面可见；回退目录不是权限来源，受保护操作仍由服务端拒绝。
6. 旧的 `/profiles` 列表入口重定向到 `/research?section=profiles`；`/profiles/<id>` 详情路由暂时保留以兼容历史链接，详情页返回研究身份选项卡。
7. 目录只暴露当前 Manager 已有页面承载的管理入口（`manager`、`sqlite_web`）。没有对应 shell/路由的未来管理模块先不进入客户端目录，避免出现可见但点击后 404 的入口。

## 影响

- 新增或调整客户端入口只需修改 Manager 导航注册表及其多语言目录。
- 未认证访问不会从导航响应中获得受保护的研究身份、测试工作台或管理员模块。
- 现有研究报告、Profile 详情链接、账户设置中的本地 Profile 管理不被删除；只调整公网/Manager 研究目录中的入口层级。
- `/static/config/modules.json` 作为旧兼容资源仍可保留，但当前 Web 与 Swift 不再以它作为权限或导航来源。
