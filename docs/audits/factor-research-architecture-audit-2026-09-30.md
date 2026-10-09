# FactorTester 因子研究架构缺陷与改进清单

- 审计日期：2026-09-30（Asia/Taipei）
- 基线：本机缓存 `origin/feat@9d35ee47f33cbc756103626a9a9eaeeb57631030`（本次 GitHub fetch 因 HTTP/2 framing error 失败；不据此声称已核实最新远端 HEAD）。
- 范围：研究数据身份、RunSpec/ExecutionPlan、因子源码版本、受保护样本暴露、因子执行后端、研究报告协作及相关 Issue/ADR 状态。
- 证据边界：以下标为“已证实”的项目由当前源码、测试或仓库记录直接支持；这不等于已证明生产历史结果实际出错。未实际访问生产业务数据，也未运行生产任务或迁移。

## 结论与当前架构基础

FactorTester 已有若干可独立保留的核心边界：因子 DSL 的批量/增量执行分离、冻结的因子身份和源码版本、产品组与提交时产品范围快照、RunSpec/ExecutionPlan/Job 生命周期、结果 artifact 哈希、因子集合成员历史以及跨服务器研究目录基础设施。部分样本保护和研究流程目前仍耦合于 Research Graph/TrialPlan，需要在整体切换中迁到 Run 级规范边界。统计设计已把比较、样本角色、停止规则和多重检验计划纳入 TrialPlan；这只证明旧设施表达过这些概念，不意味着 TrialPlan 或 Graph 必须保留。

用户已明确决定整体退役 Research Graph，Graph 专属历史无需保留。报告正文、Report Branch 和跨服务器协作继续保留为独立领域对象；ResearchRun、Job、因子与样本正确性只有在能独立于 Graph 工作时才继续保留。不能把 Graph 历史搬进另一套节点/义务系统。

另外，当前可证实的研究证据缺口包括：保护样本只比较完全相同的产品范围；运行时因子版本校验仍依赖当前目录，即使 RunSpec 已冻结历史公式。此前将“行情内容版本未绑定到运行身份”列为缺陷，经用户确认后已改为产品决策：平台以稳定 source key 标识数据源，源内数据变化由数据源自己管理；重新计算读取同一来源的当前数据，不要求平台保留旧行情字节。真正需要修正的是 availability profile 曾把文件元数据指纹误标成行情快照并声称可重放。

源码与规范显示 Graph/Branch/TrialPlan 不只是历史关系视图：它们还参与研究路径状态、运行绑定、Evidence admission 和执行检查点。用户决定这些设施整体剥离、Graph 历史不留存；与之相连但有独立价值的报告、Run/Job 和统计正确性必须先落到自己的身份与生命周期，再删除 Graph 代码和数据。

## 成熟研究架构参照

Research Graph 全量移除的初始路径审计清单见[候选文件清单](research-graph-removal-manifest-2026-09-30.md)；清单命中项须逐个判定，不能机械删除。

公开实现提供的是可借鉴的工程模式，不是必须照搬的规范：Microsoft Qlib 将行情数据准备、Data Loader、Data Handler、Dataset 与缓存分层；其 Experiment/Recorder 按实验组织单次运行，并保留参数、指标和 artifacts；需要批量试验时另有 task generation、storage、training、collection 生命周期。Alphalens 把单因子诊断聚焦在带日期、资产、因子值、前瞻收益期与可选分组的数据集，输出 IC、分位数组合收益、换手等诊断。mlfinlab 的交叉验证实现将标签信息区间用于 PurgedKFold，并支持 embargo，体现了时间区间重叠应进入验证边界的原则。QuantConnect 建议先在交互式 Research 环境分析假设和统计显著性，再用较慢的事件驱动回测验证，并允许研究代码导入回测项目。Microsoft 的 RD-Agent(Q) 采用 Research → Development/代码实现 → 回测 → Feedback 的迭代闭环，并动态选择下一步任务；论文把它描述为 Agent 研究过程，而不是要求研究者先维护固定的通用知识图。

