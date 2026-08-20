# ADR 118: Profile Agent 通过 CC Switch CLI 适配 Provider 协议

## 状态

Accepted — 2026-08-20

## 背景

FactorTester 的研究身份会话目前由 Codex app-server 提供稳定的线程、事件和
工具策略接口，但用户需要连接 OpenAI Responses、OpenAI Chat 和 Anthropic
Messages 等不同 Provider。自行复制协议转换代码会与成熟实现产生行为偏差，
也会重复承担流式事件、工具调用和错误映射的维护成本。

官方 CC Switch 是 Tauri 桌面应用，不适合作为多用户服务器组件；
`SaladDay/cc-switch-cli` 则是其 headless CLI fork，并声明复用原项目的 Service
Layer。它提供非交互 Provider 管理、独立配置根目录和前台代理模式。

## 决策

FactorTester 直接调用固定版本的 `cc-switch` CLI，不复制协议转换源码：

1. Manager SQLite 继续是 Provider、Profile 绑定和凭据的权威数据源；
2. 每次 Profile Agent 启动时创建独立、权限为 `0700` 的
   `CC_SWITCH_CONFIG_DIR`；
3. Manager 使用权限为 `0600` 的短时配置文件调用
   `cc-switch provider add --config-file`，避免密钥进入进程参数；
4. CC Switch 仅监听 `127.0.0.1` 的临时端口，不开放为服务器服务；
5. Codex 子进程只拿到本地临时令牌和 CC Switch 环回地址，不拿到上游密钥；
6. Profile Agent 停止后终止 CC Switch，并清理其临时配置、SQLite 和凭据；
7. OpenAI Responses 可保持现有直连；OpenAI Chat 和 Anthropic Messages 通过
   CC Switch 的 Codex 路由转换；
8. 未经 CC Switch Codex 路由明确支持的 Gemini Native 等组合必须在启动前
   拒绝，不做隐式协议降级。

公网镜像固定安装 `cc-switch-cli v5.10.2`，按架构校验上游发布包 SHA-256。
来源、固定版本和 MIT License 记录在 `third_party/cc-switch-cli/`。

## 原因

- 直接复用成熟转换实现，避免 FactorTester 与 CC Switch 行为漂移；
- Profile 级临时配置消除 CC Switch 单用户“当前 Provider”模型造成的串用；
- 环回监听和临时本地令牌缩小上游凭据暴露范围；
- FactorTester 会话目录与 Provider 原生状态仍保持清晰边界。

## 后果

- 非 Responses Provider 启动依赖镜像中的 `cc-switch` 可执行文件；缺失时应
  明确失败；
- CC Switch 升级必须更新固定版本、校验和、归属记录并跑协议聚焦测试；
- 若将来需要 Claude Code 或 Gemini CLI 自身作为 Agent Runtime，应另行实现
  Runtime 的会话事件适配，不能仅凭 Provider 转换宣称已经支持。
