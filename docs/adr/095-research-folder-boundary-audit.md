# ADR 095: 研究目录与服务器能力边界审计

## 状态

已接受；分阶段迁移。

## 背景

FactorTester 目前同时存在三套研究相关代码：

1. `server/` 下早期的研究实例、分支、Evidence、TrialPlan、报告检查点和
   Agent HTTP 路由；
2. `server/manager/` 下的研究图目录、共享研究投影和 7997 对象传输；
3. `tools/cli/agent-harness/`、`tools/cli/release/research_reporting/` 与
   `apple/Sources/Features/Profiles/` 下的本地研究运行和展示。

新的职责边界是：Manager 的公开研究能力负责目录、服务器 Profile 报告读取、
共享投影和对象传输；不把这些能力误认为本地研究 Agent 的推进权威。研究过程可以
在 Swift/CLI 离线运行；共享研究报告只在联网时同步其公开投影和对象。

## 决策

### 保留在服务器侧

服务器只保留以下“目录/数据平面”能力：

```text
server/manager/
  http/
    public_research_routes.py       # 已共享报告的读取入口
    client_research_routes.py        # 本地报告投影/附件读取入口
  objects/adapters/                  # 共享报告、因子源码和附件的对象适配器
  services/
    federated_public_data.py         # 跨节点公开投影读取
    research_object_transfer.py      # 7997 对象传输

server/services/research_graph/      # 过渡期目录；最终只留下 catalog
  protocol.py                        # 图文件校验/序列化合同
  schema.py                          # 图目录与用户图文件表
  versions.py                        # 版本登记/列出
  active_pointer.py                  # 默认版本指针
  presentations.py                   # 语言版本登记/读取
  presentation_contract.py
  user_graphs.py                     # 用户上传/列出/下载/删除
  user_graph_preferences.py
  yaml_export.py
```

这里的服务器代码不能创建研究实例、推进分支或运行 Agent；它只提供可下载
的声明式图和共享对象。目录代码在后续迁移中收敛到
`server/services/research_graph/catalog/`，旧导入只允许在迁移窗口内保留。

### 迁出服务器侧

以下代码的权威实现应迁入本地客户端/CLI，而不是继续作为 Flask 能力维护：

```text
tools/cli/agent-harness/cli_anything/factortester_research/core/
  graph/       # 图解析、拓扑和本地下一步判断
  session.py   # 本地研究会话
  evidence.py  # 本地证据与事实引用
  cycle.py     # 本地研究循环
  workspace.py # 本地研究工作区

tools/cli/release/research_reporting/
  authoring/   # 本地报告编辑
  publisher/   # 本地报告投影
  public_research/
    outbox.py  # 共享报告离线队列

apple/Sources/Features/Profiles/
  ResearchGraph/  # Swift 本地研究图状态和节点视图
  ResearchReport/ # Swift 本地报告读取、编辑和附件视图
```

`server/services/research_graph/branch/`、`research_cycle/`、`trial_plan/`、
`profile_research_projection/`、`work_packages.py`、`report_checkpoint.py`，
以及 `server/modules/single_factor_test/` 下的研究推进、Evidence、Agent
Flow 和 Research Step 路由，属于待迁出的旧服务器运行时，不再添加新功能。

## 迁移顺序

1. 先让本地 CLI/Swift 具备读取已下载 YAML、保存会话、计算下一步、编辑
   报告和本地运行测试的能力；共享报告通过本地 outbox 延迟同步。
2. 先建立 Manager-owned 的 `/api/catalog/research-graphs/...` 接口。它只
   负责版本、默认指针、语言 presentation、YAML 下载和用户图文件，并复用
   现有目录表的兼容格式；Web/Manager CLI 改用该接口，不再把目录请求选到
   8000。随后再把共享目录实现集中到 `research_graph/catalog/`，最后移除
   Manager 对旧研究推进路由的 service proxy。
3. 更新 Web/Swift 读取路径到本地研究存储或公开报告读取路径。
4. 删除旧的服务器研究推进模块、表和测试；删除旧导入兼容层。

在研究推进旧模块完全退出前，不移动整个 `server/services/research_graph` 包。
当前 `server/modules/single_factor_test/__init__.py` 会自动注册部分测试/研究路由，
`server/manager/http/federation/service_proxy.py` 仍承担部分内部转发，且大量测试直接
导入旧模块；半迁移会导致启动失败或形成两个不一致的实现。是否移除旧路由必须以
路由注册、Web/Swift 调用方和测试均已迁出为验收条件，不能仅凭目录名称判断。

本阶段已经完成目录接口的第一步：

```text
server/manager/services/research_graph_catalog.py
server/manager/http/research_graph_catalog_routes.py
/api/catalog/research-graphs/...
```

这是一层明确的 Manager HTTP seam，不是第二套数据库或第二份研究图权威；
它只调用 catalog 子模块，并在 Manager 启动时创建目录所需的最小表。当前实现以
`/api/catalog/research-graphs/...` 为 canonical catalog 路径；`/api/server-research`
是服务器 Profile 报告源的独立传输面，不是研究图 catalog，也不能在新代码中当作通用
目录别名。旧路径是否仍可用，必须以当前路由注册和兼容测试为准，本文不再宣称存在
未经源码确认的 `/api/research-graphs/...` 兼容路由。

## 不做的事

- 不为了“目录看起来整齐”把单个短的本地模块再套一层空目录；
  `tools/cli/local_graph_navigation.py` 已经是合适的客户端模块。
- 不把研究图 YAML 目录、共享报告对象存取和本地研究推进合并成一个
  `research` 服务；它们的接口、离线行为和失败模式不同。
- 不恢复服务器 `next_actions`、研究实例状态、Agent 配额或服务器推进权威。

## 后果

- 当前服务器旧研究模块会暂时存在，但被明确标记为待删除的迁移遗留，不再
  是新功能的放置位置；服务器 Profile 报告读取面与研究图目录面必须分别维护。
- 客户端目录承担离线研究的状态和行为，Manager 目录承担公开投影与对象
  传输，代码归属与网络断开时的行为一致。
- 迁移完成后，服务器部署包可以删除研究推进依赖，启动面更小；在此之前由
  现有兼容测试保护每一步迁移。
