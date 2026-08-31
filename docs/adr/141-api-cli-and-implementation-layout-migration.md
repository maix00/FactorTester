# ADR-141：业务 API、CLI 与内部实现目录的分域迁移

## 状态

已接受；公开 API 与 CLI 分域已经落地，内部 Python 包名、模块注册键和部分目录层级仍是后续迁移事项。
本文是对既有迁移实现的规范化记录，不把尚未完成的内部重命名写成已完成。

## 背景

FactorTester 的 Web、Swift、CLI 和服务器 Profile Agent 过去使用过多套重叠入口，例如通用 catalog、
`custom-factors`、按页面自定义的查询函数，以及不同服务端口上的旧路由。这会造成以下问题：

- 同一个业务对象在不同客户端使用不同的权限和字段语义；
- CLI 命令名称与 Web/Swift 的功能入口不一致；
- 服务器 Profile Agent 与客户端使用不同的查询链路；
- 公开 API 已迁移，但 `custom_factors`、`products` 等内部包名仍容易让后续代码误以为旧入口仍然存在；
- 仅改目录名称会同时影响 Python import、模块注册、测试、manifest、持久化逻辑路径和部署包，半迁移会形成
  两套实现或导致启动失败。

## 决策

### 公开 API 按业务领域分域

公开 HTTP 路由以 Web/Swift 可见的业务语义为准：

| 领域 | canonical API 前缀 | 主要用途 |
| --- | --- | --- |
| 因子库 | `/api/factor-library/` | 因子家族、因子、因子集合、源码、参数配置和因子工作区投影 |
| 产品库 | `/api/product-library/` | 数据源、产品、字段、分类、产品路径、产品组和产品树 |
| 研究图目录 | `/api/catalog/research-graphs/` | 不可变研究图版本、Active 指针、YAML 和用户图文件 |
| 研究图实例 | `/api/research-graph-instances/` | 可变研究身份的研究图实例 |
| 研究报告发布 | `/api/research-publications/` | 报告同步、发布、撤销和发布设置 |
| 测试作者配置 | `/api/test-authoring/` | 工作区、配置、模板和测试模块 schema |
| 运行与任务 | `/api/runs`、`/api/jobs` | RunSpec、执行生命周期、任务状态、结果和生成物 |

这些前缀是公共协议边界。因子、产品和研究页面不得再各自拼出一套 catalog 查询；服务器 Agent、Web 和
Swift 也必须使用同一领域客户端、同一权限判定和同一结构化响应。

`/api/client/*` 是明确标记的客户端本地投影，`/api/market-data/*` 是明确标记的行情数据面；它们不是把
通用对象重新放进 catalog 的例外，也不能作为服务器目录的别名。服务器 Profile 报告使用的
`/api/server-research/*` 是服务器 Profile 的报告传输面，不是研究图目录或因子/产品库查询入口。

### 公开 CLI 与 API 对齐

公开 CLI 使用与业务领域相同的名称：

- `factortester factor-library ...` 对应 `/api/factor-library/`；
- `factortester product-library ...` 对应 `/api/product-library/`；
- `factortester research ...` 对应研究图、报告、证据、Profile 和工作区的各自 API；
- 测试作者、运行和任务客户端分别使用 `/api/test-authoring/`、`/api/runs` 和 `/api/jobs`。

`catalog` 只保留在具有明确目录语义的研究图路径中，不作为因子库或产品库的顶层公开命令。已从当前公开
路由树移除的旧入口包括 `/api/catalog/factors`、`/api/catalog/factor-*` 和 `/custom-factors/api/*`；
旧的 `factor-library-overview`、`factor-library-configs`、`factor-library-scopes` 也不得重新注册为
平行公开 API。新代码必须通过领域客户端和其 canonical 前缀访问，不能以兼容为由增加第二条公共链路。

### 内部实现目录与公开名称分开迁移

当前源码仍有以下内部名称，它们不是公共协议名称：

- `server/modules/custom_factors/`：因子领域服务实现，仍被因子目录、源码 manifest、参数解析和存储同步等
  模块 import；
- `tools/cli/modules/custom_factors/`：当前 `factor-library` CLI 的 Python 包目录，registry 的 backend
  key 仍为 `custom_factors`；
- `tools/cli/modules/products/`：当前 `product-library` CLI 的 Python 包目录，registry 的 backend key
  仍为 `products`；
- `custom_factors/{id}.py` 等持久化或工作区逻辑路径，以及 Agent capability 中的旧实现标识，是内部迁移
  依赖，不能当作已删除的公共 API。

这些目录和注册键需要在后续独立迁移中向 `factor_library`、`product_library` 等语义名称收敛，但本 ADR 不
要求在公开入口已经稳定时立即改名。迁移必须一次性完成以下步骤，并在同一变更中更新所有调用方：

