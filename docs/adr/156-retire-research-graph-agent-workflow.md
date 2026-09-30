# ADR-156：退役 Research Graph，采用 Agent WorkflowRun 与独立研究对象

- **日期**：2026-09-30
- **状态**：分阶段迁移（整体跟踪见 Issue #403）
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

### 3. AgentWorkflowRun 编排 Agent 任务，不复制对话和 Job

新增的 `AgentWorkflowRun` 表示一次有目标的研究 Agent 执行。它关联执行 principal、Profile、执行 runtime/服务器，可选关联 Research、Report/Branch、ChatKit conversation/thread、ResearchRun、Job 和 artifact。其事件时间线记录状态、用户/Agent 可见进度摘要、工具与 Job 引用、审批决定、checkpoint、失败/重试和最终产物引用；不存模型隐藏思维链，不镜像完整聊天正文、原始行情或 Job 产物。

WorkflowRun 使用追加式事件和显式状态迁移，支持继续执行、暂停/审批、恢复、取消、超时/预算和带幂等键的外部副作用。Agent 可动态选择工具、循环、拆并行工作或请求人类补充；模板只是启动提示和权限配置，不能靠固定 DAG/节点边作为通行门禁。

继续复用 Profile Agent/ChatKit 的对话线程、现有 Job daemon 和 ResearchRun/Artifact 生命周期。WorkflowRun 只负责研究任务编排和可恢复状态，不实现第二份对话记录、回测队列、行情执行器或实验跟踪系统。实施前以现有设施的可恢复能力为基线，若已满足某项能力则通过稳定接口复用，不重复造轮子。

### 4. 统计和数据正确性由独立契约承载

`ResearchRun` 继续冻结配置、因子版本、数据输入引用、产品范围、日期与执行参数；Job 继续记录实际执行和结果状态。保护样本或预注册规则只有在独立验收证明其价值后才保留，并以普通 Research/Run 可选统计合同及 Run 级暴露台账表达，不依赖 Graph、Branch 或 TrialPlan。图内的其他义务、节点前置条件和报告覆盖要求不自动迁移。

因子/产品定义、报告章节和因子集合历史变化分别归各自领域。成员移除等历史事件仍由因子集合成员账本负责，不因与旧 Graph timeline 相似而并入 WorkflowRun。

### 5. 分阶段拆除与数据删除

1. 先从新建 Run、Agent 调用和报告协作中切断 Graph/TrialPlan 的硬依赖，形成无 Graph 的独立 ResearchRun 与 ReportBranch 路径。
2. 为 AgentWorkflowRun 提供与现有 ChatKit conversation、Job 和 ReportBranch 的稳定关联及恢复能力；以客户端 Profile 和服务器 Profile 验证相同语义。
3. 移除 Web/Swift 页面和导航、Manager/server/client routes 与代理、CLI 命令/客户端库、Skills、Graph catalog、运行时初始化、schema 创建和 Graph 专属测试/资源。
4. 最后清理 Graph 专属数据库表和文件。迁移工具必须有 `dry-run`，逐表/文件报告将删除数量、保留对象引用数量、无效/未知引用和与 Report/Run/Job/Evidence 的交叉引用；不得级联删除独立领域数据。

每个实现阶段使用独立 Issue、Branch/worktree、明确 Ownership 和聚焦验收。生产数据库备份、数据迁移、部署另按仓库发布授权执行；本 ADR 不授权执行线上删除或部署。

## 后果与验收方向

- 新研究不会因缺少 Graph 版本、节点、义务或 TrialPlan 而无法开始。
- Report/Branch 的身份、权限和章节内容不再派生自 Graph；客户端与服务器 Profile 能共同访问同一逻辑报告。
- 重启后可从持久 WorkflowRun 状态恢复尚未完成的 Agent 任务；重复请求不会重复提交 Job 或报告变更；聊天正文仍以 Provider thread 为权威，Job 数据仍以 Job 为权威。
- 普通研究和 Agent 对话不写入 Graph 表，启动时也不重建 Graph schema。
- 删除 Graph 历史前能证明 Report 正文/Branch、ResearchRun、Job、Artifact、Evidence、因子库与因子集合历史未被级联删除；Graph 专属数据不建立新的历史副本。
