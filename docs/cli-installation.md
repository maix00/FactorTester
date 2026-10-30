# TradeResearch CLI 安装边界

## 终端用户

普通用户不需要、也不应当在系统 Python、Conda 或 pipx 中安装
`traderesearch` / `traderesearch-manager`。这两个命令随 `FTClient.app` 一起
发布，并由 App 启动时激活到：

```text
~/Library/Application Support/TradeResearch/bin/
```

激活后的稳定入口会指向当前已验证的 App runtime，不会调用系统 Python。
需要在终端或外部 Agent 中使用时，执行：

```bash
source "$HOME/Library/Application Support/TradeResearch/bin/traderesearch-env.sh"
traderesearch --help
traderesearch-manager --help
```

环境脚本提供以下变量：

```text
TRADERESEARCH_CLIENT_ROOT
TRADERESEARCH_CLIENT_BIN
TRADERESEARCH_CLI
TRADERESEARCH_MANAGER_CLI
TRADERESEARCH_RESEARCH_CLI
```

App 更新或回滚后会重新生成这些入口。不要把旧版本路径复制到 shell
profile，也不要用 `pipx` 或 Conda 路径覆盖 `TRADERESEARCH_CLI` 与
`TRADERESEARCH_MANAGER_CLI`。

CLI 通过签名客户端的版本化 runtime 发布；仓库不再提供旧的 pipx 安装脚本。
Keycloak 登录必须先在 TradeResearch Web 或桌面端完成，CLI 只验证并复用
当前 Manager URL 对应的会话，不接受用户名或密码参数。

当前发布包包含两个明确的 console entrypoint：

```text
traderesearch
traderesearch-manager
```

它们共享发布版本和底层协议代码，但命令树不同。研究 Agent 使用
`traderesearch`；Manager 操作使用 `traderesearch-manager`。两个 CLI 均不提供
用户、机构、Realm Group 或权限管理命令；这些授权由 Keycloak 管理。

## Swift 客户端

TradeResearch 桌面客户端在 `Contents/Resources/TradeResearch` 中携带经过构建、签名和
哈希校验的 runtime。Swift UI 的研究/本地 Profile 操作调用内置
`traderesearch`，Manager 登录和设置操作调用同一个 App 内部的
`traderesearch-manager` launcher。

这两个 launcher 是 App 的内部实现，不要求用户在 Conda 或 PATH 中安装
TradeResearch CLI。Research Agent Skill 同时随 App 资源安装并注册到客户端
的 Skill 目录。

## 本机测试依赖

研究 CLI 环境不承担测试执行依赖。Job 的 pandas、numpy、数据源连接器和
回测引擎由目标 Manager 的 Docker runner 或独立 native runner 管理，并根据
锁定的依赖清单复用环境。依赖缺失时 Job 应报告缺失，不应静默修改 CLI 环境。

因此推荐的所有权是：

| 内容 | 所属运行时 |
| --- | --- |
| 研究 CLI | FTClient.app 内置并激活的 runtime |
| Manager CLI | FTClient.app 内置并激活的 runtime |
| 仓库开发/服务器测试 | `GTHT` Conda 环境 |
| 实际测试任务 | Docker/native runner 环境 |

CLI 的 Manager URL 是用户选中的服务器入口。数据能力、可用性和流动性请求继续经过该入口，
再由 Manager 按服务器公布的自动业务服务端口和当前身份转发；客户端不需要配置固定业务端口。