1. Python import、模块 registry、backend key、测试和部署 manifest；
2. Agent capability 的 implementation ID 及其生成/校验测试；
3. 工作区、文件存储和迁移代码中的逻辑路径；
4. Web/Swift/CLI 的私有适配器引用和文档示例；
5. 启动、权限、旧数据读取和全量测试。

当前实现到目标布局的登记如下。表中的“后续迁移”是明确的工程任务，不是允许新代码继续扩散旧名称的理由：

| 当前实现位置/标识 | 目标语义位置/标识 | 当前状态 | 迁移时必须一起更新 |
| --- | --- | --- | --- |
| `server/modules/custom_factors/` | 因子领域服务包（例如 `server/modules/factor_library/`） | 保留内部旧名 | import、服务注册、源码/参数解析、历史数据读取、测试 |
| `tools/cli/modules/custom_factors/` | `tools/cli/modules/factor_library/` | 公开命令已是 `factor-library`，包目录未迁移 | registry backend、CLI 导入、能力 manifest、打包与测试 |
| `tools/cli/modules/products/` | `tools/cli/modules/product_library/` | 公开命令已是 `product-library`，包目录未迁移 | registry backend、CLI 导入、能力 manifest、打包与测试 |
| `custom_factors/{id}.py`、`factor-worktree/` | 因子库/ Profile 工作区的语义化逻辑路径 | 历史数据与现有工作区仍在使用 | 持久化路径、下载/上传、旧数据显式迁移、客户端和服务器工作区 |
| `factortester.custom-factors.*` 等 capability implementation ID | `factortester.factor-library.*` 等语义 ID | 旧实现标识仍可能出现在 manifest/测试 | capability 生成、校验、服务器安装包和回归测试 |

在上述迁移完成前，文档和新代码必须把这些名字标为内部实现名；不得把目录名重新当成公共命令、HTTP 路由
或 Profile 身份。迁移完成后应删除只为旧名字服务的兼容层，并补充一条实际完成记录。

迁移完成前允许保留内部别名，但不允许由内部别名重新暴露旧公共路由，也不允许把同一请求同时实现为两
套独立查询。迁移完成时应删除只为旧名称服务的兼容 import 和 capability；若历史数据必须读取，应使用
一次性的显式数据迁移，而不是运行时继续扩大旧 API。

### 服务器 Agent 与客户端使用同一业务能力

服务器 Profile Agent 的工作区可以是客户端用户工作区的副本，但不是另一套业务模型。Agent 通过当前
Profile 的 capability 和已认证 CLI 使用上述公共领域命令；服务器端的本地 workspace 根目录与客户端根目录
不同，只改变存储位置，不改变命令名称、对象 schema、权限关系或 API 领域。

Profile 工作区的副本、用户工作区和服务器端存储路径都必须以 owner/profile/workspace 语义区分。不能因为
内部目录仍叫 `custom_factors` 就让 Agent 回到已经移除的 `custom-factors` HTTP 入口，也不能把某个服务端口
当作 Profile 身份的一部分。

## 验收条件

- API 路由表中因子和产品查询只出现各自 canonical 领域前缀，旧公共路径没有注册；
- `factortester --help` 只展示 `factor-library`、`product-library` 和 `research` 等 canonical 领域入口；
- Web、Swift、客户端 CLI 和服务器 Profile Agent 对同一对象使用相同字段、权限和错误语义；
- `/api/client/*`、`/api/market-data/*`、`/api/server-research/*` 的特殊用途在调用方和文档中明确标注，
  不被误判为通用 catalog；
- 内部目录改名时，import、registry、capability、manifest、持久化路径、旧数据迁移和测试一次性同步，
  不产生第二套公共 API；
- 领域 API 迁移后不再通过运行时隐式迁移旧对象或旧路由，历史数据只经过显式、可审计的迁移处理。

## 后果

- 用户面对的命令和功能入口稳定，权限关系可以由统一领域 helper 实现。
- 内部目录仍暂时保留旧名称不会改变公开 API，也不会被 ADR 误报为已完成的重命名。
- 后续内部重命名的范围较大，需要单独任务和完整回归；直接删除 `custom_factors` 或 `products` 目录会破坏
  现有 import、Agent capability 和历史工作区。
- 新增业务领域时必须同时注册 canonical API、CLI 客户端和服务器 Agent 能力，并把实现目录放在对应领域下；
  页面组件不能再自行发明跨服务器查询链路。

## 相关决策

ADR-093、ADR-095、ADR-115、ADR-116、ADR-118、ADR-132，以及因子库/产品库迁移任务 #359。
