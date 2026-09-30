# ADR-156：一次性移除 Research Graph，独立保留研究对象与 Agent 工作流

- **日期**：2026-09-30
- **状态**：待一次性完整切换（整体跟踪见 Issue #403）
- **取代**：ADR-040、ADR-047、ADR-084、ADR-094、ADR-142 中与 Research Graph、Graph Branch、WorkPackage、Graph TrialPlan 或 Graph 历史有关的要求；这些 ADR 其余不冲突的报告、对象访问与同步约束继续有效。

## 背景

用户明确决定整体剥离 Research Graph 设施，Graph 历史内容无需保留。当前 Graph 同时承担研究导航、执行门禁、统计计划、证据准入和报告关联，导致自由探索与量化执行依赖固定拓扑。继续把 Graph 改成可选视图或把历史改存成另一套节点/义务记录，都没有解决问题。

平台仍需要独立的研究、报告及报告 Branch；客户端和服务器 Profile 可以共同查看同一报告、在各自 Branch 工作并跨 Branch 复制章节。因子、数据范围、ResearchRun、Job、结果产物和因子集合成员历史按各自身份与生命周期运行，不因 Graph 退役而删除。

## 决策

### 1. Research Graph 不再是产品或执行基础设施

退役 Graph 专属的模型、目录、拓扑、WorkPackage/Graph Branch、节点义务、Graph TrialPlan、Graph checkpoint、Graph admission、导航、工具和偏好。新研究、Agent 对话、因子评估和回测不得要求创建或推进 Graph。

Graph 专属历史内容不迁移到 Archive、WorkflowRun 或其他新对象。切换写入口后，Graph 表和文件中的历史版本、YAML、实例/分支轨迹、义务、TrialPlan、Graph checkpoint 与偏好都可删除。旧 ADR 和审计文档只作为工程决策记录，不是产品数据保留要求。

### 2. Research、Report 和 Report Branch 独立于 Graph

`Research` 是授权与协作根对象；`Report` 是稳定的研究报告对象；`ReportBranch` 是该报告正文的一条可编辑版本线。其规范身份和跨服务器解析沿用 ADR-149、ADR-154 的稳定 Research/Report/Branch 与 principal identity，不再包含 Graph、instance、WorkPackage 或 checkpoint 身份。服务器 ID 只标识来源/当前权威位置，不成为内容身份的一部分。

保留报告正文、附件、作者 provenance、Branch fork/复制/合并、跨 Branch 章节复制和跨服务器读取。删除 Graph 数据前，必须证明这些内容已由独立 Report/Branch 存储权威承载；若仍落在 Graph 表/文件中，只迁移**当前有效正文和必要的 Branch 头/权限元数据**，不迁移 Graph 拓扑和过程历史。

### 3. Agent 工作流不依赖 Research Graph，也不复制对话和 Job

先以客户端与服务器 Profile 的现有 ChatKit conversation、Agent runtime、Job daemon 和持久状态为基线，验证进度展示、失败/继续、重启恢复、审批与幂等副作用。只有这些现有设施确有缺口时，才补最小、Graph-free 的 WorkflowRun 状态与事件；它关联 principal/Profile/runtime 以及可选的 Research、ReportBranch、ChatKit thread、ResearchRun、Job 和 artifact。事件只记录状态、可见进度摘要、工具/Job 引用、审批、恢复点、失败/重试与最终产物引用，不存隐藏思维链，不镜像完整聊天正文、行情数据或 Job 产物。

若需增加 WorkflowRun，它应支持继续、暂停/审批、恢复、取消、超时/预算和带幂等键的外部副作用。Agent 可动态选工具、循环、拆分并行工作或请求人类补充；模板只是启动提示和权限配置，不能用固定 DAG/节点边作为通行门禁。无论是否需要新增 WorkflowRun，都不实现第二份对话记录、回测队列、行情执行器或实验跟踪系统。

### 4. 统计和数据正确性由独立契约承载

`ResearchRun` 继续冻结配置、因子版本、数据输入引用、产品范围、日期与执行参数；Job 继续记录实际执行和结果状态。保护样本或预注册规则只有在独立验收证明其价值后才保留，并以普通 Research/Run 可选统计合同及 Run 级暴露台账表达，不依赖 Graph、Branch 或 TrialPlan。图内的其他义务、节点前置条件和报告覆盖要求不自动迁移。

因子/产品定义、报告章节和因子集合历史变化分别归各自领域。成员移除等历史事件仍由因子集合成员账本负责，不因与旧 Graph timeline 相似而并入 WorkflowRun。

### 5. 一次性完整切换与数据删除

单一集成交付必须同时完成以下边界，不能先发布“隐藏入口但保留 Graph runtime”、先让新数据脱离 Graph 却继续依赖旧 Graph、或先删 UI 再留下无法使用的研究功能：

- 普通 Research、Report/ReportBranch、ResearchRun、Job、Artifact、Evidence、因子与因子集合均能独立读写；客户端与服务器 Profile 的报告协作、跨 Branch 复制及跨服务器读取可用。
- Agent 对话/执行不要求 Graph。先复用现有 ChatKit conversation、Profile runtime、Job 和持久状态；只有在验收证明恢复、审批或进度记录缺口时，才实现最小独立 workflow 状态，不重复存聊天正文或创建第二套任务队列。
- 一次性移除 Web/Swift 页面和导航、Manager/server/client routes 与代理、CLI 命令/客户端库、Skills、Graph catalog、运行时初始化、schema 创建、Graph 专属测试/资源及全部 Graph 执行依赖。
- Graph 专属历史不迁移、不归档到新系统；切换时清理专属数据库表/文件。清理工具须先提供 `dry-run`，逐表/文件报告删除数量、保留对象引用数量、无效/未知引用和与 Report/Run/Job/Evidence 的交叉引用；不得级联删除独立领域数据。

内部可用多个提交和并行工作，但不能把部分拆除作为可发布状态；最终代码、schema、CLI/UI 和保留功能一起验收并作为一个完整切换集成。生产数据库备份、数据迁移和部署仍按仓库发布授权执行；本 ADR 不授权执行线上删除或部署。

## 后果与验收方向

- 新研究不会因缺少 Graph 版本、节点、义务或 TrialPlan 而无法开始。
- Report/Branch 的身份、权限和章节内容不再派生自 Graph；客户端与服务器 Profile 能共同访问同一逻辑报告。
- 若现有 Agent runtime 不能恢复未完成任务，则由最小 WorkflowRun 状态恢复；重复请求不会重复提交 Job 或报告变更。聊天正文仍以 Provider thread 为权威，Job 数据仍以 Job 为权威。
- 普通研究和 Agent 对话不写入 Graph 表，启动时也不重建 Graph schema。
- 一次性清理 Graph 历史时能证明 Report 正文/Branch、ResearchRun、Job、Artifact、Evidence、因子库与因子集合历史未被级联删除；Graph 专属数据不建立新的历史副本。
