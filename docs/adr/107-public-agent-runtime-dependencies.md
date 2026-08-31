# ADR-107：公共 Agent 运行时依赖

## 状态

已接受。

## 背景

公共 Manager 承载服务器侧 Profile。Profile 的 app-server 必须启动 Codex `app-server` 协议并调用面向用户的 FactorTester 研究 CLI；Manager/operator CLI 属于服务器管理，不得进入 Agent 命令表面。

公共镜像按精确 Git revision 构建和激活，因此运行时依赖要在镜像构建期间安装并检查，不能把 provider token 或私有 Mihomo 订阅放进仓库。

## 决策

- 在公共镜像安装固定版本的 `@openai/codex` npm 包，并在构建时校验 `codex --version`。
- 把 `tools/cli` Python 分发安装到镜像，使 `factortester` launcher 从已安装 bootstrap 解析，而不是从 Agent 工作目录 checkout 解析。
- 安装后移除 `factortester-manager` launcher；其 Python 模块仍属于 Manager 应用源码，但普通 Agent PATH 不暴露该命令。
- Codex npm registry 和版本作为 Compose build args；provider 凭据与 Mihomo 订阅配置只在运行时注入。

## 后果

公共镜像因为包含 Node.js 和 Codex Linux runtime 会更大，但 Profile app-server 启动确定且不依赖主机安装。升级 Codex 是显式镜像 revision，必须经过正常构建、发布、重启和验证事务。
