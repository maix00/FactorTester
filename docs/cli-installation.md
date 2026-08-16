# FactorTester CLI 安装边界

## 终端用户

FactorTester CLI 是 Python 命令行应用，推荐用 `pipx` 安装，而不是安装进
系统 Python 或仓库的 `GTHT` 环境：

```bash
brew install pipx
pipx ensurepath
pipx install /path/to/factortester.whl
```

如果从源码安装，使用普通 wheel 安装而不是 editable 安装：

```bash
scripts/install_factortester_pipx.sh
```

如果使用发布资产，在同一个 pipx 环境中安装匹配版本的两个 wheel：

```bash
scripts/install_factortester_pipx.sh \
  /path/to/factortester-0.1.2-py3-none-any.whl \
  /path/to/cli_anything_factortester_research-0.1.2-py3-none-any.whl
```

脚本通过 `pipx inject --include-apps --pip-args=--no-deps` 安装 Harness。
这是有意的：两个 wheel 已经由同一次发布构建并锁定版本，避免 pipx 在没有
内部包索引时重新解析或下载一个不匹配的 `factortester` 依赖。

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
| 研究 CLI | pipx 应用环境或 Swift 内置 runtime |
| Manager CLI | pipx 应用环境；Swift 内部另有签名 launcher |
| 仓库开发/服务器测试 | `GTHT` Conda 环境 |
| 实际测试任务 | Docker/native runner 环境 |