据此，本平台的成熟度差距不在“缺少一个通用因子平台”，而在已有 RunSpec、Job 与 artifact 是否都指向可复核的数据/源码版本，以及保护样本和标签时间范围能否证明没有重叠。Agent 侧要先审计现有 ChatKit conversation、Profile runtime 与 Job 恢复能力；缺口再由轻量 WorkflowRun 填补。研究设计只应以独立、可选的统计合同约束需要预注册的高风险任务。用户已决定彻底移除 Graph，而非仅降低它的强制程度；不重复建设 experiment tracker、固定 DAG 或另一个 Job 队列。

参考： [Qlib 论文](https://arxiv.org/abs/2009.11189)、[Qlib Recorder](https://qlib.readthedocs.io/en/stable/component/recorder.html)、[Qlib task management](https://github.com/microsoft/qlib/blob/main/docs/advanced/task_management.rst)、[Alphalens 因子分析与 tear sheets](https://quantopian.github.io/alphalens/)、[mlfinlab PurgedKFold 实现](https://github.com/hudson-and-thames/mlfinlab/blob/master/mlfinlab/cross_validation/cross_validation.py)、[QuantConnect Research Engine](https://www.quantconnect.com/docs/v2/research-environment/key-concepts/research-engine)、[RD-Agent(Q) 论文](https://arxiv.org/abs/2505.15155) 与 [官方实现](https://github.com/microsoft/RD-Agent)。

## Research Graph 与 Agent 工作流基础设施复核

### 外部框架呈现出的分层

| 框架 | 一手资料中可核验的做法 | 对 FactorTester 的启示 |
| --- | --- | --- |
| Qlib | Recorder 用 `Experiment → Recorder(run)` 组织参数、指标、生成物和运行状态；task management 再独立负责任务生成、存储、训练和收集。 | 实验记录与运行调度是不同边界。已有 `ResearchRun`/`Job`/artifact 应形成统一、可比较的执行记录，不要让研究拓扑图承担队列和 Agent 调度。 |
| Alphalens | 单因子数据结构以 date × asset 为基础，明确放入因子值、多个 forward-return horizon 和可选 group；标准产物是 IC、quantile returns、turnover 与诊断图。 | 统计验收应是确定性、可复算的分析模块和结果契约；不是可视图拓扑才能表达的知识对象。 |
| QuantConnect Research/LEAN | 先用 notebook 检验假设和统计显著性，再用事件驱动 backtest 验证；研究代码可复用到 backtest，LEAN 以事件流防止在回测中读取未来数据。 | Agent 可动态探索，但从研究观察到正式回测必须跨过明确的数据时间、回测语义与验证边界。无需把探索过程固定成唯一节点路径。 |
| Microsoft RD-Agent(Q) | 论文描述动态提出假设、生成开发任务、执行代码/回测、基于反馈继续迭代，并根据反馈调度方向；这是 Agent loop 与任务反馈闭环。 | 工作流运行时要容纳循环、分支、重试与用户介入；固定 DAG 可以是一次执行计划的可选呈现，不应成为通用 Agent 的唯一控制模型。论文中的绩效数字是作者实验结论，本审计未独立复现。 |
| OpenAI Agents SDK / Temporal | Agent SDK 提供 tools、handoffs、guardrails、sessions、人工审批和 tracing；Temporal 把 LLM/API/DB 等非确定性外部操作放到 Activity，工作流通过持久历史 replay/resume。 | 运行时要显式记录工具步骤和状态，支持断点续作、幂等副作用、权限/审批和可观察性。这里借鉴能力边界，不等于决定引入任一特定第三方依赖。 |

一手资料：[Qlib Recorder](https://qlib.readthedocs.io/en/stable/component/recorder.html)、[Qlib Task Management](https://github.com/microsoft/qlib/blob/main/docs/advanced/task_management.rst)、[Alphalens](https://quantopian.github.io/alphalens/)、[QuantConnect Research Engine](https://www.quantconnect.com/docs/v2/research-environment/key-concepts/research-engine)、[RD-Agent(Q) 论文](https://arxiv.org/abs/2505.15155)、[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)、[Agents SDK 人工介入](https://openai.github.io/openai-agents-python/human_in_the_loop/)、[Temporal 持久工作流](https://docs.temporal.io/)。

### 对当前实现的判断

- **用户反馈（产品证据）：** 用户认为 Research Graph 没有带来足够帮助，固定路径限制实际研究。本报告没有线上用户任务统计来量化比例。
- **源码/文档事实：** `docs/research-decision-graph/CONTEXT.md` 定义 Graph 节点、边、entry requirements、obligations、report methods 和 transition governance；`server/services/research_graph/branch/transition.py`、`trial_plan/binding.py`、`evidence_admission.py` 与执行 checkpoint 把版本化拓扑和 TrialPlan 贯穿到状态迁移、运行绑定和 Evidence admission。TrialPlan 已演进多个 schema 版本，部分 resolver/能力仍被工作包记录为未完成。这证实维护面和认知负担很大，但不能单凭规模断定所有 Graph 用例都无价值。
- **架构推断：** 同一结构同时承载“研究方法、Agent 导航、执行检查、Evidence 资格、报告映射”会形成过宽的变更半径；自由研究没有合适图路径时容易被结构挡住，扩展规则又要求版本治理。它与 Qlib/Alphalens 的确定性研究对象层、RD-Agent 的开放迭代环节不是同一职责。
- **尚未证实：** Graph 当前造成多少 Agent 失败、用户绕路、无效 API/数据库维护或运行延迟；不应编造收益估算。退役目标来自用户明确产品决定，收益验证不构成保留 Graph 的前置条件。

### 建议方向

用户已明确决定**一次性完整移除 Research Graph 设施，Graph 历史内容不需要保留**。目标不是继续保留只读 Graph 投影视图，也不是逐步发布一个仍依赖 Graph 的过渡产品；完整切换时须同时把仍需的研究能力落在独立研究对象和 Run 生命周期，并删除 Graph 专属 UI、API、CLI、运行时、schema 和历史数据。完整决策已落为 [ADR-156](../adr/156-retire-research-graph-agent-workflow.md)：

1. **只保留独立验证后仍有价值的研究事实与统计护栏。** Research/成员、Report/Branch、冻结因子版本、RunSpec、数据快照、Job、指标/产物引用、样本角色、holdout 暴露台账、权限与审计按各自领域建模。TrialPlan 不视为必须保留；需要的多重检验、预注册、保护样本规则，应拆成小型可选的统计合同和 Run 级暴露校验，不要求一般探索、报告撰写或 Agent 对话先走整套 TrialPlan。
2. **先审查 Agent 工作流现状，只补实证缺口。** 检查 `research_id + report_id/branch + principal/profile + runtime server` 身份关联、可分页进度、工具/Job 引用、审批、断线和重启恢复、幂等副作用。只有现有 ChatKit conversation、Profile runtime 和 Job 不能满足明确验收时，才增加最小 WorkflowRun 状态；记录可见进度，不保存模型隐藏思维链，也不复制对话/Job。
3. **复用现有持久 Job 与 Agent 权限边界。** LLM/CLI/Manager I/O 作为可重试、有幂等键的活动；长任务可暂停、恢复、取消、超时和预算封顶。回测仍走当前 Job daemon；Agent workflow 负责调用与编排，不复制调度队列或运行行情逻辑。先验证 SQLite 持久事件 + 当前调度器是否满足单机与客户端场景，再评估 Temporal/DBOS 等外部持久编排引擎。
4. **删除 Graph 特有历史与存储。** Graph 节点/边、Claim/obligation、Graph YAML/版本、旧 TrialPlan、Graph traces、专属 checkpoint 和偏好均不迁成另一种“Graph 历史”。用户已明确这些历史内容无需保留；迁移仍须 dry-run 报告对象/表行/引用数量、检查非 Graph Run/Job/Report/Evidence 是否被 Graph 外键或业务字段错误级联影响、提供备份和回退点，再删除 Graph 专属表和字段。独立 RunSpec、Job、Artifact、Research、Report 和 Factor 数据不跟随 Graph 历史一起删除。
5. **同一完整交付移除所有 Graph 切面。** 最终集成必须同时包含正常 Agent 研究和 Run 不再创建、读取或写入 Graph/TrialPlan，Web 与 Swift 入口、HTTP 路由/Manager 代理、CLI 命令/客户端库、Skills、后台初始化与 catalog、Graph schema/migrations 及专属历史数据清理方案；不能发布只隐藏入口、只切新写入或仍会自动重建 Graph 表的中间状态。

Agent workflow 也不应变成另一张固定图；应先审查现有 ChatKit conversation、Profile runtime 和 Job 的可恢复能力，只在明确缺口上补最小状态/事件。代码可以分提交实现，但完整方案需在同一次集成中验证，避免留下仍依赖 Graph 的运行入口。

## 更新后的顺序化改进队列

### 2026-10-03 补充：研究链路交付顺序与验收

用户提供的两版架构审计进一步明确了目标：研究结论必须能追溯所用数据、可用时间、候选试验、选择样本、真正样本外结果与扣费后收益。以下是**待实施/验收清单**，不是已完成声明。重复描述已合并；已有 HAC、日内分区聚合、容量限制和多因子 RunSpec 应先验证并贯通，不能重新立项为从零实现。

| 顺序 | 交付范围 | 必须证明的验收点 |
| --- | --- | --- |
| A | 确定性 research golden suite 与代表性性能基线 | 未来数据扰动不改变过去信号；信号/可用/成交/标签时间对齐；夜盘、缺 bar、合约展期、平今/平昨及部分成交账本可手算复核；记录数据规模、机器、缓存冷热、样本数、耗时和内存，合成测试不能冒充线上 p95。 |
| B | #403 一次性完整移除 Research Graph，纳入 #402 普通 Run 的保护样本规则 | Graph UI/API/CLI/Swift/runtime/schema/专属历史均不再被正常路径读取或创建；Research、Report/Branch、Run/Job/Artifact/Evidence、Profile Agent 保留；冻结产品成员与日期交集、幂等和并发检查通过。此包不能拆成线上半成品。 |
| C | 数据源身份、更新语义与数据质量观察 | RunSpec 绑定稳定 source key 和查询范围；内容刷新、版本留存与 cache freshness 由数据源管理；availability profile 区分来源/覆盖观察与数据内容版本；不得以 mtime 作为内容哈希。 |
| D | 已注册 IC 附加分析的正式入口与结果链 | Web/CLI 均能配置、冻结、执行、持久化并显示滚动稳定性、分期诊断、自相关、分组统计与前瞻衰减；每个去重核心测试只求值一次，新增统计复用保留输入。 |
| E | 最小滚动样本外验证与拟合状态冻结 | 训练/验证/测试按时间及标签信息区间隔离；每折的预处理和参数选择只见本折训练数据；保留逐折输入、拟合状态、选择依据和拼接后的 OOS 结果。 |
| F | 试验族台账与统计校正 | 记录成功、失败和被拒候选，重试不计新假设；预先冻结试验族后实现 FDR 与时间块 bootstrap；DSR/PBO 仅在输入条件可验证时开放，不替代 OOS。 |
| G | 成本、容量和收益归因 | 基于现有费用、滑点、参与率、部分成交和剩余订单机制校准及压力测试；逐步解释诊断收益到可交易净收益的差距，连续价格研究与实际合约成交分开。 |
| H | 多因子边际贡献 | 同一快照、样本外区间、成本和风险约束下，比较加入因子前后的增量诊断与净收益；不能以“多个因子能提交”代替组合研究。 |

执行时先按当前代码重新核对每项状态，避免把本次静态审计中的推断当作线上已证实故障。C—H 涉及跨模块契约，应各自建立含 Ownership、依赖与验收标准的 Issue；不能借 #403 扩张为另一套研究图或隐藏的 Job 队列。

1. **Research Graph 全量移除（Issue #403）**：外部框架比较、静态依赖盘点和 ADR-156 已完成。Graph 历史不迁移保留；Report/Branch、ResearchRun/Job、因子/样本保护、Profile Agent 等正常能力必须在同一集成范围内确认脱离 Graph，再与 Graph UI/API/CLI/Skills/runtime/schema/data 清理一起验收；不得分批发布退役。
2. **保护样本范围重叠（F-01，Issue #402）**：目标保留为普通 ResearchRun 级样本暴露检查，不再依赖 Graph TrialPlan。独立实现提交 `cbe0781f3` 仍只在本地任务分支，计划随完整 Research Graph 移除工作一并审查和集成；不作为单独发布。
3. **数据源身份与源内更新语义（F-02，P2）**。
4. **冻结因子历史解析（F-03，P1）**。
5. **旧报告 publication fork（F-05，P2，Issue #396）**。
6. **外部框架交易日透传（F-04，P2，Issue #397）**。
7. **研究统计实现与 Evidence 绑定验收（P2）**：按 IC/收益对齐、费用/滑点、时间切分、异步合约日历、缺失值、多重检验逐项校验，区分统计规范、执行结果和 Agent 文本。
8. **策略和执行能力矩阵（P2）**：核对 entry/exit、订单生命周期、流动性、Buying Power、净额化与 ADR-046，关闭重复/已完结候选须按仓库授权规则执行。
9. **真实规模性能基线（P3）**：记录样本和产物规模、机器/运行时、缓存冷/热和耗时统计后再优化。

## Agent 工作流参考来源

- [Qlib Recorder：Experiment、Recorder 与参数/指标/产物](https://qlib.readthedocs.io/en/stable/component/recorder.html)
- [Qlib Task Management：任务生成、持久任务、训练与收集](https://github.com/microsoft/qlib/blob/main/docs/advanced/task_management.rst)
- [Alphalens：因子收益、IC、换手与分组诊断](https://quantopian.github.io/alphalens/)
- [QuantConnect Research Engine：交互探索、统计检验与事件回测的边界](https://www.quantconnect.com/docs/v2/research-environment/key-concepts/research-engine)
- [RD-Agent(Q) 论文：Research/Development/Feedback 多 Agent 迭代](https://arxiv.org/abs/2505.15155)
- [OpenAI Agents SDK：工具、handoff、session、审批与 tracing](https://openai.github.io/openai-agents-python/)
- [Temporal Workflow Definition：外部 I/O 作为 Activity 与确定性 replay](https://docs.temporal.io/workflow-definition)

## 已证实缺陷与能力缺口

| ID / 优先级 | 发现与证据 | 影响与改进方向 | 状态 |
| --- | --- | --- | --- |
| F-01 / P1 | **保护样本暴露检查漏掉部分产品范围重叠。** 原查询按 `sample_universe_hash` 完全相等、日期相交来查历史暴露；旧身份模块明确列出 `partial_universe_overlap_not_detected`。 | 一个验证/holdout 运行可以换成部分重叠或超集产品，旧检查不会识别既有暴露。独立 Run 级规则已保存冻结产品成员，并按日期和成员交集判断；旧成员快照缺失/损坏时会明确失败。 | [Issue #402](https://github.com/maix00/FactorTester/issues/402) 的独立提交 `cbe0781f3` 仅在本地分支，须纳入 #403 完整切换审查，不单独合并或发布。 |
| F-02 / P2 | **Availability 曾将文件元数据误报为行情快照。** `planning.py::_backtest_plan` 与 `build_execution_plan` 使用解析后的数据源 key、产品、频率、字段及日期范围；行情内容 revision、文件 mtime/大小和行数不参与计划身份，这是允许同一来源更新后重新计算的预期行为。旧 `parquet_footer.py` 的 `snapshot_ref` 仅由文件元数据构成，却被标记为 `replayable: true`。 | 继续以稳定 source key 作为平台侧行情身份。新计算从同一数据源读取其当前数据；源内修订、留存和 cache freshness 由数据源负责。不同 source key 或运行范围变化仍会使计划身份改变。平台不承诺数据源演进后的逐字节复现，也不引入全局快照/版本门禁；availability profile 只描述 source 身份和当次覆盖观察。 | Issue #404 修正 profile 声明并增加同源数据更新/换源测试；未发现源内更新导致计算被拒的线上证据。 |
| F-03 / P1 | **冻结因子历史版本与 RunSpec 校验路径不一致。** `factor_revisions.py::assert_run_spec_factor_revisions_current` 对已经冻结的 RunSpec 再调用 `_assert_factors_current`；`planning.py::build_execution_plan` 在规划/验证时调用它。另一方面，`factor_param_resolver.py::_resolve_frozen_factor` 和 ADR-146 支持按冻结 fingerprint 加载历史源码。当前 `test_factor_revision_manifest.py` 覆盖“当前公式变化后报错”，没有覆盖“冻结 v1、编辑到 v2、旧 Run 仍解析 v1”。 | 当前目录变化可能挡住仍能按历史 fingerprint 精确解析的冻结 RunSpec，削弱重试和复现。新 Run 冻结时检查当前目录；冻结后的执行只按不可变 ref/fingerprint 解析历史源码和依赖，历史字节缺失、哈希不符或身份不完整时才失败。完整重试影响范围尚需回归测试确认。 | 待建 Issue 与冻结后编辑回归测试。 |
| F-04 / P2 | **`groupby_scope(trading_day)` 在外部回测适配器上没有交易日来源。** `FactorStepAdapter.update` 支持显式接收 `trading_day`，但 Qlib、Backtrader、Zipline 的因子适配器调用没有传入该值。核心现在会显式拒绝缺少交易日的流式计算，避免把夜盘错误归到日历日。 | 三种 worker 后端上无法使用交易日作用域增量因子。应从框架/数据源的权威交易日映射透传；没有权威信息时继续显式拒绝。该项属于 #397 的现有写入范围/Claim，本任务不接管也不修改其文件。 | #397 仍 OPEN，保留现有 Claim，等待该任务结束后再评估。 |
| F-05 / P2 | **旧 publication 的 fork 兼容尚未完成。** Issue #396 的验收说明指出旧 main publication 没有 authoring bundle，writer branch 表为空，因此无法按新协作协议 fork；Issue #396 仍 OPEN、`ready-for-agent` 且没有 Claim/完成记录。 | 用户无法从某些旧报告准确继承可编辑章节和附件。应提供显式、幂等的兼容准备流程；缺源码或资源时明确拒绝，不能从渲染文本伪造，也不能建空分支冒充 fork。 | 下一项或随后按优先级处理；必须按 #396 Ownership 实施。 |
| F-06 / P2 | **ADR/上下文与真实实现状态不一致。** `CONTEXT.md` 与 `docs/development-environment.md` 的 Conda 环境名称需一致；ADR-148/#381、ADR-149/#382 与 ADR-154/#394 的状态也需同各自 Issue 生命周期核对，旧 publication fork 仍由 #396 跟踪。 | 过时状态会让 Agent 重复实现，或运行错环境。应更新知识入口与 ADR 的当前状态，并明确 #396 遗留边界；不要把活动中的 ADR-155/#397 标成完成。 | 本审计更新了 Research Graph 退役决策文档；F-06 环境/ADR 状态核对仍待单独完成。 |

## 其他研究正确性与性能审核（Graph 完整切换后）

按研究结论可信度、回归风险和依赖排序。Graph 完整切换作为一个集成目标；其余独立缺陷另按各自 Issue/Ownership 推进。跨模块 schema、API 或数据迁移先写验收与兼容策略。

1. **行情 source 身份与更新语义（F-02，P2，Issue #404）**：确保 RunSpec 以稳定 source key 和查询范围为身份；同源更新后的新计算继续读取 source 当前数据，换源/改范围则重新规划。availability profile 不得把元数据 marker 宣称成内容版本或精确重放；不建设平台级行情快照协议。
2. **统一冻结因子解析（F-03，P1）**：先复现 v1 freeze → 当前源码编辑为 v2 → v1 Run 重试；验证嵌套依赖、历史源码缺失和新 Run 的当前版本门禁。
3. **旧报告 publication fork 兼容（F-05，P2，Issue #396）**：复用独立 ReportBranch 与对象传输协议，验证旧 publication、资源完整性、重试、权限和不同 Profile 身份。
4. **外部框架交易日透传（F-04，P2，Issue #397）**：等现有 Claim 完成后复核，不与活动写入者重叠。
5. **研究执行方法学验证（P2，待审计）**：用合成价格序列校验 IC/收益滞后、异步产品时间对齐、费用/滑点、截面排序、缺失值和独立统计合同实现；不得仅凭旧 TrialPlan schema 断言正确或缺失。
6. **决策策略与执行能力矩阵（P2，待审计）**：ADR-046 的 `待实现` 状态需要与现存 entry/exit、订单生命周期、流动性、Buying Power、净额化实现和测试逐项核对；只为确实缺少验收的语义创建后续任务。
7. **真实规模性能基线（P3，待审计）**：记录真实数据规模、对象大小、机器/运行时、缓存冷/热、样本数与耗时分布后，再优化列表目录、因子求值和 Job/报告传输。当前审计没有生产负载基线，不对线上 p95 作判断。

## GitHub Issue 生命周期与范围复核

本次在 2026-09-30 定向审阅了近期提交与因子研究/回测/研究报告相关的 OPEN Issues。无法访问 GitHub 最新远端时以本机缓存 `origin/feat@9d35ee47` 和 Issue 当前可读生命周期记录交叉检查；没有做全仓所有领域 Issue 的关闭扫描。

### 有 Done-by/Released-by、且引用提交已进入本机 origin/feat 的 OPEN 候选

下列 Issue 仍显示 OPEN，评论里有完成、合并或部署记录，且本机缓存的 `origin/feat` 提交历史包含对应 `refs #N`：

- 2026-09：[#388](https://github.com/maix00/FactorTester/issues/388)、[#389](https://github.com/maix00/FactorTester/issues/389)、[#390](https://github.com/maix00/FactorTester/issues/390)、[#391](https://github.com/maix00/FactorTester/issues/391)、[#392](https://github.com/maix00/FactorTester/issues/392)、[#393](https://github.com/maix00/FactorTester/issues/393)、[#394](https://github.com/maix00/FactorTester/issues/394)、[#395](https://github.com/maix00/FactorTester/issues/395)、[#398](https://github.com/maix00/FactorTester/issues/398)、[#399](https://github.com/maix00/FactorTester/issues/399)、[#400](https://github.com/maix00/FactorTester/issues/400)、[#401](https://github.com/maix00/FactorTester/issues/401)。
- 2026-08：[#351](https://github.com/maix00/FactorTester/issues/351)、[#352](https://github.com/maix00/FactorTester/issues/352)、[#355](https://github.com/maix00/FactorTester/issues/355)、[#359](https://github.com/maix00/FactorTester/issues/359)。#355/#359 有生产部署回执；#351/#352 有部署验收回执。
- 2026-05 至 06：[#63](https://github.com/maix00/FactorTester/issues/63)、[#64](https://github.com/maix00/FactorTester/issues/64)、[#65](https://github.com/maix00/FactorTester/issues/65)、[#67](https://github.com/maix00/FactorTester/issues/67)、[#74](https://github.com/maix00/FactorTester/issues/74)、[#77](https://github.com/maix00/FactorTester/issues/77)、[#79](https://github.com/maix00/FactorTester/issues/79)、[#81](https://github.com/maix00/FactorTester/issues/81)、[#118](https://github.com/maix00/FactorTester/issues/118)、[#120](https://github.com/maix00/FactorTester/issues/120)。其中一些评论只证明本地合并或单测，仍要核验其最终实现/验收目标是否完整，再决定是否关闭；“提交进入 feat”本身不是完整验收证明。

### 仍需保留、重新认领或解决父子范围的 OPEN Issues

| Issue | 复核结论 |
| --- | --- |
| [#402](https://github.com/maix00/FactorTester/issues/402) | 保护样本目标保留，但旧实现依赖 Graph TrialPlan；已重定义为 Run 级独立规则并提交到本地分支，须与 #403 一次性移除完整集成，不单独发布。 |
| [#396](https://github.com/maix00/FactorTester/issues/396) | 旧 publication 缺失 authoring bundle 的 fork 兼容缺口；未见完成记录，保留。 |
| [#397](https://github.com/maix00/FactorTester/issues/397) | `groupby_scope` 有活动写入 Claim 与适配器交易日来源缺口；不接管、不改其范围。 |
| [#173](https://github.com/maix00/FactorTester/issues/173) / [#182](https://github.com/maix00/FactorTester/issues/182) | #173 是 IC 方法学/语义母 Issue，#182 是实现切片；#182 有 Claim 但长时间无新进展。不是重复单，应核验实现 worktree 后决定续作或调整范围。 |
| [#302](https://github.com/maix00/FactorTester/issues/302) / [#304](https://github.com/maix00/FactorTester/issues/304) | #302 明确是父/产品决策与验收总项，#304 是 Delay 批次和多产品范围 Job 切片；均无完成评论，保持父子关系。 |
| [#114](https://github.com/maix00/FactorTester/issues/114) / [#121](https://github.com/maix00/FactorTester/issues/121) / [#129](https://github.com/maix00/FactorTester/issues/129) | #121 明确取代 #114 的架构部分；#129 是要求审查异步计算计划的独立只读交付，但目前未见审计结论。需要按现存 `tools/backtest/`、Job/SSE 实现和 ADR-009/010 逐项核销，避免继续在旧原型和新架构上重复工作。 |
| [#314](https://github.com/maix00/FactorTester/issues/314) | 仍为账本/资金池结果能力，依赖 #312；无完成评论，不属于可关闭候选。 |
| [#78](https://github.com/maix00/FactorTester/issues/78) | 只有旧 Claim 评论、未见完成回执；需检查原 Claim/worktree 与当前测试后重新认领或关闭。 |
| [#127](https://github.com/maix00/FactorTester/issues/127) | 具体期限结构/Carry 因子能力缺口；未见完成回执，保留待范围核验。 |
| [#384](https://github.com/maix00/FactorTester/issues/384) | 最新记录按用户要求暂停；不视为完成。 |
| [#403](https://github.com/maix00/FactorTester/issues/403) | Research Graph 一次性全量移除的唯一集成 Issue：研究报告等正常功能保留并解耦，Graph 专属历史不保留；不得分阶段发布。 |

此外，2026-05 至 06 的其他 OPEN 旧条目仍在因子/回测搜索结果中；这次没有据标题猜测已完成。下一次范围复核应读取 Issue 全文、生命周期评论、最新 worktree/Claim，再把可确认的已实现工作写入 `Done-by`，不将历史本地合并误认为部署。

仓库规则要求 Issue 关闭单独授权，因此本次只记录候选与范围关系，没有调用关闭操作。工作区/任务分支的归档与清理同样不在本审计授权范围内。

## 已审查但未认定为缺陷的部分

- 旧 TrialPlan/Research Graph schema 曾表示样本角色、比较计划、停止和多重检验设计；根据用户决定它们不是必须保留的领域对象。需要的规则应独立验收后实现，不把旧 schema 本身当成目标。
- RunSpec 已冻结因子身份、配置版本、产品范围和部分生成物；问题在于行情数据输入及历史因子版本执行门禁仍不完整，不是所有运行输入都未冻结。
- 交易日作用域缺失会显式失败；这是后端能力缺口，不是当前观察到的静默错误结果。
- 本审计没有证明特定用户、研究报告或生产回测数据已因此产生错误结果。
