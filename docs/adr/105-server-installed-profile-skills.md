# ADR 105：服务器 Profile 使用服务器安装的 Skill

## 状态

已接受，作为首个服务器侧 Agent Skill 选择切片。

## 背景

服务器 Agent 可能需要 FactorTester 研究说明，但用户不能上传任意指令，也不能让服务器 Agent 获得 Manager 运维能力。客户端运行 Profile 必须保持独立：客户端 Skill 由客户端应用发布和管理，不能从 Manager 的服务器目录暴露。

## 决策

1. 部署的服务器在 `server/manager/skills/catalog.json` 拥有显式 Skill manifest。Skill 只有在列出、启用、含有效 `SKILL.md` 且声明匹配 runtime kind 时才对 Profile 可用。
2. 只有 `audience: profile` 的条目返回给用户；Manager-only 运维 Skill 可以安装在服务器，但不能由 Profile 目录路由返回。
3. 用户只能勾选服务器提供的 Skill ID，选择保存在 Manager 现有本地 SQLite。Profile 只在规范 `.codex/skills` 下获得由所有者控制的 symlink；Skill 源码不复制到 Profile 或临时 Agent 工作区，也不上传 PostgreSQL。
4. 浏览器响应只含 Skill 元数据和选择状态，不含本地路径。服务器 Agent supervisor 启动 claimed Profile Agent 时通过 `AgentProfileService.selected_skill_bindings` 获取绑定，只按白名单构造 app-server Skill 视图，不能暴露仓库级 Skill 目录。
5. Profile app-server 环境以其 `.codex` 作为 `CODEX_HOME`、`HOME` 和 XDG 配置/数据/状态根。接受 turn 前调用 `skills/list`，禁用所选投影之外的 Skill，重新启用之前禁用的已选 Skill，并用 `skills/config/write` 刷新列表；`turn/start` 的 Skill 输入只来自选定 ID。
6. Manager 拥有服务器 Profile app-server supervisor，提供窄的认证 JSON-RPC/SSE bridge。只有 Profile 有 active claim 和有效本地 provider 后才启动，每个 Profile 一个进程，Manager 关闭时停止子进程。Provider token 只通过子进程环境传递，不写 Profile 配置或 HTTP 响应。
7. 浏览器只能提交 prompt 和已选 Skill ID，不能提交任意路径或 app-server 方法。supervisor 强制 Profile 工作区为 cwd，校验 turn/start Skill 输入，并从响应/事件中净化本地路径和凭据形态字段。当前 bridge 只接受文本输入；图片/文件/mention、逐请求 approval、sandbox、provider、capability-root 和权限覆盖均拒绝。生成的 Profile 配置固定 `approval_policy = "never"`、`sandbox_mode = "workspace-write"`、Profile 工作区和出站网络，并设置 `shell_environment_policy.ignore_default_excludes = false`，使 provider token 不进入 shell tool 环境。
8. 首个 provider adapter 使用 OpenAI Responses 兼容 wire contract。已有 Provider 表单是唯一 API key 入口，key 在 Manager 本地 SQLite 加密保存，list/connection-test 不返回。连接测试发送认证的只读 `GET /models`，确认默认模型存在；不支持的 protocol 值拒绝，不当作 OpenAI。
9. claimed 服务器 Profile Agent 只有在本地 Codex 与 FactorTester CLI 可执行预检通过、Provider 健康检查通过后才启动。CLI 路径来自 `FACTORTESTER_CLI` 或已安装的 `factortester` 命令，并加入子进程环境；预检失败不启动 Codex。

## 后果

增加研究 Skill 是服务器部署/配置变更，不是用户上传。服务器或 SQLite 故障阻止修改选择，但已运行 Agent 仍按 supervisor 的既有进程策略继续。客户端 Profile 保持自己的 Skill 集合，不显示服务器 Skill 选择控件。API key 或模型故障在 Provider 测试时及新 Agent 启动前分别报告，响应不包含秘密；未来 provider 可增加 adapter，而不改变 Profile claim 或工作区隔离。
