# FactorTester CLI 安装边界

## 终端用户

普通用户不需要、也不应当在系统 Python、Conda 或 pipx 中安装
`factortester` / `factortester-manager`。这两个命令随 `FTClient.app` 一起
发布，并由 App 启动时激活到：

```text
~/Library/Application Support/FactorTester/bin/
```

激活后的稳定入口会指向当前已验证的 App runtime，不会调用系统 Python。
需要在终端或外部 Agent 中使用时，执行：

```bash
source "$HOME/Library/Application Support/FactorTester/bin/factortester-env.sh"
factortester --help
factortester-manager --help
```

环境脚本提供以下变量：

```text
FACTORTESTER_CLIENT_ROOT
FACTORTESTER_CLIENT_BIN
FACTORTESTER_CLI
FACTORTESTER_MANAGER_CLI
FACTORTESTER_RESEARCH_CLI
```

App 更新或回滚后会重新生成这些入口。不要把旧版本路径复制到 shell
profile，也不要用 `pipx` 或 Conda 路径覆盖 `FACTORTESTER_CLI` 与
`FACTORTESTER_MANAGER_CLI`。

仓库中的 `scripts/install_factortester_pipx.sh` 仅用于历史发行包/内部发布
验证，不是普通 FTClient 用户的安装方式。

当前发布包包含两个明确的 console entrypoint：

```text
factortester
factortester-manager
```

它们共享发布版本和底层协议代码，但命令树不同。研究 Agent 只使用
`factortester`；管理员才使用 `factortester-manager`。

## Swift 客户端

FTClient.app 在 `Contents/Resources/FactorTester` 中携带经过构建、签名和
哈希校验的 runtime。Swift UI 的研究/本地 Profile 操作调用内置
`factortester`，Manager 登录和设置操作调用同一个 App 内部的
`factortester-manager` launcher。

这两个 launcher 是 App 的内部实现，不要求用户在 Conda 或 PATH 中安装
FactorTester CLI。Research Agent Skill 同时随 App 资源安装并注册到客户端
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
