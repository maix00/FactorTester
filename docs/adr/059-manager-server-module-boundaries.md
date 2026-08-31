# ADR 059：Manager 服务器模块边界

## 状态

已接受；迁移完成。

## 背景

旧的 `scripts/worktree_flask_manager.py` 同时承担部署入口、HTTP 路由、认证、联邦、任务选择、进程监督和 HTML 生成。实现迁入 `server/manager/` 期间，兼容别名暂时保留旧导入命名空间；当所有内部调用方都迁移后继续保留这些别名，会让每个 Manager 模块有两个公开名称，也可能让部署重新依赖已退役入口。

## 决策

新的 Manager 服务器代码统一位于 `server/manager/`：

```text
server/manager/
  app.py                 # 进程启动与生命周期
  http/
    *_routes.py          # 聚焦的 HTTP 路由族
    pages.py             # 无数据库依赖的 HTML 边界
    security.py          # 传输、会话和访问策略
  domain/
    devices.py           # 设备注册、挑战和校验
    jobs.py              # 任务查询与服务器/端口选择
    federation.py        # 对等节点注册与转发
  storage/
    control_db.py        # PostgreSQL 控制面仓库
    sqlite.py            # 本地执行/索引投影
  data_plane/
    app.py               # 7997 客户端与 17997 对等传输进程
  state/                 # 路由、任务、worktree、会话、进程状态
  web/                   # Manager Web 壳与静态模块
```

`server.manager.app` 是唯一的 Manager 进程入口。ADR-068 已用 `server.manager.data_plane.app` 替代旧生成物服务，该模块是唯一的 7997/17997 传输进程入口；两个监听端口暴露相互隔离的客户端和 WireGuard 对等路由。

所有 Manager 导入使用 `server.manager.*`；已退役的 `scripts/worktree_*` 别名和 `/manager-legacy` 页面删除。`runtime.py` 只作为 `ManagerState` 与 `Handler` 的组合根；路由实现放在 `server/manager/http/` 下的聚焦模块中。

*worktree* 仍是领域概念：Manager 发现并启动 feature worktree，并通过 `/api/worktrees` 暴露它。删除旧脚本命名空间不等于删除该能力或对等路由协议。

## 后果

- 部署和本机 LaunchAgent 使用 `python -m server.manager.app`。
- 设备认证页面可以在不构造 Manager 状态、不打开数据库连接的情况下测试。
- 测试直接导入规范模块，旧命名空间无法掩盖缺失或循环依赖。
- HTTP dispatch seam 只有一个接口和一个实现命名空间；worktree 执行与联邦路由保持原有行为。
