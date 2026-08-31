# ADR-104：Profile 运行时所有权与 Agent 声明

## 状态

已接受（首个服务器端 Agent/Profile 管理范围）。

## 背景

FactorTester 有本地客户端和 Manager 服务器两种执行环境。研究 Profile 是
持久身份，不能悄悄变成多个临时 Agent 工作区。模型提供方凭据属于使用它的
运行时，不能进入 PostgreSQL、浏览器投影或 Profile 元数据。

## 决策

1. 一个 Profile 有一个规范工作区，最多一个持久 Agent 绑定。心跳只描述当前
   在线状态，不是所有权租约，也不能释放或替换绑定。只有显式释放、授权管理
   释放或删除 Profile 才会移除绑定。多个 Profile 可以共享同一个 `agent_id`；
   工作区、会话、权限和运行状态仍按 `principal + profile_id` 隔离。
2. 运行时必须明确：`client` 绑定一个客户端设备，`server` 绑定一个 Manager
   `server_id`。服务器 Profile 不能被其他 Manager claim；研究身份页面同时
   展示两种运行时。
3. 客户端和服务器使用相同的可移植相对目录：

   ```text
   users/<principal>/profiles/<profile-id>/
   ├── factor-worktree/
   ├── strategy-worktree/
   ├── research/
   ├── reports/
   └── manifests/
   ```

   客户端根目录是 `Documents/FactorTester`，Manager 根目录是配置的数据根。
   不创建 `agent-temp`、`agent-sessions`、临时副本或数据源挂载。
4. Agent 通过现有 Manager 控制/数据面（7998/7997）和 FactorTester CLI 取数，
   不挂载服务器数据源目录。
5. 模型连接在独立的研究/智能体模型页面管理。Provider 记录保存在 Manager
   本地 SQLite，token 加密并使用仅所有者可读的 key 文件；API 只返回元数据和
   是否有 token，不返回 token。服务器运行时要求 HTTPS；客户端凭据由本地
   客户端写入，公共 Manager 不写入。
6. 研究模块是唯一导航所有者，不新增 Agent 首页模块。现有 Profile 投影只
   增加运行时和活跃 claim 元数据，秘密仍在投影之外。

## 后果

- Manager 可以协调 Profile 所有权和显示运行时，不需要常驻研究 Agent，也不
  决定研究图下一条边。
- 服务器重启、Agent 停止、漏心跳、浏览器关闭或页面回收都保留绑定；断开
  的绑定会阻止隐式替换，直到显式释放。
- 升级时，只有不存在当前绑定的 Profile 才可恢复最新的 `expired` 旧行；
  显式 `released` 的行永不恢复。
- Agent runner 仍必须使用这些 API 和规范工作区；本文不授权额外的临时执行目录。
