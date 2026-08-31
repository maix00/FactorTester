# ADR 119: Profile Agent 通过 CC Switch CLI 适配 Provider 协议

## 状态

已接受（2026-08-20）

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
5. 不使用 CC Switch 的 `--takeover`；Codex 子进程显式连接环回 URL，
   CC Switch 的 `HOME`、`CODEX_HOME` 和 XDG 目录也全部映射到该
   Profile 的临时会话根，不读写 Manager 用户的全局 CLI 配置；
6. Codex 子进程只拿到本地临时令牌和 CC Switch 环回地址，不拿到上游密钥；
7. Profile Agent 停止后终止 CC Switch，并清理其临时配置、SQLite 和凭据；
8. OpenAI Responses 可保持现有直连；OpenAI Chat 和 Anthropic Messages 通过
   CC Switch 的 Codex 路由转换；
9. 未经 CC Switch Codex 路由明确支持的 Gemini Native 等组合必须在启动前
   拒绝，不做隐式协议降级；
10. Provider 选择 `manager_proxy` 时，Manager 把当前 Mihomo loopback URL
    只注入该 Profile 的 CC Switch 进程；选择 `direct` 时不注入。Mihomo
    不可用时代理 Provider 明确失败，不做直连回退；
11. CC Switch 子进程只继承运行所需的 PATH、locale、TLS 证书和临时目录环境，
    不继承 Manager 进程中的数据库、云服务或其他 Provider 密钥。

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

## UI 对齐与性能门槛

后续每增加一项 Provider UI 能力，都必须先与 CC Switch 的对应行为做语义映射，
再决定 FactorTester 的呈现方式；不得仅凭视觉相似自行增加另一套状态模型。
FactorTester 保留现有 FTUI，不引入 CC Switch 的 React、TanStack Query、Tauri
运行时，避免形成第二套前端框架、路由、国际化和缓存系统。

| 能力 | CC Switch 对应行为 | FactorTester 约束 |
|---|---|---|
| Provider 列表与搜索 | ProviderList | 只读 Manager SQLite；不得探测上游 |
| 新增与编辑 | ProviderForm | 复用公共 overlay，并保持 Profile/服务器所有权隔离 |
| 模型建议 | ModelDropdown | 仅在已保存 Provider 的模型字段获得焦点或用户测试连接时加载；允许手填 |
| 健康状态与测试 | ProviderHealthBadge / useStreamCheck | 用户显式触发单个 Provider；禁止列表批量检查 |
| 协议与传输标识 | Provider 类型及代理状态 | 由后端 capability registry 注册，显示 direct 或 CC Switch |
| 网络代理 | Provider proxy configuration | Provider 只保存 direct/Manager proxy 策略；代理地址与凭据仍由超级管理员管理 |
| 用量、日志和图表 | Usage/日志视图 | 尚未实现；以后只能在用户打开详情 overlay 后懒加载 |
| 故障切换 | 应用级 Provider 切换 | 尚未实现；必须是 Profile 级策略，不得使用全局当前 Provider |

## 会话级模型与运行状态

Provider 的 `default_model` 只负责初始化新会话。一个会话随后独立保存
`model_id`、`reasoning_effort` 和 `service_tier`；修改这些字段不得写回 Provider，
也不得影响同一 Profile 的其他会话。Manager 在每次 `turn/start` 前移除浏览器
直接提交的同名参数，再注入该会话的持久设置。

模型目录采用两层交集：CC Switch/Provider 健康检查返回账号实际可用模型，运行中
的 Codex app-server `model/list` 返回模型的推理强度、服务档位等运行时能力。
Manager 只向 UI 暴露二者交集，结果按 Profile 缓存 60 秒，并在 Agent 启停时
失效；用户聚焦模型选择器或显式刷新时才发起查询。Provider 不可用或组合非法时
保存操作明确失败，不修改旧设置。

上下文信息不从 CC Switch 估算。Manager 直接观察 Codex app-server 的
`thread/tokenUsage/updated`、`thread/settings/updated`、`model/rerouted`，以及新版
`item/completed` 的 `contextCompaction` 项；弃用的 `thread/compacted` 仅作为
兼容输入。SQLite 只保存轻量运行元数据，不镜像会话正文。界面中的“上下文已用”
使用最近一次 active-context token，而“累计”单独显示总 token，避免把累计用量
误当成上下文占用。

只读的直属上级和跨服务器历史沿用 Provider thread 读取链路，显示这些设置与
运行元数据但禁用编辑。Agent 停止后仍可读取 thread；模型能力目录只有在运行时
能同时得到 app-server 能力时才声明推理强度和服务档位可选。

## CLI 与管理边界

研究用 `factortester` CLI 只为服务器管理的 Profile 提供
`profile-agent`：状态、启停、会话列表、模型目录和单会话设置。能力文件模式必须
锁定到签名 Profile；普通登录模式必须显式给出 Profile，并经过本服务器运行绑定
校验。Provider 凭据增删改、Mihomo、CC Switch 进程和服务器集群维护继续只属于
`factortester-manager`。

CC Switch 的全局 Provider 切换、takeover、全局 failover、WebDAV、MCP 与其
React/Tauri UI 不接入本功能。未来若增加自动故障切换，策略必须绑定 Profile，
且一次跨 Provider 迁移必须显式创建或迁移会话，不能把 Provider 的全局状态冒充
会话设置。MCP 与 Skill 可以在同一“Agent 能力”页面管理，但保持不同的数据模型、
权限和生命周期。

性能不变量：

1. 打开 Provider 列表只允许一次 Manager 列表请求，向模型供应商发出零次请求；
2. 不在列表加载、搜索、分页或语言切换时批量执行健康检查；
3. 模型目录按交互懒加载，单次结果最多保留 2000 项；
4. 用量图表、日志和大型详情只在 overlay 打开后加载，关闭后释放其视图状态；
5. 每次 UI 扩展必须记录 CC Switch 对应组件、FactorTester 权限差异、增加的
   请求数量和缓存边界，并用聚焦测试固定关键的不发请求约束。
