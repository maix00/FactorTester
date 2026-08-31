# Grill 179 — v8 义务分类与逐节点/逐边报告映射

Status: closed; Grill 179.1–179.50 accepted/revised, with the canonical
handoff in 179.48, the historical-time addendum in 179.49, and the
run-configuration/formula/equity-curve projection in 179.50.

> **Implementation warning:** Sections 3–8 below preserve the initial proposal and are
> not a canonical implementation map. Grill 179.1–179.40 subsequently renamed or
> removed several categories, moved capability and Evidence qualification out of the
> Verification Obligation Catalog, split strategy design from external market/accounting
> rules, and added User Acceptance Obligations. Implementation must use the final
> consolidated map produced after this grill; it must not copy the initial tables merely
> because they appear earlier in this file.

## 1. 基线与不可变边界

本规划以服务器当前 active pointer 指向的 `factor-research@v8` 为事实基线：

- content hash: `8fa0bf865c245a81ebd34411e385983cb7e7154ac5eddc4a88d61602cd413b54`
- 15 个节点；
- 29 条显式边；
- entry node: `hypothesis_preregistration`。

v8 已经不可变，以下 contract 不能回写进原 v8 JSON。这里“进入 v8”的含义是：

1. 对当前 v8 研究历史执行一次性本地报告迁移；
2. 将完整 contract 发布为 v8 的后继 Graph 版本；
3. 只有用户明确选择的 v8 分支才通过 continuation 进入后继版本；
4. continuation 保留同一 Work Package、同名当前节点、旧 Evidence 和原始审计链。

## 2. Requirement Catalog contract

每个大类和小类不是标签，而是类似 Skill 入口的可读 contract：

```json
{
  "requirement_id": "data.realtime_l2_availability",
  "revision": 1,
  "title_zh": "目标产品是否有实时 L2 数据",
  "question_zh": "在授权产品、市场和试验所需时段内，是否存在可合法使用且延迟满足要求的实时 L2 行情？",
  "select_when_zh": "TrialPlan、因子或策略依赖盘口深度、价位队列、买卖盘或实时微观结构。",
  "evidence_expected_zh": ["数据源和产品覆盖", "L2 深度定义", "延迟或时间戳测量", "权限与允许用途"],
  "not_sufficient_zh": ["只配置了 connector", "供应商宣传支持 L2", "只有延迟 L2 却按实时使用"],
  "home_node": "data_contract",
  "report_method_refs": ["inventory", "adjudicate"]
}
```

Research Agent Skill 读取该 contract 后选择大类/小类、绑定具体义务或提出新候选。
Graph 版本控制这些定义；运行时只按当前节点/边和 Agent 请求渐进返回。

## 3. 最小稳定义务大类（名称待逐类 Grill）

大类保持少量和稳定；小类可以随 Graph 版本扩展。`other` 只承接尚未完成分类的
具体义务，不能满足任何专门 entry requirement。

| 大类 ID | 中文含义 | v8 所需核心小类 |
|---|---|---|
| `decision_scope` | 研究问题、可证伪机制和决策边界 | `mechanism_falsifiability`, `decision_boundary`, `permitted_use`, `candidate_scope` |
| `data` | 当前研究所需要的数据是否存在、能否合法取得、何时可见、覆盖什么范围，以及是否足以执行 TrialPlan；由现有 `data_contract` 节点作为主要定义/处理位置 | 见下一节的首版具体目录 |
| `factor_semantics` | 因子表达式与经济、数值及时序语义 | `economic_mechanism`, `expression_validity`, `causal_timing`, `expression_parameterization`, `derived_comparability`, `conditional_factor_role` |
| `trial_validity` | TrialPlan 能否检验义务而不泄漏或扩张选择 | `discharge_alignment`, `sample_partition`, `holdout_separation`, `multiplicity_ledger`, `transportability_design`, `stopping_rule` |
| `statistical_validity` | 统计量、估计不确定性与选择偏差 | `cross_sectional_predictiveness`, `quantile_monotonicity`, `uncertainty`, `selection_bias`, `robustness_preconditions` |
| `execution_accounting` | 信号、策略、成本和产品会计语义 | `signal_schedule`, `session_boundary`, `accounting_fidelity`, `cost_capacity`, `contract_roll` |
| `evidence_integrity` | Job、结果、后端与主张证据资格 | `job_terminal_integrity`, `artifact_completeness`, `backend_assurance`, `claim_scope`, `conflict_resolution`, `evidence_qualification` |
| `research_decision` | 下一试验、结论边界与研究结束 | `decision_disposition`, `next_trial_value`, `search_exhaustion`, `bounded_unknown` |
| `capability_governance` | 能力绑定、Skill、代码修复与发布 | `binding_suitability`, `product_support`, `gap_impact`, `skill_fit_and_safety`, `backend_change`, `rollout_and_rollback` |
| `other` | Agent 发现了会改变研究决定的问题，但当前目录没有合适大类 | 无固定小类；必须保留问题描述，图升级时优先重分类 |

## 4. `data` 大类首版可选择目录

大类描述：判断当前研究所需的数据服务、历史、字段、时点和授权是否真实存在并
覆盖 TrialPlan。连接器存在、账户已配置或供应商宣传页均不能单独满足数据义务。

| 小类 ID | Agent 看到的中文问题 | 何时选择 | 最少需要的证据 |
|---|---|---|---|
| `data.product_source_availability` | 有没有数据源提供目标产品或合约？ | 研究范围包含尚未确认的数据源/产品，或准备扩展市场 | provider、venue、product/contract、频率/深度、允许用途的实际 availability 结果 |
| `data.realtime_l2_availability` | 目标产品有没有可用的实时 L2 数据？ | 因子/策略依赖盘口深度、队列、价位或实时微观结构 | L2 定义、产品覆盖、实测延迟/时间戳、权限、连续性；仅有 connector 不足 |
| `data.delayed_l2_availability` | 如果没有实时 L2，是否有明确延迟口径的 L2 数据？ | 研究可使用延迟流、仿真实盘或需要区分实时与延迟结论 | 延迟时长/分布、时间戳语义、产品覆盖、可用时段和用途限制 |
| `data.realtime_l1_availability` | 目标产品有没有可用的实时 L1 数据？ | 实盘/准实时检验只需最优价、成交或基础报价 | L1 字段定义、实时性测量、产品覆盖、权限与断流记录 |
| `data.historical_l1_availability` | 目标产品有没有历史 L1 数据？ | TrialPlan 使用历史报价/成交或需要和实时/延迟数据对齐 | 起止时间、频率、字段、合约覆盖、缺口、来源和版本 |
| `data.historical_l2_availability` | 目标产品有没有历史 L2 数据？ | 回测微观结构、盘口或执行假设 | 深度级数、快照/增量语义、起止时间、缺口、重建规则和来源 |
| `data.trial_window_coverage` | 数据起止范围和缺口是否覆盖当前 TrialPlan？ | TrialPlan 已提出产品、频率和时间窗口 | 每个必需字段/产品/频率与 Trial window 的确定性交集、缺口和可用样本 |
| `data.field_history_coverage` | 保证金、手续费、合约规则等历史字段是否真实覆盖试验？ | 会计或策略语义依赖会随时间变化的字段 | 字段值历史、有效时点、来源、缺口和静态回填限制 |
| `data.point_in_time_integrity` | 数据在当时何时可见，是否存在未来信息或修订泄漏？ | 任何选择、成员、规则、基本面或修订数据参与因子/Trial | visibility timestamp、vintage、修订规则、成员时点和因果对齐证据 |
| `data.permission_and_use` | 当前账户和数据许可是否允许研究、保存、回放或实盘使用？ | 外部/用户数据源或实盘流参与研究 | entitlement、许可范围、保存期限和允许用途；有数据不等于有权使用 |

小类数量不是永久清单。Research Agent 若发现新的、可复用且会改变研究决定的数据
问题，可以提出候选；只有后继 Graph 版本经维护审计后才能加入目录。

## 5. 通用 Report Methods

Graph 只组合以下通用方法，不为每个因子创造新方法。每个具体
`report_requirement_id` 必须绑定上表中一个真实小类。

| Method ID | 允许的内容 | 通用作用 |
|---|---|---|
| `explain` | sentence, list, math | 解释机制、假设、动作和限制 |
| `inventory` | list, table | 逐项列出范围、对象、义务或数据 |
| `compare` | table, figure, list | 比较版本、参数、样本或替代解释 |
| `present_result` | table, figure, sentence | 展示经引用约束的统计/回测结果 |
| `adjudicate` | list, table, sentence | 逐项说明 Claim、义务和 Evidence 状态变化 |
| `explain_transition` | sentence, list, table | 说明为何选择一条边及未选路径 |
| `explain_gap` | list, table | 说明缺口、影响范围和修复路径 |
| `explain_closure` | list, table, sentence | 说明停止搜索、未知项和允许用途 |

Report Item 必含 `report_requirement_id`、`subject_ref`、内容块和 canonical
bindings。要求 `per_subject` 时，CLI 对 Graph 推导的 subject 集合逐项核对。

## 6. 逐节点规划

所有节点共同要求：进入节点时用 `inventory` 逐条报告适用小类、覆盖它的本地
义务、证据资格和未满足项。缓存命中可以是一条简短 Item，但仍保留展开引用。

| v8 节点 | Entry Requirement 小类 | 节点内必须完成的 Report Requirements |
|---|---|---|
| `hypothesis_preregistration` | `decision_scope.mechanism_falsifiability`; `decision_scope.decision_boundary`; `decision_scope.candidate_scope`; `trial_validity.stopping_rule` | `node.hypothesis.mechanism` (`explain`); `node.hypothesis.scope` (`inventory`); `node.hypothesis.initial_obligations` (`inventory`, per obligation); `node.hypothesis.rejection_and_stop` (`inventory`) |
| `capability_resolution` | `capability_governance.binding_suitability`; `capability_governance.product_support` | `node.capability.required` (`inventory`, per capability); `node.capability.binding` (`inventory`, per binding); `node.capability.unsatisfied` (`explain_gap`, per gap) |
| `data_contract` | 按当前 research scope/TrialPlan 触发上述具体 `data.*` 小类；至少包含 `data.product_source_availability`, `data.trial_window_coverage`, `data.point_in_time_integrity` 的适用性检查 | `node.data.inventory` (`inventory`, products/contracts/frequency/fields); `node.data.provenance` (`inventory`, per source/field); `node.data.history` (`inventory`, coverage/gaps); `node.data.trial_fitness` (`adjudicate`, per data obligation) |
| `factor_semantics` | `factor_semantics.economic_mechanism`; `factor_semantics.expression_validity`; `factor_semantics.causal_timing`; `factor_semantics.expression_parameterization`; conditional `factor_semantics.derived_comparability`; conditional `factor_semantics.conditional_factor_role` | `node.factor.original_expression` (`explain`, LaTeX + meaning); `node.factor.columns_and_params` (`inventory`); `node.factor.timing` (`explain`); `node.factor.revisions` (`compare`, per derived/revised family); `node.factor.semantic_obligations` (`adjudicate`, per obligation) |
| `validation_design` | `trial_validity.discharge_alignment`; `trial_validity.sample_partition`; `trial_validity.holdout_separation`; `trial_validity.multiplicity_ledger`; `trial_validity.transportability_design`; `trial_validity.stopping_rule` | `node.validation.obligation_trial_map` (`inventory`, per obligation); `node.validation.sample_plan` (`inventory`); `node.validation.holdout` (`explain`); `node.validation.trial_ledger` (`inventory`); `node.validation.stop_conditions` (`inventory`) |
| `cheap_factor_diagnostics` | `statistical_validity.cross_sectional_predictiveness`; `statistical_validity.quantile_monotonicity`; `evidence_integrity.claim_scope` | `node.cheap.specification` (`inventory`); `node.cheap.ic_results` (`present_result`, table); `node.cheap.monotonicity` (`present_result`, table/figure); `node.cheap.evidence_effect` (`adjudicate`, per affected claim/obligation) |
| `statistical_robustness` | `statistical_validity.uncertainty`; `statistical_validity.selection_bias`; `statistical_validity.robustness_preconditions`; `evidence_integrity.claim_scope` | `node.robustness.preconditions` (`inventory`, per method); `node.robustness.results` (`present_result`, per method); `node.robustness.selection_adjustment` (`present_result`); `node.robustness.evidence_effect` (`adjudicate`, per affected claim/obligation) |
| `authoritative_backtest` | `execution_accounting.signal_schedule`; `execution_accounting.session_boundary`; `execution_accounting.accounting_fidelity`; conditional `execution_accounting.cost_capacity`; `evidence_integrity.backend_assurance` | `node.backtest.runspec` (`inventory`); `node.backtest.signal_and_session` (`explain`); `node.backtest.accounting` (`inventory`); `node.backtest.backend_assurance` (`inventory`); `node.backtest.submission` (`inventory`, Job/Run refs) |
| `job_evidence_ready` | `evidence_integrity.job_terminal_integrity`; `evidence_integrity.artifact_completeness`; `evidence_integrity.backend_assurance` | `node.job.terminal_attempt` (`inventory`); `node.job.artifacts` (`inventory`, per artifact/ref); `node.job.omissions` (`explain_gap`, per missing artifact); `node.job.downstream_eligibility` (`adjudicate`) |
| `result_audit` | `evidence_integrity.claim_scope`; `evidence_integrity.conflict_resolution`; `evidence_integrity.evidence_qualification`; `research_decision.next_trial_value` | `node.audit.claims` (`adjudicate`, per claim); `node.audit.obligation_deltas` (`adjudicate`, per obligation); `node.audit.evidence_qualification` (`inventory`, per affected evidence/claim); `node.audit.conflicts` (`compare`); `node.audit.next_trial` (`adjudicate`) |
| `research_decision` | `research_decision.decision_disposition`; `research_decision.next_trial_value`; conditional `research_decision.search_exhaustion`; `research_decision.bounded_unknown`; `decision_scope.permitted_use` | `node.decision.disposition` (`adjudicate`); `node.decision.support_and_limits` (`inventory`, per claim); `node.decision.open_unknowns` (`inventory`, per obligation); `node.decision.search_exhaustion` (`explain_closure`); `node.decision.permitted_use` (`explain_closure`) |
| `capability_gap` | `capability_governance.gap_impact`; `capability_governance.binding_suitability`; `research_decision.next_trial_value` | `node.gap.exact_gap` (`explain_gap`, per capability); `node.gap.affected_scope` (`inventory`); `node.gap.attempted_bindings` (`inventory`); `node.gap.remediation_routes` (`compare`) |
| `skill_candidate_review` | `capability_governance.skill_fit_and_safety`; `capability_governance.gap_impact`; `capability_governance.rollout_and_rollback` | `node.skill.required_semantics` (`inventory`); `node.skill.candidate_fit` (`compare`); `node.skill.audit` (`adjudicate`); `node.skill.authorization` (`inventory`); `node.skill.validation` (`present_result`) |
| `code_improvement_required` | `capability_governance.backend_change`; `evidence_integrity.backend_assurance`; `capability_governance.rollout_and_rollback` | `node.code.anomaly_or_gap` (`explain_gap`); `node.code.authorized_scope` (`inventory`); `node.code.change_and_tests` (`inventory`); `node.code.independent_review` (`adjudicate`); `node.code.rollout_rollback` (`inventory`) |
| `factor_improvement_required` | `factor_semantics.economic_mechanism`; `factor_semantics.expression_validity`; `factor_semantics.derived_comparability`; `trial_validity.multiplicity_ledger`; `evidence_integrity.claim_scope` | `node.improvement.rationale` (`explain`); `node.improvement.old_new_expression` (`compare`, LaTeX); `node.improvement.version_identity` (`inventory`); `node.improvement.comparison_obligations` (`adjudicate`, per obligation); `node.improvement.ledger_effect` (`inventory`) |

## 7. 逐边规划

每条显式边共同要求 `edge.<edge-id>.decision`，使用 `explain_transition`，绑定表中
小类，并逐项引用实际 Evidence、TrialPlan、义务/Claim delta。下表的“必报内容”
是 common transition item 之外的边特有要求。

| v8 边 | 绑定小类 | 必报内容 |
|---|---|---|
| `any_node__capability_gap` | `capability_governance.gap_impact` | 原目标节点、精确缺失能力、受影响事务、未受影响 Job/分支 |
| `hypothesis__capability_resolution` | `decision_scope.decision_boundary` | 已冻结假设、范围、拒绝/停止条件、初始义务清单 |
| `capability_resolution__data_contract` | `capability_governance.binding_suitability` | 每项当前节点能力已选实现及授权状态 |
| `capability_resolution__capability_gap` | `capability_governance.binding_suitability` | 缺失能力、尝试过的绑定及不能继续的原因 |
| `data_contract__factor_semantics` | `data.trial_window_coverage` | 可用数据范围、仍有边界的字段/历史缺口、为何足以进入语义检查 |
| `data_contract__capability_gap` | `data.product_source_availability` | 不可用的产品/字段/频率/时间/来源逐项列表 |
| `factor_semantics__validation_design` | `factor_semantics.economic_mechanism` | 语义义务处置、因子版本、允许设计试验的范围 |
| `factor_semantics__factor_improvement` | `factor_semantics.derived_comparability` | 接受的修改裁决、原式/新式差异、必须保留的比较义务 |
| `validation_design__cheap_diagnostics` | `trial_validity.discharge_alignment` | 冻结 TrialPlan、义务到 trial 映射、样本/holdout/ledger hash |
| `validation_design__factor_improvement` | `factor_semantics.expression_validity` | 迟发现语义义务为何使当前 TrialPlan 无效及需修改内容 |
| `cheap_diagnostics__backtest` | `statistical_validity.cross_sectional_predictiveness` | 便宜诊断哪些证据支持付出回测成本、哪些未知仍保留 |
| `cheap_diagnostics__result_audit` | `evidence_integrity.claim_scope` | 为何无需/不得进入权威回测，以及当前诊断可支持的有限主张 |
| `backtest__job_evidence_ready` | `evidence_integrity.job_terminal_integrity` | RunSpec/JobAttempt 身份、终态和结果 artifact refs |
| `job_evidence_ready__statistical_robustness` | `statistical_validity.robustness_preconditions` | 哪些统计方法前提已满足及采用哪些事实输入 |
| `job_evidence_ready__capability_gap` | `capability_governance.gap_impact` | 缺失下游方法、已保留 Job 证据和恢复目标节点 |
| `statistical_robustness__result_audit` | `statistical_validity.uncertainty` | 预声明方法、结果表、选择调整和仍不支持的主张 |
| `result_audit__factor_improvement` | `research_decision.next_trial_value` | 被证伪/削弱的机制、新可证伪修改、预算与 holdout 状态 |
| `result_audit__validation_design` | `research_decision.next_trial_value` | 为什么新增 Trial 有信息价值、哪些义务驱动它、旧证据如何保留 |
| `result_audit__research_decision` | `research_decision.decision_disposition` | 为什么不再需要新的当前 Trial、可作出的有限决定 |
| `research_decision__cycle_event` | `research_decision.decision_disposition` | 每条 Claim/义务 delta、决定理由及是否重新开启搜索 |
| `factor_improvement__hypothesis` | `factor_semantics.derived_comparability` | 新因子家族/版本、与父版本关系、旧 Job 适用范围、ledger/holdout 继承 |
| `capability_gap__capability_resolution` | `capability_governance.binding_suitability` | 新可用能力或授权、验证证据和要恢复的目标 |
| `capability_gap__data_contract` | `data.product_source_availability` | 新增数据源/字段的精确范围、provenance 和仍未覆盖部分 |
| `capability_gap__job_evidence_ready` | `evidence_integrity.artifact_completeness` | 已恢复的 Job/artifact、完整性验证和下游可用性 |
| `capability_gap__blocked_closure` | `research_decision.bounded_unknown` | 三次阻塞审计、无法修复原因、受限结论和重新开启条件 |
| `capability_gap__skill_review` | `capability_governance.skill_fit_and_safety` | 所需语义能力、为什么既有实现不足、候选搜索边界 |
| `capability_gap__code_improvement` | `capability_governance.backend_change` | 后端缺口、授权范围、受影响分支、未受影响 Job 继续规则 |
| `skill_review__capability_resolution` | `capability_governance.skill_fit_and_safety` | grill/人工授权、验证结果、允许执行范围和撤销条件 |
| `code_improvement__capability_resolution` | `capability_governance.rollout_and_rollback` | 修复版本、测试/独立 review、Backend Assurance Gate、rollback target |

## 8. 系统派生边与 v8 结构缺口

以下不是 v8 的第 30 条人工边，而是 continuation 协议运行时派生的系统自环：

`__graph_continuation_reentry__`: current node @ source graph -> same node @ target graph

它必须逐项报告：累计 Change Manifest、小类增删改、`other` 义务重分类、Entry
Requirement coverage、义务重开/修订/新建、Evidence 资格变化、缺失 Report
Requirements 和返回同一节点后的 gate 状态。UI 使用 Graph 升级边样式。

真实 v8 还有一个必须在后继版本补足的结构缺口：测试节点 entry gate 被实质义务
阻塞时，v8 没有统一的“准备下一 Trial 后返回原目标节点”协议。不得滥用
`any_node__capability_gap`。后继版本应在 Node Re-entry Gate 的 resolution metadata
中声明：

1. 记录被阻塞 target node；
2. 路由到 `validation_design` 合成下一 TrialPlan；
3. 无有价值 Trial 时路由 `research_decision` 做 bounded closure；
4. Trial 可行时回到原 target node 重新执行 entry requirements；
5. 每一段使用上表对应的 node/edge Report Requirements。

## 9. Token、数据库与兼容约束

- `context/next` 只返回当前 node/edge 的 requirement IDs、中文短描述、subject
  refs、已命中 Item hashes 和缺失集合，不返回本目录或完整历史。
- 普通命中由确定性代码检查；只有义务语义匹配、重开/新建和分析正文调用 Agent。
- Report Item 正文只存本地 journal；服务器 trace 只保留 requirement ID、subject
  ref、bindings 与 content hash 的紧凑投影。
- 不新增报告表、报告义务表或 coverage 表；节点/边 requirement 来自 immutable
  Graph，实际 Items 来自本地 journal，coverage 可确定性派生并缓存于本地索引。
- 新 Graph 使用现有 sentence/list/table/figure 原语时不要求 FTClient 代码更新；
  新原语必须在 activation validation 阶段提前暴露为 capability gap。

## 10. v8 一次性迁移验收

1. 15 个节点和 29 条显式边均有至少一个绑定真实小类的 report requirement；
2. continuation 系统自环有独立逐项升级审计；
3. v8 旧报告只从已有事实重建，无法证明的项显示历史迁移缺口；
4. UI 的 node、ordinary edge、Graph-upgrade edge 三种锚点样式可视觉区分；
5. 点击版本树节点/边能滚动到同一 anchor，反向点击报告项也能定位图；
6. 每项显示中文 alias，详情 Chip 不以 UUID 为可见标题；
7. CLI 对遗漏 ID、subject 或 binding 返回逐条错误；
8. 无变化的覆盖检查零 Agent 调用、零服务器额外数据库写入；
9. MaxA 的同一 SgCCS Work Package 完成一次 v8 历史迁移，不制造第二个研究；
10. 迁移前后旧 Evidence、Job、Trial ledger、factor-family version 和原始 hash 不变。

## 11. 哪些内容属于 Graph Definition

### 必须随不可变 Graph 一起发布、hash 和审计

1. Graph 身份：`graph_id`, `version`, `parent_version`, schema、provenance；
2. `change_manifest`：相对 parent 的真实结构/语义变化和 re-entry 影响；
3. `requirement_catalog`：大类和小类的版本化中文描述、选择条件、证据要求、反例；
4. `report_method_descriptors`：通用报告方法的语义描述和 descriptor hash；
5. `report_requirements`：须报告内容 ID、绑定的小类、subject selector、bindings 和方法；
6. nodes：节点语义、entry requirement refs、entry report refs、node-action report refs、能力 refs；
7. edges：source/target、guard、evidence facts、edge report refs、风险和 server action；
8. system transition policies：continuation re-entry 和 node re-entry resolution 的派生边规则；
9. research-cycle/maintenance operations 与 review policy；
10. capability descriptions，不含具体 Skill 名称、路径或 provider identity。

以上必须共同进入一个 content hash。节点或边引用不存在、版本不一致或未绑定真实
小类的 report requirement 时，Graph 发布即失败，不能等 Agent 运行后才发现。

### 不属于 Graph Definition

- Research Agent/Server Maintenance Skill 的身份、正文、下载来源或运行时路径；
- 具体分支的 Verification Obligations、Claims、Evidence、TrialPlans 和 Jobs；
- Agent 写出的 Report Items 和 Markdown/PDF；
- FTClient 的颜色、间距、字体、动画与懒加载缓存；
- token 用量、运行队列、Profile、账户和数据源凭据；
- 客户端对 sentence/list/table/figure 的 renderer 实现。

Graph 只引用这些运行时对象的类型/语义，不把实例或 UI 实现塞入版本定义。

## 12. 最小代码重构建议

### 当前问题

- canonical `validate_graph` 位于 CLI-Anything harness，服务器反向导入它；
- schema v1 只严格校验 nodes、edges、capabilities、operations 和 review policy；
- builder 分散在 draft nodes/edges/cycle 模块，没有 Requirement/Report/Manifest owner；
- branch `context/next` 只投影 capabilities、edges 和 obligations，不认识 entry/report refs；
- report publisher 在 transition 之后才校验可选 narrative，无法形成 Graph 报告门。

### 目标结构

保持数据库只有一行不可变 `graph_json`，但把代码整理为一个共享、provider-neutral
的 Graph Definition package：

```text
tools/cli/research_graph_definition/
  identity.py       # canonical bytes, content hash, lineage
  requirements.py   # categories and Entry Requirement validation/selectors
  reporting.py      # methods, requirements, subject/binding contracts
  topology.py       # node, edge and system-transition validation
  governance.py     # change manifest, operations and review policy
  definition.py     # GraphDefinition v2 composition and cross-ref validation
```

Server、public FactorTester CLI 和 CLI-Anything harness 都依赖该共享协议包；服务器
不再从 harness 私有 core 反向导入。实际 Graph builder/维护材料仍由服务器维护，
最终发布一个完整 `graph_json`。

## Grill 179.1 — 第一类是否应从 `decision_scope` 收敛为 `research_intent`

**决定：接受。** 当前 `decision_scope` 同时放置机制、候选范围、允许用途和决策边界，
而末端 `research_decision` 又需要裁决结论边界与允许用途，容易让同一事项形成两套
义务。建议将第一类改为 `research_intent`，只保存研究开始或研究范围变化时必须
明确、且会约束后续 TrialPlan 的内容：

- `research_intent.question_and_mechanism`：要解释或预测什么，提出的机制是什么；
- `research_intent.falsifiability`：什么观察会削弱或证伪该机制；
- `research_intent.authorized_scope`：获准研究的因子/家族、产品、市场与允许探索的
  主因子、辅助因子和派生因子边界；
- `research_intent.decision_target`：研究最终要支持哪一种行动或有限判断；
- `research_intent.initial_stop_boundary`：在什么预算、数据或信息价值条件下停止当前
  搜索，但允许新证据或新 Graph 要求重新开启。

不在这里提前裁决“因子可用于什么”。最终允许用途只保留在
`research_decision.permitted_use`，由全程 Evidence 和未解决义务决定。这样初始类
描述研究为何开始和被授权研究什么，末端类描述证据最终允许说什么，二者不重复。

## Grill 179.2 — `factor_semantics` 只管理因子定义，不管理策略门控

**决定：按用户纠正后的身份语义接受。** 原问题把因子家族和因子实例混为一谈。修订后的
身份层如下：

- **因子家族（Factor Family）**：可版本化的表达式模板、可调参数 schema、允许的
  数据列/因子家族参数以及输出语义；
- **因子（Factor）**：某个因子家族在一组确定参数、列选择、频率及其他配置下实例
  化得到的具体信号；Job、Evidence 和统计结果必须引用这个实例身份及其家族版本；
- **派生因子家族**：以一个或多个因子家族的 raw expression 或数据表达式构造出的
  新模板；它不是多因子组合；
- **多因子组合**：只对多个已实例化因子及其信号进行估计、选择、赋权或组合，不对
  因子家族本身做组合。

在此身份区分下，建议保留 `factor_semantics` 大类，但把当前容易混淆的
`conditional_factor_role` 拆清：

- 表达式模板内部把一个或多个辅助因子家族的 raw expression 作为输入，经变换、
  门控、交互或加权生成新的模板，形成一个派生因子家族；该家族的某组确定参数才
  形成单个因子实例；登记在
  `factor_semantics.derived_construction`，并必须同时产生
  `factor_semantics.derived_comparability` 义务；
- `ColumnRef` 是否应提升为 `FactorParam` 属于
  `factor_semantics.expression_parameterization`；它允许新家族包含原家族作为一个参数
  特例，旧参数对应的 Job/Evidence 继续保留；
- 用另一个信号决定是否交易、何时发信号、是否跨 session、如何调仓，若没有成为
  因子表达式本身，则不是因子语义，而属于 `execution_accounting.strategy_conditioning`；
- 多因子组合的估计、权重和组合评价不塞进这一类，作为后续针对多个**因子实例**的
  能力和 Graph 路径；一个派生家族可以使用多个辅助家族表达式，但必须输出具有独立
  身份、LaTeX、家族版本和比较义务的新家族。

由此删除含混的 `factor_semantics.conditional_factor_role`，避免 Agent 把策略层条件
误写进 Factor DSL，也避免把含多个输入的派生因子家族错误标为多因子组合。

## Grill 179.3 — 从 `trial_validity` 收敛为可执行的 `trial_design`

**决定：接受。** 当前草案把 sample、holdout、transportability 和 stopping 并列，但
缺少“本次 Trial 改变什么、与什么比较”的核心。建议大类改名为 `trial_design`，
只管理 TrialPlan 在运行前必须明确的设计义务：

- `trial_design.obligation_alignment`：每个 Trial 回答哪些具体义务；不能只因为有
  指标可跑就创建 Trial；
- `trial_design.intervention_and_baseline`：本次改变的家族版本、因子实例、参数、
  数据、策略或市场范围是什么，和哪个冻结基线/对照比较；
- `trial_design.information_partition`：哪些数据可用于构造、选择和调参，哪些信息被
  保留作后续检验；不硬编码固定年份；
- `trial_design.latest_holdout`：默认把可得数据中最新且有未来借鉴意义的一段保留到
  最后，只有相关前置义务与停止条件满足后才能打开；实盘/仿真实盘/延迟流可作为更
  晚阶段的顺序证据，但必须标记可见性和用途；
- `trial_design.regime_and_instrument_coverage`：历史上其他时间范围、市场环境和标的
  用于跨环境/跨标的义务，不冒充最新 holdout；
- `trial_design.multiplicity_and_ledger`：参数、派生家族、辅助家族和重复尝试全部登记，
  防止选择性报告；
- `trial_design.stop_and_budget`：预先声明本 Trial 的停止条件、资源上限以及何时不再
  打开更多信息。

`transportability_design` 不再作为含混独立小类，而由
`regime_and_instrument_coverage` 表达；统计方法的前提、估计不确定性和选择偏差仍
留在后续 `statistical_validity`，避免 Trial 设计与结果统计重复。

### `trial_design` 与 `statistical_validity` 的关系

两者不是包含关系，也不应实现成两个互不相干的阶段。它们是一个 TrialPlan 的两个
正交 contract：

- `trial_design` 回答研究设计问题：要处理哪项义务，改变什么，与什么比较，使用或
  冻结哪些信息，覆盖哪些市场环境，何时停止；
- `statistical_validity` 回答推断问题：采用什么 estimand/统计量/不确定性方法，方法
  前提是否成立，多次选择如何影响解释，结果最多支持什么强度的主张。

每个可执行 TrialPlan 必须同时引用适用的 `trial_design.*` 与
`statistical_validity.*` requirement revisions。设计先确定问题、对照和信息边界，
随后选择与这些设计相匹配的统计方法；若统计方法前提无法满足，不得悄悄换问题，
而应修订 TrialPlan 或保留有边界的未知项。运行后的 EvidenceEnvelope 可以同时提出
两类具体义务的 delta，但任何一类通过都不能替代另一类。

## Grill 179.4 — 统计义务描述推断问题，不把具体工具当成固定流程

**决定：接受。** 建议把当前 `cross_sectional_predictiveness`、
`quantile_monotonicity` 等具体检验从稳定大类目录中下沉为按主张触发的 method/
capability binding；`statistical_validity` 的稳定小类改为：

- `statistical_validity.estimand_and_metric`：要估计的量是什么，指标为何能回答当前
  义务，方向、单位和聚合口径是什么；
- `statistical_validity.dependence_structure`：横截面、时间序列、合约和市场之间的
  相关结构是否被推断方法处理；
- `statistical_validity.uncertainty_and_effect_size`：不仅报告点估计，还报告不确定性、
  效应大小和可辨识范围；
- `statistical_validity.selection_and_multiplicity`：参数、家族、市场、时间段和指标的
  多次选择如何进入 ledger 并限制推断；
- `statistical_validity.method_assumptions`：所选方法的样本量、平稳性、分布、缺失和
  其他前提是否足够；
- `statistical_validity.sensitivity_and_falsification`：结论对合理替代口径是否稳定，
  是否执行了能够推翻当前解释的检查。

IC、Rank IC、分组单调性、Bootstrap Sharpe、Deflated Sharpe、置换检验等仍可以是
Requirement Catalog 中按需加载的候选证据方法和 capability 描述，但只有当前
Claim/Trial 需要时才进入局部上下文。Graph 不规定每个因子必须跑所有方法；它要求
Agent 说明为何选择、为何足够以及还有哪些推断义务未解决。

**用户补充：上述解释必须成为须报告条目。** Graph 在使用统计方法的节点/边至少
声明以下 Report Requirements，而不只由 Skill 软提示：

- `statistics.method_selection`：逐个方法报告为什么适合当前义务、estimand、样本与
  依赖结构，绑定 `statistical_validity.estimand_and_metric` 和
  `statistical_validity.method_assumptions`；
- `statistics.supported_claim_scope`：逐个结果报告能够支持的 Claim、效应方向/大小、
  不确定性及不能外推的范围，绑定
  `statistical_validity.uncertainty_and_effect_size`；
- `statistics.unresolved_obligations`：逐项列出仍未解决或因方法前提不足而只能保持
  bounded/unknown 的具体统计义务，并绑定相应的 `statistical_validity.*` 小类。

CLI 按 method/claim/obligation 的 `subject_ref` 确定性验证覆盖；缺失任一条时返回
具体 `missing_report_requirements`，不能把统计节点或相关边视为报告完整。

## Grill 179.5 — 区分交易策略与外生市场/会计规则

**决定：接受用户纠正后的拆分方案。** 原方案把研究者选择的交易策略
与外生市场规则/会计规则混在同一大类。修订为两个可分别触发、但在回测 Trial 中
相互引用的大类。

### `strategy_design`：研究者可以改变并需要控制变量的策略规则

- `strategy_design.signal_schedule`：`$F`、信号频率、计算时点、生效时点和可交易
  时点如何对应；
- `strategy_design.strategy_conditioning`：辅助信号只在策略层决定是否交易、仓位或
  再平衡时的具体规则；
- `strategy_design.position_and_rebalance`：信号如何映射为方向、仓位、调仓、退出和
  风险约束；
- `strategy_design.session_policy`：是否跳过收盘前时段、是否跨 session 保留信号或
  仓位等策略选择。

`end_session_skip` 属于 `strategy_design.session_policy`。交易所 session 日历只是该
策略的事实输入；启用或关闭 skip 是 Trial 的受控变量。比较时固定同一因子实例、
数据、成本、产品、样本和其他策略参数，只改变 session policy，并把尝试登记进
ledger，不能把默认值造成的效果归因于因子。

### `market_execution_accounting`：研究者不能任意改变的外生规则和执行事实

- `market_execution_accounting.session_calendar`：夜盘、交易日边界、节假日、开收盘
  和产品交易时段的 point-in-time 规则；
- `market_execution_accounting.contract_lifecycle`：期货合约上市、到期、交割、合约
  选择事实，以及主连/换月实现所依赖的规则；
- `market_execution_accounting.order_and_fill`：订单类型、撮合、成交约束、盘口/成交
  量限制、滑点和容量假设；
- `market_execution_accounting.cost_margin_and_settlement`：手续费、保证金、利息、
  现金和结算的 point-in-time 会计；
- `market_execution_accounting.backtest_live_consistency`：同一策略规则在历史、仿真
  实盘、延迟流和实盘中的执行与会计语义是否一致。

两类只在 Trial 需要把信号映射成交易结果时触发；纯表达式语义检查或便宜 IC 诊断
不必提前加载。某条市场规则/历史字段是否存在仍由 `data.*` 回答；其真实规则语义
及回测采用方式由 `market_execution_accounting.*` 回答；后端是否正确实现则由
`evidence_integrity.backend_assurance` 回答。

## Grill 179.6 — Evidence 资格与按异常升级的后端保证

**决定：接受，并采用严格异常触发规则。** `evidence_integrity` 不负责判断因子是否有效，而只判断某份结果是否有
资格参与后续义务/Claim 裁决。建议稳定小类为：

- `evidence_integrity.identity_and_lineage`：Evidence 是否绑定不可混淆的 Work
  Package、因子家族版本、因子实例配置、TrialPlan、RunSpec、数据版本和 Graph；
- `evidence_integrity.job_and_artifact_completeness`：JobAttempt 是否终态，约定的指标、
  表格、图表/序列和失败信息是否齐全，缺失项是否逐项标记；
- `evidence_integrity.backend_assurance`：执行后端、代码/构建版本、配置 hash 和已批准
  的 Backend Assurance receipt 是否匹配；
- `evidence_integrity.applicability_scope`：Evidence 实际覆盖的产品、时段、市场环境、
  频率、参数和策略范围，不能由结果自动外推；
- `evidence_integrity.conflict_and_anomaly`：与既有 Evidence 冲突、数量级异常、不可
  复现或实现疑点如何记录与处置。

正常路径只由确定性代码检查 identity/hash/receipt/artifact manifest，不启动 LLM 或
源码审查。只有出现明确 anomaly、receipt 不匹配、同 RunSpec 不可复现或结果违反
可检查不变量时，才打开 `backend_assurance` 审查：普通用户的 Agent 只能形成证据
资格缺口并请求服务器端审查；拥有后端源码权限的开发者 Agent 或 Server Agent 才能
调用专门 reviewer 审查/修正代码。既有未受影响 Job 继续运行和保留。

须报告条目至少逐份 Evidence 说明：身份与来源、完整/缺失 artifact、可支持范围、
资格裁决以及异常/冲突。源码、stdout 和完整 trace 只按引用懒加载，不进入普通正文
或 Agent packet。

### 何时允许怀疑 Evidence integrity

默认不怀疑。可信后端版本的 receipt、身份/hash 与 artifact manifest 确定性检查通过
后，Evidence 默认具备流程资格；Agent 不得因为 Sharpe/IC 较差、结论不合预期、
市场阶段不同或与旧研究方向相反而启动后端审查，这些属于正常研究证据或冲突义务。

只有至少出现一项可复核触发器时，Agent 才能提出 integrity anomaly：

1. identity/hash/schema 不一致，例如结果引用了错误的因子实例、RunSpec、数据版本或
   家族版本；
2. Job 非终态却产出“最终结果”，或约定 artifact/指标缺失、重复、损坏；
3. 结果违反确定性不变量，例如资产曲线与逐期收益无法对账、交易数/持仓/现金流关系
   不可能、全 NaN 却报告有效指标、单位或时间戳自相矛盾；
4. 完全相同的冻结 RunSpec 与输入 hash 在声明为确定性的后端上产生超出容差的不同
   结果；
5. backend/build/config receipt 缺失、不在批准范围或运行中发生未记录变化；
6. Evidence 声称的产品、时段、字段或样本覆盖与 artifact/provenance 可验证事实不符；
7. 一个独立、低成本的确定性复算或会计核对不能重现关键中间量。

Agent 提案必须给出 `expected_invariant`、`observed_violation`、相关 refs 和最小复现；
没有这些字段只记为普通研究疑问，不进入后端审查。确定性检查能判定的先由代码判定；
只有需要源码语义判断时才请求一个专门 reviewer，避免 token 浪费。

## Grill 179.7 — `research_decision` 不设“因子通过”，而裁决下一步与停止边界

**决定：接受。** `research_decision` 保留为稳定大类，但不设置统一 Sharpe/IC 阈值，也
不产生无范围的“有效/无效因子”结论。建议小类为：

- `research_decision.claim_disposition`：逐个 Claim 说明被支持、削弱、证伪、冲突或
  保持未知，并限定适用的家族版本、因子实例、产品、时段、环境和策略；
- `research_decision.obligation_portfolio`：逐项检查现有义务的状态，并要求 Agent 基于
  当前 Evidence、第一性原理与 Graph 当前目录寻找是否缺少决策相关的新义务；
- `research_decision.next_trial_information_value`：是否存在能够实质改变某项 Claim/
  义务状态、且成本与信息价值合理的可执行 TrialPlan；
- `research_decision.search_exhaustion`：记录本轮探索过的候选路径、未采用原因、Skill/
  Graph 版本和 search exhaustion checkpoint；
- `research_decision.bounded_closure`：没有新的有价值 Trial、达到预算/停止边界或存在
  当前无法解决的义务时，形成有边界的暂停/结束，而不是伪称全部义务清除；
- `research_decision.permitted_use`：当前证据最多允许研究、模拟、受限试用还是其他
  用途，以及明确禁止的外推。

研究范围的“完成”是 Work Package 范围上的可审计 closure：没有尚未处理且会改变
当前决定的义务，也无法提出新的有信息价值且可执行 Trial；未解决项被逐项限定，
并满足已声明预算/停止条件。它不是永久完成：Requirement/Skill/Graph 更新、新数据、
新市场环境或新的可行 Trial 可以从 checkpoint 重新开启。因子家族有多个实例时，
报告必须展示实例/覆盖矩阵，不能用一个好参数代表整个家族。

必须报告：每个 Claim 的裁决与边界、每项变化义务、下一 Trial 的信息价值判断、未选
路径、停止理由、bounded unknown 和 permitted use；这些都绑定真实义务小类和 refs。

## Grill 179.8 — Active Graph 只管理能力影响，治理实现交给 Server Agent

**用户纠正：角色边界本来如此，不应误判为需要移除节点。** 当前
`capability_governance` 同时描述研究能力缺口与服务器维护事务，但并不表示 Research
Agent 执行全部事务。建议义务目录仍在 Factor Research Active Graph 中缩为
`capability` 大类：

- `capability.required_semantics`：当前节点/Trial 实际需要什么行业/计算语义；
- `capability.available_binding`：是否存在已批准且版本匹配的本地/服务器实现；
- `capability.product_and_scope_support`：实现是否支持当前产品、频率、数据和用途；
- `capability.gap_impact`：缺口具体阻塞哪些义务/Trial，哪些分支和运行中 Job 不受
  影响；
- `capability.validation_receipt`：Server Agent 返回的实现、测试、审批、版本与撤销
  条件 receipt 是否满足研究需要。

Skill 搜索/安全审查、后端源码修改、独立代码 review、发布和 rollback 由 Server
Agent 按 Server Maintenance Skill 执行。Research Agent 只提交一个紧凑 capability
request，保持当前目标节点与恢复位置；Server Agent 完成后返回 receipt，Research
Graph 在下一个 checkpoint 确定性检查后恢复。普通用户看不到/不能修改后端源码。

v8 已有 `skill_candidate_review` 和 `code_improvement_required` 节点继续作为明确的
跨角色等待/协调节点，不是兼容性残留，也不需要删除。Graph 的 node/action contract
需要声明 `responsible_actor_role`、request/receipt schema、受影响分支、恢复目标和
checkpoint 条件：

1. Research Agent 到达后停止受影响 Trial/边，未受影响 Job 和研究任务继续；
2. Server Agent 认领 request，并按自己的 Skill/审批流程执行；
3. Research Agent 不轮询源码或加载维护过程，只等待轻量状态/heartbeat；
4. receipt 到达下一个 checkpoint 后，确定性代码验证版本、范围和测试状态；
5. 通过则恢复原目标节点，失败或超范围则保持等待/形成更新后的缺口。

研究报告逐项记录缺口影响、request ref、等待期间继续的事项、Server receipt 和恢复
决定；源码 diff、审批对话和完整测试日志留在服务器审计记录，按需引用。

**用户补充：Research Agent 必须在连续研究报告中解释维护结果。** Research Agent
可以并且应当根据已验证的 Server receipt 报告“服务器做了什么改变、补强了什么
能力、研究因此能够继续什么”，但须保留角色归属与证据边界。跨角色节点至少产生：

- `capability.maintenance_change_summary`：由 Server receipt 支持的修改摘要，明确
  实施者/版本，不把修改冒充为 Research Agent 行为；
- `capability.capability_delta`：新增、修复或扩大了哪些能力、产品/频率/数据范围；
- `capability.validation_and_limits`：通过了什么测试/审查、尚有哪些限制与撤销条件；
- `capability.research_impact`：哪些原义务/Trial 被解除阻塞、哪些 Evidence 仍可沿用、
  从哪个 checkpoint/目标节点恢复；
- `capability.remaining_gaps`：仍未解决的缺口及其对研究结论的限制。

Research Agent 负责把这些事实组织为中文研究叙事并解释研究影响；事实字段绑定 receipt
和 artifact refs。源码 diff、完整测试日志和审批对话默认懒加载，普通用户无源码权限
时也能读懂“功能增强了什么”，但不能访问受限实现细节。

**决定：按上述跨角色语义接受。**

## Grill 179.9 — Server Maintenance Task 的确定性交接表

**决定：接受最小持久化 contract。** Research Agent 在能力节点创建任务后只
保存 `task_id`；Server Agent 必须在统一的逻辑任务登记表中记录是否处理以及如何
处理，不能只在 Agent 对话里回复。建议每个 task 只保留一个当前状态行，至少包含：

- `task_id`, `task_type`, `status`, `request_hash`；
- 来源 `work_package_id`, `branch_id`, `checkpoint_id`, `requested_capability_ids`；
- `responsible_actor_role` 与实际认领的 provider-neutral `agent_id`；
- `result_json`, `result_hash`, `completed_at`；
- Server 审计 trace/ref（复用既有审计存储，不复制完整日志）。

`result_json` 使用版本化 schema，至少包含：

```json
{
  "disposition": "resolved|partially_resolved|rejected|failed",
  "change_summary_zh": [],
  "capability_deltas": [],
  "validation_receipt_refs": [],
  "remaining_gaps": [],
  "affected_scope": {},
  "resume": {
    "target_node": "...",
    "checkpoint_condition": "..."
  }
}
```

Research Agent 到 checkpoint 时按当前分支关联的 `task_id` **一次批量查询**，不扫描
全表、不读取服务器对话；未完成则继续等待但不阻塞无关任务，完成则校验
request/result hash 和 receipt refs，再生成上一节的逐条中文报告。

这里先定义逻辑 contract，不预设一定新增数据库表。实现前必须审计现有 Job/任务/
approval 存储：能在不污染 Job 语义的情况下复用则扩展；否则只新增一张
maintenance task registry，不再拆 request/result/event 多张表。状态迁移只写必要
次数，UI 按需读取，避免轮询造成数据库热路径压力。

## Grill 179.10 — `other` 只作可审计的临时分类，不自动升级规范

**决定：接受，并补充报告/UI/服务器收集要求。** 当 Research Agent 运用第一性原理发现会改变研究决定、但 Catalog 中
确实找不到合适大类时，可以在 `other` 下创建具体义务。该义务必须包含：自然语言
问题、为什么决策相关、预期证据、不能满足它的事实、影响的 Claim/Trial，以及已
检查过但不适用的现有类别。

约束如下：

1. `other` 义务可以阻塞具体 Trial 或限制结论，但不能冒充某个专门 Entry
   Requirement 的 coverage；
2. 它与普通具体义务一样进入本地 journal、报告和检索，供后续 Agent 复用；
3. 单次出现或出现次数多都不能自动修改 Graph；复用频率只是提案证据，不是行业
   规范；
4. 只有问题具有跨研究复用价值、会改变决策，并有行业/统计语义或多次独立研究事实
   支持时，Research Agent 才创建 Server Maintenance Task，提出新增/修改 Catalog
   大类或小类；
5. Server Agent 按 Graph 维护 Skill、grill-with-docs 与人工审计处理；批准后只进入
   新 Graph 版本；
6. 研究分支仅在用户主动 continuation 时，才在系统升级自环中把相关 `other` 义务
   重新分类，并保留旧分类和审计链。

因此 Agent 始终可以提出新问题，但不能自行把临时经验提升为全局规则，也不会因为
当前 Catalog 不完美而停止正常研究。

每项义务的正文 Report Item 和 UI Chip 必须显示中文 alias、当前大类、小类与
requirement revision；`other` 还显示未分类原因、候选大类/小类、是否已提交服务器、
maintenance `task_id` 和处理状态。Chip 首屏不显示 UUID；点击后懒加载问题全文、
预期/不足证据、Claim/Trial 影响、分类历史和审计 refs。

## Grill 179.11 — 复用 Maintenance Task 收集 Catalog 提案

**决定：接受。** Research Agent 可以自行判断一个 `other` 或现有分类义务是否值得向
Server Agent 提交，并建议：复用哪个大类、新增/修改哪个小类、中文描述、选择条件、
预期证据、反例、适用节点/边和须报告条目。提交不等于批准。

服务器不收集所有本地临时义务，只收集 Agent 明确提交的 proposal。复用 Grill
179.9 的统一 maintenance task registry：

- `task_type = catalog_change_proposal`；
- request JSON 存 proposal、来源 obligation ref、Graph version、证据 refs、建议分类；
- `request_hash`/canonical proposal fingerprint 用于精确幂等去重；
- Server Agent 的 `result_json` 返回接受、修订、拒绝或需更多证据，以及目标 Graph
  proposal/version refs；
- 多个语义相似但 hash 不同的提案由 Server Agent 审查时归并，不在数据库热路径调用
  LLM 做模糊匹配。

数据库成本保持在冷路径：每次提交一次 INSERT、状态实质变化时 UPDATE/审计一次；
Research Agent 只按已知 task IDs 批量查询，Server Agent 只分页查询带索引的 pending
任务。建议索引 `(task_type, status, created_at)` 和唯一 `request_hash`；UI 从本地
journal 展示义务，只在展开服务器状态或刷新时批量读取任务结果，不逐 Chip 查询。

## Grill 179.12 — 每个 Entry Gate 必须审查相关 `other` 义务

**决定：接受，并继续定义未满足项的处置协议。** Graph 声明的 Entry Requirements 不是 entry gate 的唯一输入。每次进入
或重新进入节点时，还必须检查当前分支中与以下任一对象显式相关的 open/reopened/
bounded `other` 义务：目标节点、候选边、当前 Claim、拟执行 TrialPlan、因子家族/
实例、产品/市场/时间范围。

为了节省 token，流程分两层：

1. 本地确定性索引按上述 refs、状态和 scope hash 取回 `other` 候选，只给 Agent 中文
   alias、一句话问题、状态和关键 refs；不加载全部 journal；
2. Research Agent 逐项判断该义务是否会实质影响当前 entry：需要先解决、可带着明确
   边界继续，还是与本节点无关，并报告理由。

相关且会改变 Trial/Claim 的 `other` 义务未得到解决或有边界处置时，entry gate 不得
放行；不相关项不阻塞，但必须留下本次 applicability decision，输入 hash 未变化时
可缓存复用。`other` 不能满足专门 Entry Requirement；反过来，专门要求满足也不能
自动忽略相关 `other`。

Catalog proposal 的服务器审批状态与本地研究处置解耦：Research Agent 可以在
`other` 分类下设计 Trial、收集 Evidence 和处置义务，不必等 Server Agent 批准新
类别；是否提交/批准分类本身不阻塞研究，真正有实质影响的是该义务的内容。

报告/UI 在 entrypoint 的逐项检查中展示：义务 alias/分类、为何相关或无关、当前
状态、所需处置、是否阻塞和相应 Evidence/Trial refs。Graph continuation 时还须检查
它是否应重分类到新 Catalog。

## Grill 179.13 — `other` 未满足时的 Graph 派生处置路径

**决定：接受，并按用户纠正明确 Research Agent 的路由责任与恢复状态。** Entry Gate 发现义务未满足时，仍由 Active Graph 决定允许的临时处置
路径。它不是新的永久业务节点，而是附属于 `target_node` 的 resolution episode，
保存目标节点、待处理义务和返回条件。已有小类可直接读取 Catalog 中的 evidence/
resolver contract，例如 `data.*` 通过批准的 CLI 检查 availability、coverage 或
point-in-time 事实。

`other` 没有预定义 resolver 时，Research Agent 不是向 Server 请求“告诉我能不能
做”，而是先在本地 entrypoint 形成结构化 `provisional_resolution_decision`：

- 义务问题和决策影响；
- 什么 Evidence 才能缩小/解除/证伪它；
- 判定标准与不能算满足的事实；
- 所需能力的 provider-neutral 描述；
- 候选验证动作、成本和停止条件。

Research Agent 结合 Capability Registry 自行判断属于以下哪条固定路由；Graph
验证选择和必需证据，Agent 不能临时发明边：

1. **已有批准能力可满足**：绑定 CLI/本地工具/服务器能力，执行最小验证；完成后回到
   原 `target_node` 的 Entry Gate；
2. **需要新的 Trial**：进入 `validation_design`，生成与义务对齐的 TrialPlan，完成
   证据链后返回原 Entry Gate；
3. **CLI 能力缺失或代码缺陷**：Research Agent 报告具体缺口并进入
   `capability_gap`，生成 Maintenance Task；Server Agent
   先判断现有 Skill/能力能否满足，确实缺失才进入 `skill_candidate_review` 或
   `code_improvement_required`；
4. **其他/当前没有可行验证方法**：Research Agent 报告原因，将义务保持为
   bounded unknown，并暂停进入该目标节点；未受影响研究可继续。之后若无其他有价值
   Trial，再由 `research_decision` 决定有边界结束，不能伪装满足。

验证动作无论成功、失败或无法执行，都必须同时产生：

- 本地中文 Report Items：`other.resolution_plan`、`other.verification_action`、
  `other.verification_result`，若有缺口再加 `other.capability_gap_handoff`，恢复时加
  `other.resume_decision`；
- Active Graph/server 的紧凑 transition delta：obligation ref/hash、目标节点、所选
  route、执行/Trial/task refs、Evidence refs/hash、状态 delta 和返回条件；不上传完整
  本地正文或因子源码；
- 若进入维护路径，Maintenance Task 的 request/result JSON 与 Server receipt。

Research Agent 不能仅用自然语言声称义务满足；Graph 只接受绑定实际 Evidence 与
判定标准的 disposition。Server 收到的是可审计的紧凑事实投影，不是整份研究报告，
因此不会让正常 entrypoint 产生大体积数据库写入。

### Entry Resolution 恢复状态

任何 entrypoint 绕行前必须把紧凑的 `EntryResolutionFrame` 写入当前 branch
checkpoint，而不是依赖 Agent 上下文：

```json
{
  "entry_attempt_id": "...",
  "graph_ref": "factor-research@...#hash",
  "target_node": "...",
  "origin_checkpoint_ref": "...",
  "blocking_obligation_refs": [],
  "entry_requirement_refs": [],
  "selected_route": "existing_capability|trial|capability_gap|paused_other",
  "dispatch_refs": [],
  "completion_refs": [],
  "status": "resolving|waiting|resumable|resolved|abandoned",
  "resume_guard_hash": "..."
}
```

若绕行目标自身又被 entry gate 阻塞，则在同一 checkpoint 的
`entry_resolution_stack` 上压入下一帧；只保存 IDs/hashes/状态，不复制报告或
Evidence。内层满足后按栈返回，最终重新进入原 `target_node` 并重新执行 gate；
Graph/requirement/obligation 输入 hash 变化时旧 resume guard 失效，必须重算。

每次 push、route、wait、resume、resolve/abandon 都产生边/entry Report Item 和紧凑
server transition delta。这样 UI 能显示“当前为何离开、正在处理什么、将返回哪里”，
Research Agent 换模型、换会话或交接后也能从 checkpoint 无缝恢复。

## Grill 179.14 — 大类收敛及两个易混边界

**用户纠正：市场/会计与数据边界接受；Trial/Decision 部分撤回修订。** 原提案把
Graph 的步骤节点与真实义务大类混在一起。原列出的正式大类为
`research_intent`、`data`、`factor_semantics`、`trial_design`、
`statistical_validity`、`strategy_design`、`market_execution_accounting`、
`evidence_integrity`、`research_decision`、`capability`；`other` 是临时分类。

### `trial_design` 与 `research_decision`

- `trial_design` 是**运行前、面向单个或一组具体 Trial 的前瞻 contract**：把某些
  义务转换为可执行比较，冻结干预/基线、因子实例、数据分区、统计计划、ledger、
  成本与停止条件；
- `research_decision` 是**得到 Evidence 后、面向整个 Work Package 的组合裁决**：
  更新 Claims/义务，判断下一项 Trial 是否还有信息价值，或形成 bounded closure 和
  permitted use。

两者不包含彼此，而是反馈环：`research_decision` 若认为下一项 Trial 有价值，就回到
`trial_design`；Trial 完成并审计 Evidence 后再回到 `research_decision`。不能在
`trial_design` 中预判最终结论，也不能在 `research_decision` 中临时拼一个未冻结的
Trial。

### `market_execution_accounting` 与 `data`

`market_execution_accounting` 不属于 `data` 小类。两者分别回答：

- `data`：事实有没有、来自哪里、何时可见、覆盖多久、是否允许使用。例如是否有
  逐日保证金率/手续费历史、真实交易时段、L1/L2、合约规则版本；
- `market_execution_accounting`：这些事实的行业语义是什么，以及回测/交易如何正确
  应用。例如保证金占用与结算怎样计算、手续费按手/金额/开平今怎样处理、session
  如何映射交易日、换月和撮合/滑点模型如何作用于订单与现金流。

同一研究问题可以生成相互引用的两项义务：`data.field_history_coverage` 证明历史费率
存在并 point-in-time 可得；`market_execution_accounting.cost_margin_and_settlement`
证明后端按照当时规则正确计提。前者满足不能推出后者满足，反之亦然。这样既不把
市场规则降格成“有一列数据”，也不在会计类别重复保存数据库存。

### 修订：义务类别不能按流程阶段命名

真实 Verification Obligation 必须是一个未解决时会改变 Trial 可解释性、Evidence
资格、Claim 或行动决定的问题；“现在到了哪个节点”或“下一步要作研究决定”不是
义务。

因此：

1. 删除 `research_decision` **义务大类**。`research_decision` 仍是 Graph 节点，
   负责读取全部现有义务、Claims 和 Evidence，决定下一 Trial 或 bounded closure，
   并完成 `claim_disposition`、`search_exhaustion`、`bounded_closure`、
   `permitted_use` 等决定/报告输出；这些输出不伪装成新的元义务类别。
2. 将 `trial_design` 大类改为 `identification_and_comparison`。它不表示“正在设计
   Trial”这一阶段，而是登记 Trial 是否能识别所要判断机制的真实问题。

`identification_and_comparison` 的小类与具体义务例子：

- `controlled_contrast`：**比较是否只改变了研究变量？** 例如检验
  `end_session_skip` 时，固定同一因子实例、产品、样本、成本和其他策略参数，只改变
  session policy；
- `baseline_relevance`：**对照是否能回答问题？** 例如成交量增强家族与父家族的对应
  参数实例比较，而不是和另一个最佳因子比较；
- `information_separation`：**构造、选择、调参信息是否和最终检验分开？** 例如最新
  holdout 在最终义务前未被查看；
- `regime_and_instrument_contrast`：**跨时间环境/标的的设计能否区分稳健性与特定环境
  效应？** 历史其他环境不冒充最新 holdout；
- `sequential_holdout_integrity`：**逐步滚动样本内外时是否保持各阶段的信息边界？**
  例如先做 2024→2025，再做 2025→2026，后一步信息不能倒流影响前一步选择；
- `trial_stop_integrity`：**停止/继续是否依照预声明规则，而不是看到结果后选择性
  停止？**

“生成 TrialPlan”和“下一项 Trial 是否值得做”是节点动作/边 guard。它们由上述
具体义务及 `data`、`statistical_validity` 等大类中的未解决问题驱动，不再单独创建
与流程节点同名的义务。

### 用户追问后的二次修订：`trial_design_validity`

`identification_and_comparison` 命名覆盖不全，也不便 Research Agent 理解。建议改为
行业语义更直接的 `trial_design_validity`（试验设计有效性）：它登记“一个 Trial 或
一组递进 Trial 的比较设计与信息生成方式，是否足以回答所绑定的研究义务”。它不是
`validation_design` 节点的别名；该节点负责创建/修订 TrialPlan，而这一大类中的
具体义务可以在任何 entrypoint 被发现、重开或由 Evidence 改变。

小类 contract 必须向 Research Agent 提供中文名称、问题、适用 scope、何时选择、
所需证据、不能算满足的事实、报告要求和 resolver。首版建议：

| 小类 ID | Agent 必须回答的真实问题 | 默认 subject scope |
|---|---|---|
| `trial_design_validity.target_contrast` | 本 Trial 究竟要比较什么、改变什么，结果对应哪项义务与目标差异？ | Trial |
| `trial_design_validity.baseline_relevance` | 基线/父家族/对照实例是否与问题匹配，而不是事后选择的有利对照？ | Trial |
| `trial_design_validity.controlled_variable_isolation` | 除目标变量外，因子实例、参数、数据、策略、成本、产品和计算口径是否固定或明确建模？ | Trial |
| `trial_design_validity.population_and_universe` | 产品、合约、时间、成员/存续样本和排除规则是否代表 Claim 的目标范围？ | Trial 或 Trial family |
| `trial_design_validity.information_partition` | 构造、训练、选择、调参与评估使用了哪些信息，是否把应保留信息提前暴露？ | Research cycle / Trial family |
| `trial_design_validity.sequential_holdout` | 递进样本内外或 walk-forward 是否只向前使用信息；最新 holdout 是否最后才打开，后期信息是否倒流？ | Research cycle / Trial family |
| `trial_design_validity.regime_control_and_coverage` | 市场背景是被固定、配对/分层/阻断，还是作为待比较维度；是否覆盖 Claim 所需环境且不混淆目标变量？ | Trial family / Work Package |
| `trial_design_validity.instrument_control_and_coverage` | 不同标的差异是控制变量、分层因素还是外推检验；选择标的是否造成偏差？ | Trial family / Work Package |
| `trial_design_validity.temporal_overlap_and_gap` | 信号标签、持有期和相邻窗口是否重叠，是否需要 purge/gap/embargo 防止信息污染？ | Trial |
| `trial_design_validity.replication_structure` | 哪些时间块、标的或市场可作为独立/相关重复单元，结果是否依赖单一事件或单一路径？ | Trial 或 Trial family |
| `trial_design_validity.adaptation_and_ledger` | 参数、派生家族、指标、样本和策略的自适应尝试是否预先限定并完整进入 ledger？ | Research cycle / Trial family |
| `trial_design_validity.stop_and_reopen_rule` | Trial 的停止、继续、打开 holdout 与重新开启条件是否事前明确且未被结果选择性改变？ | Trial / Research cycle |

不是所有实例都复制成“每个 Trial 一条”。`subject_scope=Trial` 的义务绑定具体
TrialPlan；`Trial family`/`Research cycle`/`Work Package` 级义务由 Trial 引用一个
coverage decision，输入 hash 未变化时复用。这样既确保每个 Trial 有完整设计约束，
又避免为同一 holdout/ledger/市场范围重复建义务和消耗 token。

### 与 `statistical_validity` 的关系

两者不是简单事前/事后，也不互相包含：

- `trial_design_validity` 判断**数据和比较是怎样产生/划分的，能否识别目标差异**；
- `statistical_validity` 判断**给定这些观测，estimand、统计量、依赖结构、不确定性、
  多重选择调整和敏感性推断是否成立**。

运行前二者都必须进入 TrialPlan：前者冻结 contrast/control/partition/coverage，后者
冻结 estimand/metric/estimator/uncertainty/multiplicity 方法。运行后也都要复核：
前者检查实际 Run 是否遵守设计；后者检查方法前提和推断边界。设计违例会降低
Evidence 资格或重开义务；统计不成立不能由“设计写得完整”替代。

例子：固定全部条件只改变 `end_session_skip` 属于设计有效性；用 block bootstrap
处理序列相关、报告效应区间属于统计有效性。保留最新 2026 holdout 属于设计有效性；
在打开后对多次家族/参数选择作调整属于统计有效性。

**决定：接受 `trial_design_validity`、删除 `research_decision` 义务大类，并增加 CLI/
报告硬约束。** 上述全部小类均纳入首版参考语义。Research Agent 在适用 Trial/
Trial family/Research cycle/Work Package 上必须逐项报告适用性、事实检查、裁决、
未解决项和 Evidence/Trial refs；不能只写“已考虑实验设计”。

## Grill 179.15 — 每个义务小类必须有 CLI resolver capability 与报告 contract

**用户要求，作为 Graph activation 硬约束。** Requirement Catalog 中每个可激活的
小类必须声明：

- `resolver_capability_ids`：取得结构化事实、验证前提或执行处置所需的 provider-
  neutral capabilities；
- `cli_invocation_templates`：Research Agent 可发现的最小 CLI 调用模板；
- `resolver_output_schema`：findings、evidence refs、missing inputs、limitations；
- `adjudication_policy`：哪些由代码确定、哪些必须由 Agent 结合语义判断；
- `report_requirement_refs`：适用性、动作、结果、义务 delta 与未解决项的必报 ID；
- `fallback_route`：缺能力/缺输入/无法判断时进入 capability gap、Trial 或 bounded
  unknown 的路径。

不能要求每个 handler 自动替 Agent 作统计/行业判断；CLI 必须提供足够事实、差异和
引用，使 Agent 能可靠裁决，并通过统一 obligation/report API 提交。建议公共命令面
保持少量稳定入口：

```text
factortester research requirements describe --id <requirement-id> --graph <ref> --json
factortester research obligations entry-check --branch <id> --target-node <id> --json
factortester research trial-design evaluate --trial-plan <ref> --checks <ids> --json
factortester research obligations adjudicate --obligation <ref> --input <json> --json
factortester research report requirements --anchor <ref> --json
factortester research report submit-item --input <json> --json
```

`trial-design evaluate` 内部按小类 capability binding 分派，不为每个小类建立风格不一
的顶层命令。首版 handlers 至少覆盖：contrast diff、baseline identity、controlled-
variable diff、population/universe inventory、information partition/holdout ledger、
sequential holdout audit、regime coverage/control table、instrument coverage/control
table、temporal overlap/gap audit、replication structure、adaptation ledger 和 stop/
reopen rule validation。

Graph 发布/激活 validator 必须证明每个 requirement ref 存在、每个小类至少有一个
已批准的 CLI resolver binding、output schema 可验证、Report Requirements 完整；
否则 Graph 只能保持 draft，不能成为 Active。运行时产品/数据不受某个 binding 支持
可以形成正常 capability gap，但不能出现“Graph 要求检查、系统根本没有检查入口”。

CLI 默认只返回当前小类的紧凑 JSON 和 artifact refs；表格、完整 ledger、数据清单
与日志按引用懒加载。entry-check 一次批量处理当前 gate 的小类，report submit 一次
提交多条 Items，避免逐义务数据库往返。

## Grill 179.16 — 以 `hypothesis_validity` 替代 Research Intent 元义务

**决定：接受。** `research_intent` 移出义务目录，作为 Research Decision Contract
保存研究问题、授权范围、决策目标、预算和停止边界。`hypothesis_preregistration`
节点依据该 contract 生成真实的 `hypothesis_validity` 义务；经济机制是核心，统计
显著本身不能代替机制。

### 核心小类与按机制触发的小类

所有假设至少检查以下核心问题：

| 小类 ID | Research Agent 必须回答的问题 |
|---|---|
| `hypothesis_validity.mechanism_chain` | 从市场事实/参与者行为到价格或收益的完整作用链是什么，方向与期限为何如此？ |
| `hypothesis_validity.observable_proxy` | 因子表达式、ColumnRefs 和参数真实代理了机制中的哪一环，代理何时失真？ |
| `hypothesis_validity.falsifiable_predictions` | 除“回测好”以外，机制还预测哪些符号、期限、标的、环境或参与者差异；什么事实会削弱/证伪？ |
| `hypothesis_validity.alternative_explanations` | 是否可能只是 beta、carry、趋势、流动性、数据/执行伪影、选择偏差或其他已知因子暴露？ |
| `hypothesis_validity.boundary_conditions` | 机制预期在哪些产品、时段、市场环境、流动性和参与者结构下成立或失效？ |
| `hypothesis_validity.derived_incremental_mechanism` | 派生家族新增的辅助表达式/参数改变了哪一环，为何预期优于或不同于父家族，怎样做对应实例比较？ |

根据 mechanism chain 条件触发以下小类；一个假设可以同时触发多个：

| 小类 ID | 机制问题 |
|---|---|
| `hypothesis_validity.participant_incentives` | 哪类参与者因风险敞口、信息、库存、资金、授权、期限或监管约束而产生该交易需求？ |
| `hypothesis_validity.behavioral_channel` | 是否依赖注意力不足、反应不足/过度、过度自信、自我归因、锚定、处置效应、羊群或趋势追逐；可观察预测是什么？ |
| `hypothesis_validity.risk_transfer_and_compensation` | 套期保值者转移何种风险，谁提供风险承接，预期收益是否是承担风险/资金约束的补偿？ |
| `hypothesis_validity.information_diffusion` | 信息如何在参与者、现货与期货、合约和时间中扩散，为什么价格不会立即吸收？ |
| `hypothesis_validity.liquidity_inventory_and_impact` | 流动性需求、做市库存、订单失衡、拥挤或价格冲击如何产生短期延续/反转？ |
| `hypothesis_validity.fundamental_supply_demand_and_carry` | 库存、生产/消费、季节性、仓储、融资、便利收益和期限结构如何作用？ |
| `hypothesis_validity.institutional_and_contract_rules` | 保证金、涨跌停、交割、限仓、交易时段、会员/合约制度或政策变化如何形成约束或结构断点？ |

### 参与者不是单一标签

Graph 不把“主力”“游资”当成可直接满足义务的正式分类。Agent 必须把口语标签拆为
可以重叠的描述：

- economic role：生产/消费/加工/贸易套保者、掉期/中介、做市/流动性提供者、套利者、
  管理资金/CTA、机构配置、个人或自主投机资金；
- information/behavior role：有信息交易者、信息观察者、趋势追随者、噪声交易者、
  羊群/注意力驱动交易者；
- constraints：现货风险、库存、资金/保证金、授权、风险限额、期限、赎回和监管；
- observable proxies：监管/交易所公布的参与者分类、会员/客户持仓、成交与订单流、
  持仓集中度、期限结构、基差、库存等，并声明识别限制。

CFTC 的正式披露区分 Producer/Merchant/Processor/User、Swap Dealers、Managed
Money 和 Other Reportables，说明“商业/投机”本身仍可能过粗；中国交易所会员持仓
也不能无证据推断为最终受益人或笼统“主力”。Agent 若使用“主力/游资”，报告必须
给出操作化定义、数据来源、proxy limitation 和反例，不能靠事后故事解释收益。

### CLI 与报告 contract

`hypothesis_validity.*` 每个小类同样受 Grill 179.15 约束。统一入口建议为：

```text
factortester research hypothesis assess --contract <ref> --factor-family <ref> \
  --checks <requirement-ids> --json
```

其 handlers 至少提供：因子表达式/ColumnRef/FactorParam 投影、机制模板、参与者角色与
约束表、可用定位/持仓/基本面/微观结构数据 inventory、父/派生家族差异、候选替代
暴露、边界条件矩阵和文献/Evidence refs。CLI 只验证结构与提供事实；经济/行为机制
裁决返回 `requires_agent_judgment=true`，由 Agent 依据第一性原理和证据判断。

节点/边必须逐项报告：LaTeX 与代理映射、机制链、参与者—激励—约束—动作—代理表、
行为心理或风险补偿依据、可证伪预测、替代解释、边界条件、派生增量机制与未解决
义务。每项绑定 requirement/obligation/Evidence refs；不能用一段笼统“具有经济
意义”代替。

### 实施不可遗忘约束

本文件及 Grill 178/179 的已接受条目是实现的 traceability source，不以会话记忆
代替。每个后续实施批次必须在 plan/commit test matrix 中列出所覆盖的 Grill IDs、
对应 schema/CLI/report/UI 行为和测试；Graph activation acceptance 必须检查所有已
接受 requirement/report/resolver contract。未映射的已接受决策视为实施未完成。

## Grill 179.17 — 跨产品、地区、场所与历史规则版本的机制语义

**用户要求，待确认架构边界；行业调研继续进行。** 经济机制不能只调研期货，也
不能把一个市场的参与者/规则类推到其他产品。首版调研矩阵至少覆盖：

- 产品：现金股票、ETF/基金、商品/金融期货、期权、固定收益/信用、外汇现货/远期/
  掉期、数字资产现货/永续/衍生品；
- 地区/司法辖区：中国大陆、香港、美国、欧盟/EEA、日本；
- 市场形态：交易所连续/集合竞价、做市/RFQ/OTC、集中清算或双边、24/7 或 session、
  现货/衍生品/组合交易；
- 时间：规则、产品规格、交易时段、结算、保证金、涨跌停、持仓/交易限额、卖空和
  数据透明度的 effective-from/effective-to 历史版本。

“地区”本身不够：中国大陆内不同交易所、板块、股票/可转债/期货/期权规则不同；
日本 OSE 夜盘把夜盘至下一日盘计作同一 trading day；美国股票有多场所/NMS 语义，
固定收益多为 OTC 成交披露；欧盟 equity/non-equity 的透明度与 waiver/defer 规则
不同。Graph 不允许用某个地区的默认规则填补未确认产品。

### 三层结构，避免把完整规则库塞进 Graph

1. **Graph Requirement Catalog（稳定问题）**：保存跨产品可复用的
   `hypothesis_validity.*`、`data.*`、`market_execution_accounting.*` 等问题、
   selector 和报告 contract；
2. **Versioned Product-Market Profile（外部事实）**：按
   `product_type + jurisdiction + venue/segment + rule_effective_period` 保存参与者披露、
   交易/清算/结算、价格/仓位/卖空限制、公司行动/交割、数据透明度、官方来源和
   profile hash；它不是 Graph topology，也不因每次规则更新重发整张 Graph；
3. **Branch-local hypothesis/obligation instances（研究解释）**：Research Agent 基于
   当前 Decision Contract pin 的 profile refs，把通用机制问题具体化为该产品/地区
   的义务、代理、预测和限制。

Graph 版本控制“什么时候需要哪类 profile 事实以及必须报告什么”；Market Profile
版本控制“当地当时的事实是什么”。Research branch 同时 pin Graph hash 和全部
profile hashes。规则 profile 更新时只重开受影响的小类/Claims；除非 selector/行业
语义本身改变，不需要修改 Graph。

### 不同产品必须额外回答的机制问题（初始路由，不是固定结论）

| 产品 | 条件触发的核心机制/规则问题 |
|---|---|
| 股票 | 所有权/现金流、公司行动、指数成员与存续偏差、卖空/借券、投资者结构、场所碎片化、价格限制与结算 |
| ETF/基金 | NAV/跟踪标的、申赎与 AP/做市、折溢价、成分可得时点、费用与再平衡 |
| 期货 | 风险转移/套保压力、期限结构/库存/carry、合约选择/换月/交割、保证金/逐日盯市、限仓/涨跌停/夜盘 |
| 期权 | 非线性 payoff、隐含波动/波动风险溢价、Greeks/动态对冲、行权/指派/到期、卖方保证金和波动率曲面 |
| 固定收益 | 票息/应计利息/到期、信用/利率/流动性风险、OTC 报价与成交稀疏、回购/融资、违约和嵌入期权 |
| 外汇 | 双边货币与 funding/carry、fixing、现货/远期/掉期点、跨时区 OTC 流动性、结算与资本/交易限制 |
| 数字资产 | 现货/永续基差与 funding、交易所/托管/对手方风险、强平机制、24/7 session、链上/链下流动性和规则碎片化 |

每个产品都仍可调用行为、信息扩散、风险补偿、流动性与参与者异质性机制，但 Agent
必须解释为何代理在该产品/场所可观察；不能把 CFTC trader category、股票龙虎榜、
交易所会员排名或加密地址标签当成可互换的“主力”数据。

### CLI/报告要求

规划开始先明确产品范围；CLI 至少提供：

```text
factortester product-library scope inspect --workspace <ref> --json
factortester markets profiles resolve --product <id> --venue <id> --as-of <time> --json
factortester markets profiles describe --ref <profile-ref> --json
factortester markets rules diff --from <profile-ref> --to <profile-ref> --json
factortester research hypothesis assess --market-profile <ref> ... --json
```

每个机制 Report Item 必须列出 product/venue/jurisdiction、profile version/hash、规则
生效期、本地参与者/代理定义、不可识别部分和跨市场类比依据。跨市场类比只能生成
候选义务/Trial，不能直接继承 Evidence 状态。

### 当前已核对的官方/原始资料方向

- CFTC COT 将商品参与者细分为生产/贸易/加工/使用者、掉期交易商、管理资金和其他
  可报告者，且分类依据实体活动；
- 期货风险溢价研究区分长期套保需求与短期流动性需求，不能把“投机者净仓”解释成
  单一方向；
- 行为金融原始模型覆盖反应不足/过度、自信/自我归因、渐进信息扩散、趋势追随、
  噪声交易者风险与套利限制；
- 美国股票 NMS、美国固定收益 TRACE、中国交易所价格/保证金/持仓制度、日本 OSE
  夜盘、欧盟 MiFIR equity/non-equity 透明度均展示显著制度差异。

在实现 Graph/CLI 之前，必须把上述产品×地区矩阵的官方来源、规则字段、机制
selectors、profile schema 和测试样例补齐；当前期货调研不得被标记为全产品完成。

## Grill 179.18 — 小类是义务生成指南，不是预制研究结论

**决定：接受。** Requirement Catalog 的小类只指出一个经行业审计、在适用
研究中必须考虑的方面，并提供足够描述指导 Research Agent 生成具体义务。它本身
不是某个因子必须满足的硬编码结论，也不要求服务器预先列出所有可能义务。

每次小类在 entrypoint 被 selector 触发后，Research Agent 读取小类短描述/完整
contract，并结合：Decision Contract、因子家族/实例表达式、Product-Market Profile、
可用数据、已有 Claims/Evidence/义务，作出 `applicability decision`：

1. **适用且存在决策相关问题**：创建一条或多条 branch-local 具体 Verification
   Obligations，声明问题、subject/scope、预期/不足证据、Claim 影响、候选 resolver/
   Trial 和停止条件；
2. **适用但现有义务已覆盖**：记录 coverage decision，引用既有 obligation revision，
   不重复创建；
3. **当前不适用或无法形成有意义义务**：逐项报告理由与所依据的产品/表达式/数据
   refs；这不是义务解除，输入变化时必须重审。

Graph entry gate 检查的是：小类发现过程是否完成、生成/复用的具体义务是否得到所需
处置；后续 Trial 绑定并试图改变的是具体义务状态。Catalog 小类更新可能使旧研究
重新进行 obligation discovery，但不会自动给所有分支批量生成相同义务。

### 哪些“假设”可以登记为小类

可以登记**稳定、跨研究可复用的理论机制族**，例如：

- `behavioral_channel`：行为偏差是否可能产生可证伪的延续/反转等机制；
- `risk_transfer_and_compensation`：风险转移与风险承接补偿；
- `information_diffusion`：信息扩散速度与参与者信息结构；
- `liquidity_inventory_and_impact`：流动性需求、库存和价格冲击；
- `fundamental_supply_demand_and_carry`：供需、库存、carry 与期限结构；
- `institutional_and_contract_rules`：制度/合约规则造成的结构性机制。

不能把产品/因子特定的结论直接登记成 Catalog 小类，例如“某类中国期货的游资会让
SgCPS 在五分钟频率反转”。这应是 branch-local Research Hypothesis 和具体义务；
小类只要求 Agent 询问参与者是谁、激励/约束是什么、代理数据是什么、可证伪预测和
替代解释是什么。

每个小类 contract 因而增加 `generation_guidance_zh`、`candidate_questions_zh`、
`applicability_hints`、`anti_storytelling_checks` 和 `concrete_obligation_schema`。
CLI resolver 提供当前 subject 的事实包与 obligation draft 模板；Research Agent
作语义判断并提交，Graph 确定性验证字段、refs、报告覆盖与后续 Trial binding。

### 必报内容

每次触发的小类必须报告：为何适用/不适用、查看了哪些当前事实、生成或复用了哪些
具体义务、为什么这些义务会改变决定、计划用何种 CLI/Evidence/Trial 处理、仍缺什么。
这属于 entry/node 的 Report Requirements，不另造“报告义务”。

## Grill 179.19 — 逐小类回答、无数据仍建义务、由目标驱动首个 Trial

**决定：接受，并增加目录外义务发现与 Trial 可行性前置门。** Requirement selector 在当前 entrypoint 展示适用候选大类/小类后，
Research Agent 必须逐小类提交一行 `obligation_discovery_decision`，不能跳过：

```json
{
  "requirement_ref": "hypothesis_validity.behavioral_channel@1",
  "decision": "create|reuse|not_applicable|no_material_issue",
  "reason_zh": "...",
  "fact_refs": [],
  "created_or_reused_obligation_refs": [],
  "first_resolution_action": {
    "kind": "cli_evidence|trial_candidate|capability_gap|bounded_unknown",
    "ref_or_description": "..."
  }
}
```

语义约束：

- `create`：存在会改变当前 Claim/Trial/决定的具体问题，创建 branch-local 义务；
- `reuse`：既有具体义务已经覆盖，引用其 revision；
- `not_applicable`：当前产品、表达式或研究范围确实不触发，必须给事实理由；
- `no_material_issue`：已认真检查，但当前无法形成会改变决定的具体问题，必须说明
  检查内容；输入变化后重审。

**缺数据或缺方法不能选择不建立。** 若问题本身决策相关，仍须 `create`，状态保持
open/unknown；`first_resolution_action` 选择数据/CLI capability gap 或 bounded
unknown。随后可询问用户接入数据、寻找公开/服务器数据、提交 connector/后端任务，
或限制结论。这样认知债务不会因当前不可测而消失。

### 每项具体义务先声明“第一处置动作”，不强迫全部立即建 Trial

新义务必须说明第一个最小处置动作：

1. 能由现有 CLI 确定性取得事实的，先做 `cli_evidence`，不滥建 Trial；
2. 需要经验比较的，提出 `trial_candidate`，注明 primary obligation、可能共同处理的
   secondary obligations 和所需数据；
3. 缺 CLI/后端/数据能力的，走 `capability_gap`；
4. 当前不存在可行验证方法的，保持 `bounded_unknown` 并说明阻塞节点/Claim。

一个 Trial 必须有且只有一个 `primary_obligation_ref`，防止跑完后事后挑选解释；可
有多个预声明的 `secondary_obligation_refs`。一个义务也可需要多个递进 Trial。

### 用户目标与第一个可执行 Trial

用户在研究开始时与 Planning Agent 确认的 Research Decision Contract 至少提供：
研究目标/拟支持的决定、授权因子家族范围、产品/市场范围、资源/token 上限、最新
holdout 边界和用户明确的优先问题。它决定“什么具有决策价值”，但不要求用户逐条
发明统计/行业义务。

Research Agent 完成初始 obligation discovery 后，生成按以下顺序解释的候选队列：

1. 阻塞其他试验的前置事实/语义义务；
2. 与用户目标最相关、最可能改变决定的义务；
3. 信息价值高且成本低的验证；
4. 不会提前污染 holdout、且依赖已满足的 Trial；
5. 其余可并行或后置的义务。

Research Agent 在报告中明确推荐“第一个可执行 Trial”及其 primary/secondary 义务、
为何优先、为何不是其他候选。若不同优先级会实质改变研究方向、因子范围或消耗，
必须在对话中请用户确认；在已授权范围和预算内的常规后续 Trial 可由 Agent 自主
推进。若当前只有 CLI/data/capability 前置动作，则如实报告“尚无可执行 Trial”，
先解决前置项，不能为了满足流程编造试验。

### Graph/CLI/报告门

- entry gate 要求所有当前触发小类都有 discovery decision；
- `create/reuse` 必须有 obligation ref 与第一处置动作；
- `not_applicable/no_material_issue` 必须有中文理由和 fact refs；
- 报告用逐小类表格展示决定、理由、具体义务、数据可得性、第一处置动作和是否阻塞；
- TrialPlan 提交时 CLI 校验 primary obligation、预声明 secondary obligations、用户
  目标/授权 scope 和 holdout/ledger refs；
- server transition delta 只上传这些决定和 refs/hash 的紧凑投影。

## Grill 179.20 — Catalog 后强制开放式义务发现，Trial 前检查数据/能力可行性

**决定：接受。** Catalog 是认知脚手架，不是封闭清单。完成当前触发小类的逐项回答后，
Research Agent 必须再执行一次第一性原理扫描：基于研究目标、因子表达式、产品市场
规则、现有 Evidence/冲突和刚发现的未知项，判断是否存在未被 Catalog 提醒但会改变
Trial、Claim 或决定的义务。

输出必须是以下之一：

- `new_obligations`：逐项给出问题、决策影响、证据标准和候选分类；能放入现有大类
  则登记在该大类，只有确无匹配才登记 `other`；
- `no_additional_material_obligation`：说明检查了哪些机制链、反例、参与者、数据限制、
  市场规则和替代解释，以及为何当前没有新的决策相关义务。

这个扫描在初始 obligation discovery、重要 Evidence 产生后、`result_audit`、准备
bounded closure 和 Graph continuation re-entry 时触发；普通无变化边不重复运行，
输入 hash 未变时复用 checkpoint，控制 token。

### CLI 数据/能力可行性检查

义务进入正式 TrialPlan 之前，Research Agent 必须先查询当前批准的能力和数据接口，
而不是假设“可能有数据”。统一 CLI 应能按 obligation evidence needs + product/
venue/frequency/window/fields 返回：

- 可用的数据源（服务器管理、用户本地、外部 connector）与权限；
- 产品/合约、时间范围、频率、字段、L1/L2、延迟/实时、缺口和 point-in-time 状态；
- 已批准 resolver/backend capability 及支持范围；
- `available_now|partial|missing|prohibited|unknown`；
- 证据 refs、限制和建议的 capability/data route。

建议稳定入口：

```text
factortester research obligations discover-gaps --branch <id> --checkpoint <ref> --json
factortester research obligations feasibility --obligation <ref> --json
factortester data availability resolve --needs <json-or-ref> --json
factortester research capabilities resolve --needs <json-or-ref> --json
```

`discover-gaps` 由 CLI 组装紧凑事实包和校验输出 schema，第一性原理判断由 Research
Agent 完成；它不是让代码假装发现新理论。

### Trial admission gate

只有同时满足以下条件才能创建/冻结正式 TrialPlan：

1. primary obligation 与预声明 secondary obligations 已登记；
2. 所需数据为 `available_now`，或 `partial` 但其缺口不破坏该 Trial 的判定标准且已
   明确限制；
3. resolver/backend capability 已有批准 binding 并支持当前产品/频率/范围；
4. Product-Market Profile、数据/规则版本、holdout 和 ledger refs 已 pin；
5. Trial 的 Evidence 能够按预声明标准改变至少一项义务状态。

不满足时不进入正式 Trial 设计/执行：

- 数据缺失/禁止/未知：保留义务，走 data/capability resolution，必要时询问用户接入
  数据或寻找公开数据；
- CLI/backend 缺失：创建 Maintenance Task 等待 Server Agent；
- 当前不可验证：保持 bounded unknown 并限制节点/Claim；
- 可以记录一句候选验证方向，但不创建会被误认为可执行的 TrialPlan 或占用 Trial
  ledger 编号。

报告/UI 必须同时展示具体义务、需要什么数据/能力、当前 availability、为何能/不能
进入 Trial、所走 gap 路径和恢复 entrypoint。服务器只保存 feasibility 决定与 refs/
hash，不复制本地数据清单或源码。

## Grill 179.21 — `capability` 是否应移出 Verification Obligation Catalog

**决定：接受。** 经前述“节点/动作不等于义务”的审计，`capability` 也不像真实研究
义务：它不回答市场、因子、Trial 或 Evidence 的未知事实，而回答当前系统是否有能力
取得/计算所需证据。建议：

- 从 Verification Obligation 大类中删除 `capability`；
- 保留现有 provider-neutral `CapabilityRequirement`、`CapabilityBinding`、
  `CapabilityGap` 和 Maintenance Task 对象/节点；
- 每项具体义务的 `first_resolution_action` 与 Trial admission gate 声明所需
  capability IDs；缺失时产生 CapabilityGap，而不是伪造一条“能力义务”；
- `capability_resolution`、`capability_gap`、`skill_candidate_review`、
  `code_improvement_required` 节点继续存在并按已确认的 Research/Server Agent
  交接流程工作；
- 能力变化仍必须报告修改、增强范围、receipt、剩余限制与恢复决定，但这些是节点/
  边 Report Requirements，不绑定虚假的义务小类。

Graph report requirement 必须绑定真实义务小类的既有规则，需要对能力节点作明确
例外修正：纯运维条目绑定 `capability_requirement_ref`/`maintenance_task_ref`，而非
Verification Obligation subcategory。它仍是可审计的 Graph 报告门，只是不污染认知
义务集合。

若接受，正式 Verification Obligation 大类暂收敛为：`hypothesis_validity`、`data`、
`factor_semantics`、`trial_design_validity`、`statistical_validity`、
`strategy_design`、`market_execution_accounting`、`evidence_integrity`，加 fallback
`other`；下一问继续审计 `evidence_integrity` 是否也应改为 Evidence Qualification
而不是普通义务。

### CapabilityRequirement / Binding / Gap / MaintenanceTask 的区别

它们是一次能力解析的四个逻辑概念，不代表四张数据库表：

1. `CapabilityRequirement`（需要什么）：当前义务/节点要求的 provider-neutral
   能力语义、输入输出和支持范围。例如“检查中国期货某产品逐日保证金率历史是否
   覆盖 Trial window”；它来自 Graph/义务/Trial，不指名 Skill 或实现。
2. `CapabilityBinding`（现在由什么已批准实现完成）：本地或服务器 registry 选择的
   CLI/backend implementation ID、版本/hash、支持产品/频率/范围和 approval receipt。
   例如某版 `factortester data availability resolve` handler 能完成上述检查。
3. `CapabilityGap`（解析后哪里不满足）：Requirement 找不到合格 Binding，或 Binding
   不支持当前产品/范围时的分支局部结果；必须说明缺什么、阻塞什么、哪些工作不受
   影响和恢复目标。它是 checkpoint/transition delta，不需要独立数据库表。
4. `MaintenanceTask`（谁去做什么）：只有缺口需要 Server Agent 行动时才创建的可
   执行任务，带 task ID、状态和 result JSON。例如补 Tiger/OSE 数据覆盖、增加 CLI
   handler 或修复代码。数据本来不存在、权限禁止或决定接受 bounded unknown 时，
   Gap 可以没有 Task。

确定性关系：

```text
CapabilityRequirement
        ↓ registry resolve
CapabilityBinding ──有且范围匹配──> 执行
        └─没有/不匹配──> CapabilityGap
                              └─需要服务器工作──> MaintenanceTask
                                                     ↓ result/receipt
                                                新/更新 Binding
                                                     ↓ re-resolve
                                                  恢复 checkpoint
```

最小持久化：Requirement 随 Graph/Trial refs；Binding 在既有 registry/cache；Gap 嵌入
branch checkpoint 和 trace；只有 MaintenanceTask 使用 Grill 179.9 的统一任务表。
一个 Task 可处理一组紧密相关 Gap，一个 Gap 也可能需要数据、CLI 和后端多个 Task，
但必须显式列 refs，不能靠对话关联。

## Grill 179.22 — `evidence_integrity` 改为 Evidence Qualification Gate

**决定：接受。** `evidence_integrity.identity_and_lineage`、artifact completeness、backend
receipt 和 applicability scope 的职责是判断一份 Evidence 能否参与裁决，而不是描述
需要 Trial 验证的市场/因子未知问题。建议从 Verification Obligation 大类中删除
`evidence_integrity`，改为 EvidenceEnvelope 内的强制 qualification contract：

```text
qualification_status = eligible | limited | pending | reference_only | rejected
checks = identity_lineage + artifact_completeness + backend_receipt + applicability_scope
anomalies = explicit invariant violations only
```

正常路径仍按 Grill 179.6 确定性检查，不调用 Agent/源码审查；报告逐份 Evidence 的
身份、完整性、范围、资格和异常。若发现问题，不创建含混的“证据完整性义务”，而按
真实语义路由：

- 数据来源、缺失、时点或值质量问题 → 创建/重开相应 `data.*` 义务；
- 会计、信号、市场规则实现问题 → 创建/重开 `strategy_design.*` 或
  `market_execution_accounting.*` 义务；
- 统计方法/推断问题 → `statistical_validity.*` 义务；
- 后端 receipt/代码不变量问题 → CapabilityGap/Maintenance Task；
- 仅结果冲突但无 integrity 违例 → 保留两份 Evidence，生成相应机制/统计/边界义务，
  不把“不一致”当作损坏。

Qualification 状态与 Verification Obligation 状态正交：一份 `limited` Evidence 仍
可能缩小某个窄范围义务；一份 `eligible` Evidence 也不会自动解除义务。资格投影存
在 EvidenceEnvelope/trace 中，不新增独立数据库表；Agent packet 只取状态、限制和
refs。

v8 的 `job_evidence_ready` 只是当时等待 Job/artifact 的实现；后继图不将
Evidence qualification 本身建模为节点。`result_audit` entrypoint 继续强制资格门与报告。相关 Report
Requirements 绑定 `evidence_ref`/qualification check IDs；若资格问题导致真实研究
义务，再绑定该具体 obligation ref。这样不削弱审计，反而避免为了每个 artifact
制造元义务。

若接受，普通 Verification Obligation 大类收敛为七个：`hypothesis_validity`、
`data`、`factor_semantics`、`trial_design_validity`、`statistical_validity`、
`strategy_design`、`market_execution_accounting`，加 fallback `other`。

## Grill 179.23 — 测试边上的 Evidence Admission Gate 与真实义务映射

**决定：已接受。** 将 Evidence Qualification 具体化为任何 evidence action 通往
`result_audit` 时的系统派生 `EvidenceAdmissionGate`。它附着于目标 entrypoint/
edge guard，不新增永久业务节点。v8 的 `job_evidence_ready` 只是 Job/artifact 到齐的
旧实现；后继图由 `trial_execution` 保留同步/Job/connector action 的执行和等待状态。
Admission Gate 决定产物能否以
`eligible|limited|pending|reference_only|rejected` Evidence 进入 `result_audit`。

### 两层不能混淆

1. **Evidence admission**：这份结果是不是它声称的那个 Trial/Run 的完整、可追溯、
   范围明确的产物；
2. **Result audit**：在 admission 限定的范围内，它对 Claims/义务意味着什么。

表现差、结论相反或不同市场阶段冲突不使 admission 失败；它们在 Result Audit 中
产生机制、统计、边界或新 Trial 义务。

### Admission 必查项与可触发的真实义务

| Admission check | 正常确定性检查 | 失败/异常时使用的真实义务或对象 |
|---|---|---|
| `identity_lineage` | Work Package、Graph、家族版本、因子实例、TrialPlan、RunSpec、数据/规则版本 hashes 一致 | 身份无法修复则 reject；错用表达式/实例重开 `factor_semantics.*`，不造 integrity 义务 |
| `job_artifact_terminal` | JobAttempt 终态；预声明 metrics/tables/series/failure artifacts 齐全 | 缺后端产物 → CapabilityGap/MaintenanceTask；Job 失败本身保留失败 Evidence |
| `data_provenance_and_quality` | 实际数据源/范围/字段/时点/缺失/单位与 Trial pin 一致 | `data.trial_window_coverage`, `point_in_time_integrity`, `schema_and_units`, `value_quality`, `universe_and_survivorship` |
| `factor_and_timing_adherence` | 实际表达式、参数、ColumnRefs、频率和 causal alignment 与 Trial 一致 | `factor_semantics.expression_validity`, `causal_timing`, `expression_parameterization` 等 |
| `trial_design_adherence` | 对照、控制变量、信息分区、holdout、regime/instrument scope、ledger 与冻结设计一致 | 对应 `trial_design_validity.*` 义务重开；严重污染时 reference-only/rejected |
| `strategy_adherence` | signal schedule、session policy、仓位/调仓和条件化规则与 RunSpec 一致 | `strategy_design.*` |
| `market_accounting_adherence` | session/calendar、换月、撮合、手续费、保证金与结算规则版本和实现 receipt 一致 | `market_execution_accounting.*` 或 CapabilityGap |
| `statistical_plan_adherence` | 输出的 estimand/metric/method/selection ledger 是预声明版本，基本 schema/不变量成立 | `statistical_validity.estimand_and_metric`, `method_assumptions`, `selection_and_multiplicity`；详细推断留给 Result Audit |
| `backend_receipt_and_invariants` | 批准的 build/config receipt；资产曲线/收益/现金流等低成本不变量通过 | 具体语义义务或 CapabilityGap/MaintenanceTask；遵循 Grill 179.6 严格异常触发 |
| `applicability_scope` | Evidence 实际产品、时间、环境、参数、策略范围可由 artifacts 证明 | 形成 `limited` scope；必要时重开 data/design/market obligations，不自动外推 |
| `related_other` | 当前 Trial/Evidence/目标节点关联的 open `other` 已检查 | 按 Grill 179.12/179.13 处置；不能因专门 checks 通过而忽略 |

新增的 `data.schema_and_units`、`data.value_quality`、
`data.universe_and_survivorship` 是数据义务小类，不是每次都要求昂贵检查：Catalog
selector 按字段/产品/Trial 触发，CLI 先运行 schema、范围和低成本异常摘要，只有异常
时加载详细 artifact 或 Agent 判断。

### Gate 结果与路由

- 全部硬检查通过且限制明确 → `eligible`；
- 可用于窄范围但有已量化限制 → `limited`，下游只允许该 scope；
- 缺 Job/artifact/task 尚可恢复 → `pending`，保存 EntryResolutionFrame；
- 设计污染或旧版本无法满足当前要求但仍可作历史参考 → `reference_only`；
- 身份不明、不可修复损坏或伪造 → `rejected`。

Gate 不要求研究范围中的所有义务都已解除，只要求本 Trial 声明处理的 primary/
secondary obligations、运行前置条件和相关 `other` 得到必要处置。未由本 Trial 处理的
开放义务继续存在，并在 Result Audit/Research Decision 中限制 Claim。

必须生成逐检查 Report Items：check 名称、状态、实际 refs、关联真实义务、限制、
修复/绕行路径与最终 Evidence qualification；CLI 批量执行并只返回紧凑结果，详细
统计表和 artifacts 懒加载。

### Graph Definition v2 建议字段

```text
GraphDefinition v2
  identity/provenance/change_manifest
  requirement_catalog
    categories
    entry_requirements
  report_method_descriptors
  report_requirements
  nodes
    entry_requirement_refs
    entry_report_requirement_refs
    action_report_requirement_refs
  edges
    report_requirement_refs
  system_transition_policies
  capability_descriptors
  research_cycle_operations
  maintenance_operations
  review_policy
```

旧 v8/v1 只保留冻结读取器用于 continuation 和一次性历史迁移；新 Graph 发布与
activation 只接受 v2。Research Agent 的正常 packet 不返回整个 v2，而由 selector
只投影当前 node/edge 的目录摘要和缺失 Report Requirement IDs。

### 实施批次

1. 先增加共享 v2 schema、cross-reference validator 和 content-hash tests；
2. 再把 v8 topology 导入 v2 builder，加入 Requirement/Report/Manifest components；
3. 更新 server publish/activation/continuation/context/next；
4. 更新 CLI template/validation/advance/recovery；
5. 更新本地 journal、Markdown 与 FTClient node/edge/upgrade-edge 投影；
6. 最后执行 v8 一次性报告迁移和 MaxA 同 Work Package 验收。

## Grill 179.24 — CLI 辅助义务回应与既有验证复用

**已接受。** Graph 每次要求 Research Agent 回应义务大类/小类、处理 entrypoint
或 Evidence Admission 时，CLI 必须提供紧凑的本地辅助接口。Agent 不应自行拼接
完整图、义务历史、EvidenceEnvelope 或报告 JSON，也不应重复执行输入没有变化的验证。

### Agent 获得的最小响应包

CLI 根据当前 branch、target node/edge 和 obligation ref 一次返回：

- 义务大类、小类、中文 alias 和当前问题描述；
- 为什么本 entrypoint 触发、Agent 必须回答什么；
- 当前义务状态、scope、primary/secondary Trial refs；
- 可用的 resolver capability、可直接运行的 CLI invocation template；
- 已有 Evidence/Trial/报告条目的紧凑摘要和引用；
- 可复用验证候选及 `exact|partial|stale|incompatible` 判断；
- 尚缺事实、允许的 disposition 和最短报告模板；
- 预期的 report requirement IDs 和恢复目标节点。

Agent 只补充不能由程序生成的内容：是否建立/复用/重开义务、语义理由、Evidence
如何改变义务，以及下一项 action。CLI 校验、登记并确定性生成中文 Report Item、义务
变化表格和 evidence chips；Agent 不重复书写 provenance、hash、表格或历史裁决。

### 验证复用不是按 ID 复用

现有 `evidence capture-job` 的 envelope-hash 去重继续保留，但义务验证能否复用必须由
确定性 `ValidationFingerprint` 判断，至少覆盖：

```text
resolver capability + implementation/version
graph requirement subcategory revision
obligation question/criterion revision
factor-family version + factor-instance parameters/expression hash
product/instrument/universe scope
data source + field/range/PIT snapshot hash
TrialPlan/RunSpec + strategy/rule/accounting hashes（适用时）
method/ledger revision（适用时）
```

- 全部相关维度一致且 Evidence 未失效 → `exact`，直接引用，不重跑；
- 只覆盖当前 scope 的一部分 → `partial`，引用已覆盖部分，只补缺口；
- requirement、数据、规则或实现版本变化可能影响裁决 → `stale`，保留历史 Evidence，
  仅重新检查受影响部分；
- 问题、产品、因子实例或方法不具可比性 → `incompatible`，只能作背景参考。

复用必须产生一条轻量 `validation_reused` 审计事件，记录原 validation/evidence refs、
当前义务、fingerprint comparison、复用范围和未覆盖限制。报告正文只写自然语言结论并
引用 chip；完整旧验证仍按 ref 懒加载，不复制进新 trace、报告或 Agent packet。

### 建议的 CLI 能力边界

命令名称在实现前与现有 Click group 统一，但必须覆盖四个语义动作：

1. **inspect**：投影当前 entrypoint 相关义务、报告要求和复用候选；
2. **resolve**：运行该小类登记的确定性 resolver，或返回明确 CapabilityGap；
3. **respond**：校验 Agent 的语义裁决和义务 delta，生成标准报告条目；
4. **admit**：批量运行 Evidence Admission checks，优先复用 fingerprint 命中的验证。

不得设计成每条义务一次数据库往返：checkpoint 时批量读取当前 entry requirements、
branch-local obligations 和 fingerprints；artifact 详情只在 Agent 明确请求或异常时
懒加载。相同 input hash 的 selector、resolver 和 report projection 必须命中本地缓存。

### 报告与审计要求

复用不是无声跳过。每一条被要求回应的小类仍要在报告中出现，但可以简写为：

> 本项沿用验证「中文 alias」；其因子版本、数据范围、规则与判定标准未变化，验证
> 指纹完全一致，因此未重复运行。适用范围为……，仍未覆盖……。

UI chip 显示旧验证的中文 alias、验证时间、适用范围、复用状态和限制；点击后再加载
原 Evidence、Trial、统计表和审计记录，不显示 UUID 作为主要文本。

## Grill 179.25 — Evidence 复用与义务裁决复用分层

**已接受。** 同一用户工作区内，不同 Profile/Work Package 可以检索并复用有权限的
Evidence，但复用分为两个层次：

1. **Evidence reuse**：事实、CLI 验证或 Trial 结果的 ValidationFingerprint 与当前
   问题相容，因此不重复计算；
2. **Obligation adjudication reuse**：只有 requirement revision、义务问题、discharge
   criterion、scope 和 Evidence qualification 也一致时，才能沿用原状态裁决。

Graph/Requirement 升级后，旧 Evidence 可能仍是 `exact|partial` 可复用，但旧的
`discharged|bounded` 裁决可能变为 `stale`，Research Agent 必须针对新版要求重新判断；
不得因保留旧 Evidence 而自动保留旧裁决。

## Grill 179.26 — CLI 查询结果的 Evidence 身份与 resolver 模块边界

**已接受。** CLI 查询结果可以成为 Evidence，但“CLI 输出”本身不是充分条件。只有
可复现、可溯源且 scope 明确的事实性结果才进入 EvidenceEnvelope。CLI 必须声明
本次输出属于：

- `measurement`：对数据、配置或运行产物执行确定性测量，形成新的 Evidence；
- `snapshot`：读取外部/服务器/本地数据源在特定 as-of 下的事实快照，形成新的
  Evidence，但必须携带上游来源和时效；
- `projection`：对已有 Evidence/义务/Trial 的紧凑查询，只生成引用和视图，不产生
  独立 Evidence，也不得在统计或义务裁决中重复计数；
- `diagnostic`：解释缺口、命令可用性或修复建议，默认是 Capability/流程事实，只有
  其中有独立可验证测量时才拆出 Evidence。

可入 Evidence 的 CLI result receipt 至少包括：

```text
resolver capability ID + implementation/version
normalized invocation/query hash
subject/scope/as-of
upstream data/artifact/version refs
result schema revision + content hash
success/partial/failure status
limitations/freshness/expiry policy
```

Agent 的自然语言解释、搜索建议和裁决不混入该事实 receipt；它们分别进入 Report Item、
obligation delta 和 decision warrant。查询历史记录时只返回原 Evidence ref、alias、摘要
和 fingerprint comparison，不能把一次 projection 包装成第二份 Evidence。

### 每个义务小类必须同时完成 CLI resolver 决策

Requirement Catalog 中每新增或修改一个义务小类，当场必须决定并校验：

1. 可以由哪个现有 CLI capability 提供哪些事实；
2. 需要的新 resolver 是确定性查询、测量、Trial，还是只能形成 CapabilityGap；
3. invocation template、输入 scope、输出 schema、Evidence kind 和 adjudication policy；
4. 失败、无数据、部分覆盖、过期和不可验证时如何路由；
5. 对应的逐条中文 Report Requirements 和可懒加载 artifacts；
6. ValidationFingerprint 的相关维度及缓存失效条件。

缺少上述 resolver descriptor 的义务小类不能随 Graph 激活。它仍可作为 catalog proposal
进入 MaintenanceTask，但不得让 Research Agent 面对一个没有可执行处置方式的正式
entry requirement。

### 代码与文件夹约束

不得把所有小类塞进一个大型 `commands/obligation.py`、`core/obligations.py` 或单个
Graph builder。实现前按稳定语义重新规划目录，建议边界为：

```text
requirements/       # category/subcategory descriptors and selectors
resolvers/          # one domain package per obligation category
evidence/           # receipts, fingerprints, qualification and reuse
reporting/          # report requirement validation and projections
graph/              # topology, entry bindings and transition policy only
```

每个 category package 暴露统一 registry interface；具体 subcategory 使用小型 descriptor
和 resolver，不复制 CLI boilerplate。Click command 只做参数解析和调用 service，不承载
领域逻辑。GraphDefinition 只引用 capability/requirement/report IDs，不内嵌 resolver 代码。

实施验收必须包含：模块依赖方向检查、registry 完整性、每个小类的 resolver contract
测试、单文件体积/职责审查，以及 CLI 输出 schema/fingerprint/report round-trip 测试。
如果现有持久化或目录语义不适合，应先重构稳定边界再加入小类，不以连续补丁撑大旧文件。

## Grill 179.27 — Evidence freshness 与按成本失效重查

**已接受。** 每个 resolver descriptor 必须声明 Evidence freshness policy，不允许由
Research Agent 临场猜测旧验证是否过期：

- 冻结 JobAttempt、不可变 artifact、按 content hash 固定的历史 bundle：相关 hashes
  不变时不按墙上时间过期；
- 交易规则、字段 schema、Product-Market Profile 和后端实现 receipt：按版本或
  effective-period 变化失效；
- 实时/延迟数据 availability、最新覆盖范围、entitlement、服务健康状态：按明确
  as-of/TTL 或来源事件失效；
- requirement/discharge criterion 更新：Evidence 本身可以保留，义务裁决必须重新
  qualification；
- 低成本、确定性且没有外部副作用的 stale resolver，只在实际进入相关 entrypoint
  时自动批量重查；
- 昂贵外部查询、付费数据、长 Job 或 Trial 不自动重跑，形成明确 action/cost/stop
  condition；不阻塞未受影响的任务。

运行时局部包只返回 `valid|stale|partial|incompatible`、失效原因、原 Evidence ref 和
建议动作；完整旧验证按需读取。缓存 key 使用 resolver/fingerprint/input hashes，禁止
以“进入同一节点”作为无条件重查原因。

## Grill 179.28 — `statistical_validity` 小类及 CLI resolver

**已接受。** `statistical_validity` 保持 Grill 179.4 的六个稳定推断问题小类，并为每个
小类同时定义 CLI resolver contract：

| 小类 | CLI resolver 必须提供的事实/动作 |
|---|---|
| `estimand_and_metric` | 投影 Trial 的 estimand、指标、方向、单位和聚合口径；检查实际结果 schema 是否与预声明一致 |
| `dependence_structure` | 测量序列相关、横截面/合约/市场聚类与样本重叠；返回适用方法候选和限制 |
| `uncertainty_and_effect_size` | 按已绑定方法计算区间、效应大小和可辨识范围；Bootstrap Sharpe 是按需候选能力，不是固定流程 |
| `selection_and_multiplicity` | 批量读取完整 Trial/参数/派生家族 ledger，描述选择路径；在前提满足时提供 DSR、PBO 等候选方法 |
| `method_assumptions` | 按当前方法检查样本量、缺失、分布、平稳性和方法特有前提；不得用单一通用 pass 替代 |
| `sensitivity_and_falsification` | 根据预声明替代口径生成/检查比较任务，登记已执行反证及仍缺 Trial/能力 |

每个 resolver 返回已掌握事实、候选 method capabilities、方法前提、已有验证与复用
状态、缺失能力、Agent 必须回答的义务和中文 Report Requirement IDs。IC、分组单调性、
Bootstrap、DSR、PBO 和置换检验是按 Claim/Trial 绑定的能力，不成为每个因子固定流水线。
单独使用 holdout 或固定 Sharpe 阈值不能替代 selection ledger 和多重选择审查。

## Grill 179.29 — 统计/回测能力补齐与 Equity Curve 报告产物

**已接受。** 当前 FactorTester 后端缺少某个已触发统计 resolver、回测结果字段或通用
报告 artifact 时，不允许 Research Agent 私下用临时代码伪造正式 Evidence。CLI 返回
CapabilityGap；Research Agent 记录研究影响和建议语义，Server Agent 通过统一
MaintenanceTask 补齐、测试、发布 capability binding/result JSON，Research Agent 在
原 EntryResolutionFrame 恢复后继续。未受影响的 Job/分支继续运行。

### Equity curve 是交易型权威回测的标准 artifact

凡 Trial 产生订单、持仓和绩效主张，Backend Result Contract 必须至少提供：

- 带时间戳的 canonical net equity series；
- 初始权益、基准币种、净值/金额单位和是否 rebased；
- 手续费、滑点、保证金、实现/未实现损益的会计口径 refs；
- session、换月、合约、策略与 RunSpec hashes；
- 缺口、非交易时段、强平/资金流等影响曲线解释的事件 refs；
- 与摘要指标（总收益、年化收益、波动、Sharpe、最大回撤）的确定性 reconciliation。

如能力允许，可附 gross equity、benchmark、drawdown 和 exposure series；但不能用它们
替代 canonical net equity。只计算 IC、分组单调性等而未形成交易组合的 Trial 不伪造
equity curve，应输出相应统计表/图并标记 `not_applicable`。

### 性能与存储边界

- 回测热循环只维护本来就需要的会计状态/series，不调用绘图库；
- Job 结束后由 artifact renderer 在冷路径确定性生成 SVG/PNG（并预留 PDF 报告接口）；
- 完整 series 存 artifact store，trace/数据库只保存摘要、hash、范围和 artifact ref；
- Markdown 报告嵌入静态 equity curve，FTClient 使用同一 ref 展示，并可懒加载完整序列；
- 长序列显示可确定性降采样，但统计指标使用完整序列，图中必须标注降采样；
- 相同 series/render-spec hash 命中缓存，不重复绘图、不重复写数据库。

### Report Requirements 与 Evidence Admission

权威回测节点必须逐条报告：回测范围和会计口径、核心绩效表、equity curve、曲线中的
显著阶段/异常、义务变化和不能据此支持的主张。图表绑定 Evidence/Run/Trial refs，
不是装饰图片。

Evidence Admission 校验 series 身份、时间范围、非有限值、起止权益、摘要指标
reconciliation 和 renderer receipt。缺图但完整 series 尚在时只重建 artifact；缺失
canonical series 或会计无法对账时，相关绩效主张只能 `pending|limited|reference_only`，
并创建具体 CapabilityGap/会计义务，而不把整个研究结果无差别作废。

## Grill 179.30 — 历史 Job 的 Equity Curve 补全边界

**已接受。** 历史研究报告补充 equity curve 时必须保持原始 Evidence 身份：

- 已保存完整 canonical equity series：按原 series hash 和固定 render spec 直接生成图，
  不重跑回测；
- 只保存摘要指标：禁止根据总收益、Sharpe、最大回撤等反推或伪造曲线；
- 原 RunSpec、因子/策略版本、数据 snapshot、规则/会计配置和后端版本均可精确恢复：
  可以登记新的 reproducibility Trial/Job 重跑，但新结果拥有新的 Evidence identity，并
  与旧摘要逐项比较，不能冒充旧 Job 的原曲线；
- 无法精确恢复：报告明确标记“历史曲线不可恢复”，说明缺失对象和影响；旧指标只能
  作为受限历史 Evidence。

FTClient/Markdown 对历史回填沿用相同规则。缺图但 series 在时属于 artifact repair；
缺 series 属于 Evidence limitation 或新的复现 Trial，不通过 UI 插值、截图或兼容层
制造看似完整的历史。

## Grill 179.31 — `data` 小类的统一 Provider Resolver

**已接受并授权后续自行收束。** `data.*` 每个小类按 Grill 179.15/179.26 配置 resolver，
但不为每个数据源复制研究命令。统一 provider adapter 覆盖 server-managed source、
local bundle、user-defined source 和 Tiger；同一 capability contract 提供产品目录、
实时/延迟探测、历史覆盖、Trial 字段交集、FieldHistory、PIT、schema/units、value
quality、universe/survivorship 与 permission/use facts。

批量查询按 source/product/frequency/scope 执行；详细字段/缺口进入 artifact，Agent packet
只返回状态、义务 alias、Evidence refs 和缺口。用户本地数据可在本地形成 Evidence，
不因 resolver 统一而上传源码或数据。

## Grill 179.32 — `DataFreq`、行情深度与既有报告补全

**决定：不让 `DataFreq` 支持 L1/L2。** 现有实现把 `DataFreq` 规范化为
`pd.Timedelta`，用于表达 bar/window/signal 的时间步长。L1/L2 表达行情内容和深度，
与一分钟、逐笔或事件驱动正交。把两者合并会破坏频率比较、窗口运算、索引语义和
Pylance contract。

后继 availability/result schema 至少拆分：

```text
sampling_mode: bar | event | snapshot
frequency: DataFreq | null
data_kind: ohlcv_bar | trade | quote | order_book
market_depth: not_applicable | l1 | l2 | full_depth
delivery_mode: historical_snapshot | live_stream | delayed_stream
latency/provenance/coverage: ...
```

当前 `sources/Tiger/connector.py` 在 L2 live entry 中写入 `"frequency": "L2"` 是已确认
语义缺陷。实现批次应迁移为真实 sampling/content/depth 字段并更新 tests；不得扩展
`DataFreq("L2")` 兼容该错误。冻结旧 Graph/Evidence 仍由版本读取器解释，新的正式
Evidence 只接受新 schema。

### 既有研究报告不通过“直接升级图并补初始义务”重写历史

补全分成两个独立、可审计的操作：

1. **历史报告投影迁移**：保持原 Graph、trace、Work Package、节点顺序和 Evidence
   identity；从既有 trace/artifacts/义务/Trial/Job 确定性重建逐条中文章节、表格、
   chips 和可恢复图表。事实不存在时明确写“历史记录未捕获/不可恢复”，不得补造；
2. **显式 Graph continuation**：新 Graph 发布不会迁移正在运行的研究。只有用户在 UI
   或对话中明确要求某 Work Package 切换时，程序才从原节点进入同名节点的系统自环，
   保留全部旧 Evidence，并计算 requirement/report/profile/capability delta。

Continuation 不批量添加“所有初始义务”。程序只选择当前 scope、当前节点 entrypoint
和目标边中新加或修订的小类；Research Agent 将它们映射到已有本地义务，必要时才
重开、修订或新建具体义务，并执行一次受变化范围限制的 first-principles discovery。
未受影响的旧义务和已验证 Evidence 直接复用。

若新增 Report Requirement 只是缺少表达形式，而事实已在旧 Evidence 中，迁移器直接
生成报告条目；若它暴露出真正未验证的研究问题，才绑定对应真实义务小类并在 re-entry
中处理。缺少报告本身仍是 gate/report error，不创建 `report_coverage` 伪义务。

因此 MaxA/SgCCS 应继续保持同一 Work Package：先把旧历史按原事实补成完整连续报告；
用户明确 continuation 后再增加一段视觉上独立的 Graph 升级审计，列出新要求、义务
映射、复用证据、未满足项和返回原节点的结果，不重复经过 capability/data/factor
semantics 节点，也不生成第二个研究。

## Grill 179.33 — `factor_semantics` 小类与现有 CLI/后端能力映射

**决定：采用七个稳定小类，并复用已有 source-free revision identity。** 因子语义审查
不重复 `hypothesis_validity` 的市场因果机制：前者解释表达式实际算了什么、何时可见、
符号/单位/参数/派生关系；后者解释为什么市场参与者或风险机制可能使其有效。

| 小类 | CLI 必须提供 | 当前能力与缺口 |
|---|---|---|
| `observable_meaning_and_direction` | 原式 LaTeX、逐层自然语言结构、输入量、输出方向/尺度；Agent 报告经济可观测含义 | 已有 `to_latex`/tree；缺统一中文结构投影和符号/尺度 contract |
| `expression_validity` | 算子树、operator registry、arity/type/shape、源码与后端树一致性、revision hashes | workspace inspect/source checks/revision manifest 已部分具备 |
| `numerical_domain_and_units` | 除零、log/sqrt 域、NaN/inf、单位相容、rank/zscore/clip 等尺度变化及有界样本诊断 | 缺完整 operator domain/unit metadata 与 resolver |
| `causal_timing` | 每个 ColumnRef 的可见时点、lookback、rolling/session 边界、source/signal freq 和最终 SignalAlign | 已有 timing capability 名称和部分运行语义；缺逐节点 timing proof |
| `expression_parameterization` | 输出完整表达式树、稳定 node/path、子表达式 LaTeX、类型/单位/时序 metadata 和现有参数 schema；不替 Agent 标注“候选” | 现有 `fixed_column_refs()` 只有去重列名；需补全部子表达式 inventory 与所选节点的 binding audit |
| `derived_comparability` | 父/子家族 lineage、表达式/参数/schema diff、父因子作为子家族特例的映射、旧 Evidence 适用参数 | revision manifests 已有 identity；缺 lineage/diff/comparison-obligation resolver |
| `conditional_factor_role` | 区分 raw-expression 条件化/丰富化与 strategy-level gating，列出辅助因子依赖、对齐及缓存身份 | FactorParam/表达式能力部分存在；缺统一角色与依赖投影 |

`workspace inspect` 继续处理用户工作区源码；server source-free manifest 处理正式 RunSpec
identity。两者不能互相替代：本地 Agent 可审查源码，服务器不保存源码时仍可用表达式
hash、tree/LaTeX、ColumnRefs 和参数 contract 验证执行身份。

每个 resolver 均生成中文 Report Item：原/新 LaTeX、逐项含义、发现的问题、为何修订或
不修订、派生预期、实际 Evidence 限制和新增比较义务。CLI 只提供结构事实与候选；经济
含义、参数化合理性和派生机制由 Research Agent 作有证据引用的判断。

缺失通用算子、operator metadata、timing proof、expression diff 或正式因子修订能力时，
CLI 创建精确 CapabilityGap/MaintenanceTask，由 Server Agent 在稳定语义 owner 下补足；
不得把一次研究专用脚本登记为通用后端能力。

## Grill 179.34 — 参数化对象由 Agent 选择，不限于 ColumnRef

**已接受用户纠正。** Requirement ID 从 `column_parameterization` 修订为
`expression_parameterization`。CLI 不推断或排序“参数化候选”，只忠实返回可定位的
完整表达式结构：稳定 node/path、operator、children、子表达式 LaTeX、ColumnRefs、
类型/shape、单位/尺度、timing/lookback 和现有参数 bindings。

Research Agent 必须阅读原公式并自行回答：

- 该节点/子表达式在当前产品和市场中的经济含义；
- 为什么固定它可能造成语义过窄、为什么参数化可能有研究价值；
- 哪个精确 node/path 应参数化；
- 原表达式作为默认参数值时，父因子是否仍是新家族的严格特例；
- 参数空间如何受机制约束，避免把任意搜索空间伪装成参数化；
- 需要建立哪些父/子版本比较和 selection-ledger 义务。

参数化对象可以是：

- 单个 `ColumnRef`，通常可绑定 `DataColumnParam`；
- `H-L`、价差、比值、rolling、rank、z-score 等任意 FactorExpr 子树；
- 一个已有因子/因子家族的表达式；
- 必要时整个原始表达式，作为派生家族的默认 `FactorParam`。

当前 `FactorParam` 的 Python contract 接受任意 `FactorExpr`，但正式支持必须同时通过
源码/SDK、参数 metadata、UI/CLI transport、RunSpec freeze、worker resolution、缓存
identity、回测执行和报告 round-trip。CLI 在 Agent 选定 node/path 后运行 binding audit，
返回：

```text
DataColumnParam | FactorParam(family ref) | FactorParam(inline expr)
| new generic parameter capability required | semantically invalid
```

其中最后的 `semantically invalid` 只能来自可证明的类型/时序/递归依赖冲突，不替代
Agent 的经济学判断。任一端到端环节缺失即创建 CapabilityGap，由 Server Agent 补齐；
不得因为当前 transport 只方便传 factor alias 就剥夺复合子表达式参数化能力。

报告必须展示原式、选中的子表达式、新式 LaTeX、参数默认值、父式特例证明、经济动机、
预期变化以及新建的比较/多重选择义务。

## Grill 179.35 — `trial_design_validity` 小类的 CLI resolver 与 TrialPlan 缺口

**决定：沿用 Grill 179.3 的十二个设计问题小类；CLI 从 TrialPlan、RunSpec、数据
Evidence 和 Trial ledger 确定性派生事实，Agent 解释其是否足以处理具体义务。** 不把
这些详情全部塞入 4096-byte TrialPlan；详细比较矩阵/覆盖矩阵是 hash-addressed artifact，
TrialPlan 只保留不可缺少的身份、角色、refs 和冻结设计声明。

| 小类 | CLI resolver 必须验证/生成 | 当前能力与缺口 |
|---|---|---|
| `target_contrast` | 一个 primary obligation、目标 estimand/outcome、目标 Run 与对照关系 | 现有 `obligation_refs/outcomes/comparisons` 部分具备；缺 primary/secondary 明确绑定 |
| `baseline_relevance` | baseline 类型、为什么能回答当前问题、不可比较差异 | comparison 只有 RunSpec hash/role，缺 baseline 语义 |
| `controlled_variable_isolation` | 两个 RunSpec 的 canonical semantic diff、允许变化维度、意外共同变化 | 缺通用 semantic-diff resolver |
| `population_and_universe` | 产品总体、纳入/排除规则、历史成员、存续和目标外推范围 | 现有 universe hash 不足；需连接 data/universe Evidence |
| `information_partition` | 每个样本可见信息、冻结/开放时点、研究访问 ledger | sample roles 已有；缺 access/freeze proof |
| `sequential_holdout` | 根据可得数据和目标决定递进阶段、最新保留段及开放条件，不硬编码年份/比例 | v4 stage policy 角色硬编码且表达力不足 |
| `regime_control_and_coverage` | 市场环境定义、时间覆盖、作为控制/分层/外推检查的用途 | 缺 regime descriptor/coverage resolver；不能事后只挑有利阶段 |
| `instrument_control_and_coverage` | 标的分层、交集/并集、跨标的验证与外推边界 | sample identity 只有整体 universe hash，缺 overlap/coverage matrix |
| `temporal_overlap_and_gap` | 样本交叠、purge/embargo、lookback、持有期、标签窗口和 session 边界 | 已有起止范围；缺有效暴露窗口检查 |
| `replication_structure` | 独立重复、seed/block/period/venue replication 结构及身份 | TrialPlan 尚无正式 replication binding |
| `adaptation_and_ledger` | 参数、派生家族、辅助因子、方法、市场/时段选择和 holdout 访问的完整增量 ledger | multiplicity 声明存在，但缺对实际研究事件的完备性核对 |
| `stop_and_reopen_rule` | 固定样本/预算/信息增益停止条件、失败/冲突/新 Evidence/Graph 更新时的重开条件 | stopping/criteria refs 部分具备；缺机器可执行 reopen predicates |

### TrialPlan 后继 schema 的最小调整

不新建一套重复的 TrialDesign 数据库对象。后继 TrialPlan 只补：

- `primary_obligation_ref` 与有界 `secondary_obligation_refs`；
- comparison 中的 `target_ref`、`baseline_ref`、`allowed_difference_refs`；
- sample/stage 的稳定 stage ID 与 semantic role 分离，允许递进、多次 validation 和最终
  latest holdout，而不是依赖固定 `STAGE_RANK`；
- `design_evidence_refs`：引用 partition、overlap、regime、instrument 和 replication
  resolver artifacts；
- `trial_ledger_ref` 与 `holdout_access_ledger_ref`；
- `stop_rule_ref`、`reopen_predicate_refs`。

现有 outcomes、RunSpec hashes、sample hashes、parent TrialPlan lineage 和 content hash
继续保留。大矩阵、自然语言理由、完整义务正文和统计结果不进入 TrialPlan。

### CLI 与报告行为

CLI 提供一次批量 `design inspect/freeze/compare/admit` 语义：

1. `inspect` 投影十二小类、已有 Evidence 和缺口；
2. `compare` 生成 RunSpec semantic diff、partition/overlap/coverage artifacts；
3. `freeze` 校验 Agent 选择与义务映射，冻结 TrialPlan/hash/ledger refs；
4. `admit` 在 Job 提交前和 Evidence Admission 时核对实际执行是否遵循冻结设计。

每个小类必须逐条中文报告“选择了什么、为什么、用什么事实、仍有什么限制”。同一
fingerprint 的设计验证直接引用；新增因子版本、参数、市场、时段或方法必须进入 ledger，
不得因沿用同一 TrialPlan 名称而逃避 multiplicity/adaptation 记录。

缺少 overlap、regime、ledger 或 holdout access 能力时形成 CapabilityGap；如果只是数据
不足，则保留相应真实 `data`/设计义务并不生成不可执行 TrialPlan。

## Grill 179.36 — `hypothesis_validity` 的 resolver 只组织事实与可证伪结构

**决定：保留 Grill 179.16 的六个核心小类和七个条件机制族；不建立统一的“经济意义
通过”判定。** CLI 验证假设是否结构完整、事实/来源是否可追溯、预测是否可证伪，
Research Agent 根据第一性原理和证据建立/修订具体义务。机制写得完整不等于机制已被
验证；回测表现好也不能解除机制义务。

### 六个核心小类

| 小类 | CLI resolver 必须提供/验证 |
|---|---|
| `mechanism_chain` | 提供结构模板并验证完整链条：事实/冲击 → 参与者激励与约束 → 行为/订单需求 → 价格形成 → 预期方向/期限；每一环绑定 fact/literature/profile refs，Agent 填写语义 |
| `observable_proxy` | 合并 factor expression node/path、ColumnRefs/params、数据字段定义与可见时点；Agent 映射每个代理对应机制哪一环、测量误差和失真条件 |
| `falsifiable_predictions` | 校验预测包含方向、期限、产品/参与者/环境差异、反例和可观测量；查询数据/CLI 能否验证，不能时保留 open/unknown |
| `alternative_explanations` | 投影已知因子/策略暴露、carry/趋势/流动性、数据/执行伪影、选择 ledger 和既有反例；Agent 必须开放式补充，不把目录当穷尽集合 |
| `boundary_conditions` | 从 Product-Market Profile、regime/instrument/data coverage 形成边界矩阵；Agent 声明成立/失效预期及 Claim 外推范围 |
| `derived_incremental_mechanism` | 使用 factor lineage/expression diff，逐项说明新增子表达式/参数改变机制哪一环、父式特例、预期增量和父子比较义务 |

Mechanism chain、proxy mapping、prediction 和 alternative explanation 是 hypothesis/report
artifacts，不因为 CLI 验证 schema 成功就成为支持 Claim 的经验 Evidence；其中引用的
市场事实、数据测量和文献 snapshot 可分别进入 EvidenceEnvelope。

### 七个条件机制族

| 小类 | CLI resolver 的事实边界 |
|---|---|
| `participant_incentives` | Product-Market Profile 的参与者/账户/披露定义、激励/约束 ontology、可用持仓/成交代理及分类变更；不自动把“主力/游资/商业/投机”当结论 |
| `behavioral_channel` | 按需加载获准的文献研究能力，返回理论机制、可证伪预测、适用市场/期限和反例；Agent 选择与当前主体相符的渠道 |
| `risk_transfer_and_compensation` | 套保风险、持仓分类、库存/波动/资金约束、风险承接者和可用 proxy inventory；缺代理不否定机制，只限制可检验性 |
| `information_diffusion` | 信息事件、发布时间/可见时点、跨市场/合约 lead-lag、覆盖与同步能力；Agent 解释为何扩散不即时及替代解释 |
| `liquidity_inventory_and_impact` | L1/L2/成交/订单流 availability、spread/depth/turnover/impact/inventory proxy；区分临时冲击、逆向选择和长期信息 |
| `fundamental_supply_demand_and_carry` | 库存、产消、季节、仓储、融资、便利收益、基差/曲线和发布日期/PIT inventory；不以价格曲线单独证明基本面机制 |
| `institutional_and_contract_rules` | 按产品、司法辖区、venue、effective period 查询规则 profile/FieldHistory；生成可能结构断点和待验证预测，不把当前规则倒填历史 |

文学/网络检索不是每次节点固定调用。只有当前机制缺少必要理论或市场事实时，Agent 才
按 skill description 加载已授权研究 Skill；CLI 将来源、版本、query/as-of、摘要和
适用范围封装为 Evidence snapshot。相同 fingerprint 直接复用。

### CLI 操作与报告

统一服务提供 `inspect / draft / validate / compare / bind` 语义：

1. `inspect` 批量投影 expression、profile、数据代理、既有文献/Evidence 和历史义务；
2. `draft` 给 Agent 紧凑模板，不自动生成机制结论；
3. `validate` 检查链条完整性、预测可证伪性、refs、边界和反故事化字段；
4. `compare` 比较父/派生假设、替代解释或不同机制预测；
5. `bind` 把 Agent 审定的具体假设义务、预测和首个 resolution action 绑定到 Work
   Package/Trial family。

报告逐条展示：公式/代理映射、机制链表、参与者—激励—约束—行动表、预测/反例表、
替代解释、边界矩阵、派生增量和未解决义务。每条绑定 requirement/obligation/fact/
literature/Trial refs；长文献和数据 artifacts 懒加载，不塞入 Agent packet。

后端缺 participant/profile、event-time、position/inventory、microstructure、fundamental
或 literature-receipt resolver 时创建精确 CapabilityGap；没有数据时仍创建机制义务，
但不能生成声称可执行的经验 Trial。

## Grill 179.37 — 行业依据登记、义务小类描述与研究报告引用

**已接受并立即补记。** 行业依据的 canonical 文档索引使用既有
[`evidence-registry.md`](evidence-registry.md)，本轮新增 NIST DOE、ICH E9(R1)、Bailey
回测过拟合、行为/信息扩散、流动性/库存、套保成本/压力和 CFTC 参与者定义。该 registry
是 Grill/设计证据索引，不进入 routine Agent context；发布时由 commit/hash 固定。

### Requirement subcategory contract 必含行业语义

每个义务小类除 Grill 179.18 字段外，增加：

```json
{
  "industry_principle_zh": "该小类要求研究者考虑的稳定行业/统计原则",
  "industry_basis_refs": ["S-BACKTEST-OVERFIT"],
  "basis_propositions_zh": ["该来源实际支持的有限命题"],
  "transfer_limits_zh": ["产品、地区、频率、数据或方法的外推限制"],
  "not_implied_zh": ["引用该来源仍不能推出的结论"],
  "further_research_hints_zh": ["何种新证据可能深化或修订本小类"],
  "basis_revision": 1
}
```

Graph/Requirement Catalog 保存 refs 和短原则，不保存论文正文。CLI 默认只向 Agent 返回
命中的 source alias、一句话命题和 transfer limits；Agent 需要核对机制、反例或方法时
才通过 ref 懒加载 registry record、摘要或原文。

### Research Agent 必须把实际使用的行业依据写入报告

适用小类的 Report Requirement 要求 Agent 逐条说明：

1. 使用了哪项行业/统计原则和 canonical source ref；
2. 为什么它与当前因子、产品、venue、市场环境和 Trial 问题相关；
3. 当前采用了行业方法的哪些部分，偏离/无法采用哪些部分；
4. 该依据只支持什么研究设计或机制合理性，不能支持什么当前 Claim；
5. 当前研究的哪些 Evidence 是独立实证事实，而不是文献陈述；
6. 哪些冲突、外推限制或新资料仍需后续深化。

报告渲染把二者分开：

- **行业依据/方法依据**：引用论文、官方规则或标准，说明选择设计/机制的理由；
- **本研究 Evidence**：当前数据、Trial、回测和 CLI 测量，负责改变具体义务/Claim。

行业依据不能因为出现在报告中被计算成第二份实证 Evidence，也不能用“符合行业惯例”
替代具体适用性论证。未实际使用的文献不批量罗列；selector 触发但 Agent 判断不适用时，
也要报告不适用理由和 transfer limit。

### 可持续深化与重开规则

Literature/Standards Registry 可以独立增加来源、反例、复制研究、产品/地区证据和来源
版本，不需要每次修改 Graph topology：

- 只增加佐证/阅读材料，不改变小类问题或判定标准：更新 registry revision/cache，旧
  研究不自动重开；
- 改变了 industry principle、selector、expected evidence 或 `not_sufficient`：提出
  Requirement revision/MaintenanceTask，发布后由 Graph continuation 只重审受影响义务；
- 新论文/规则直接反驳当前机制或改变产品事实：作为新 Evidence/Market Profile
  revision，匹配的 branch-local 义务可重开，但不自动新增图边。

Source record 后续应补作者、题名、venue、DOI/canonical URL、发表/生效日期、访问日期、
source type、支持命题、限制、反例/复制研究 refs 和内容 hash。当前登记是首版 seed，
明确允许后续行业调研深化。

## Grill 179.38 — 策略设计与市场执行/会计的 resolver 和报告边界

**决定：保留 Grill 179.5 的两个大类，但不把它们变成每次因子研究的固定
步骤。** 只有 Trial 需要把信号变成交易结果时才触发；纯表达式语义、数据检查或
IC 诊断不得提前解析这些能力。CLI 负责投影事实、预览时序、比较 RunSpec 和
校验引擎支持范围；Research Agent 负责选择策略、解释适用性和设计受控 Trial。

### `strategy_design` 小类与 CLI resolver

| 小类 | CLI resolver 必须提供/验证 | 当前后端与缺口 |
|---|---|---|
| `signal_schedule` | 从 factor/RunSpec 投影计算频率、`$F`/signal frequency、basepoint、信号可见、生效、可下单和成交时点；输出小样本 event timeline 及因果时序警告 | `FactorSignalModule` 已有 precomputed/incremental、signal alignment 和 next-bar 事件；缺统一紧凑的 schedule preview/diff/receipt |
| `strategy_conditioning` | 列出主/辅助信号、可见时点、对齐方式、gate/size/rebalance/exit 决策表，校验缓存与身份 | 现有后端有若干固定 signal/group/target 流，但没有通用、可审计的条件策略 contract/resolver；应按实际语义补 Capability，不将辅助信号暗中塞回因子表达式 |
| `position_and_rebalance` | 投影 signal→selection→target→order 链，展示方向、allocation、position policy、rebalance trigger、rounding、exit/risk 规则；输出受控 semantic diff 和小样本状态转移 | 已有 `rebalance_to_target/buy_and_hold`、`on_factor_signal/membership_change`、equal-notional/inverse-vol/equal-margin 和 lot rounding；纯 calendar `scheduled` 尚未实现，策略 catalog 与 diff resolver 不完整 |
| `session_policy` | 使用市场 session facts 预览哪些信号被跳过/延后、下一交易时点、是否跨 session 保留；比较时只改 session-policy 维度 | `end_session_skip/end_session_gap` 已进入 signal alignment，但 `end_session_skip` 当前字段和多个 runtime fallback 默认为 `True`；这是会改变结果的策略变量，不得当成无害默认或市场规则 |

`end_session_skip` 的后端默认必须统一为 `False`：FactorFamily 生成、
`SignalAlign` 类/函数、FactorSignalModule 字段和所有 runtime fallback 不得分裂。
显式 `True` 仍保留为可研究策略，并用回归测试保证原语义不被删除。旧模板/
RunSpec 若已显式冻结 `True`，仍按冻结值运行，不因新默认被静默改写。
当前 SgCCS 研究不得使用 `True` 作为未审计默认；如要研究其效果，必须
建立策略义务并做其他维度固定的对照 Trial。

### `market_execution_accounting` 小类与 CLI resolver

| 小类 | CLI resolver 必须提供/验证 | 当前后端与缺口 |
|---|---|---|
| `session_calendar` | 按 product/venue/jurisdiction/effective period 返回版本化 session、trading-day mapping、夜盘、休市/假日和临时变更；对拟定 schedule 生成 coverage/ambiguity artifact | `DataIndex` 和 `MarketDataModule` 能保留 trading-day/session 索引并从数据推断收盘；缺统一的 point-in-time official calendar/profile resolver，不能仅从已观测 bar 反推规则完整性 |
| `contract_lifecycle` | 投影上市、最后交易、交割/强平、候选合约、roll policy 和合约切换 timeline；校验每个时点的可交易合约 | `TermStructureExpand/DeliveryForceClose/RolloverModule` 已有 lifecycle metadata 和 date-before-expiry；仅支持 `none/date_before_expiry`，需要明确数据/规则来源和策略选择的分界 |
| `order_and_fill` | 列出 order type、execution basis/delay、matching、交易限制、volume/depth capacity、slippage；用小样本 order trace 验证开口到成交/拒单的每步 | 原生引擎已有 next-bar open、market/limit 声明、full-fill/bar-volume-limited、交易约束、fixed-bps 和 capacity 流；价格 basis 实际固定为 open，限价/L2 真实撮合范围需 capability matrix，不得只看 UI option |
| `cost_margin_and_settlement` | 按时点投影手续费 leg、合约乘数、保证金、抵押/追缴/强平、结算价、每日盯市和 cash ledger；校验 FieldHistory/profile 来源与引擎 receipt | 原生引擎支持 exchange/OpenCTP 费用、historical/custom/fixed margin、margin call、settlement/pre-settlement 和 daily MTM；外部 framework worker 只支持 fixed/zero fee/margin 并会拒绝无法表达的历史规则，这个限制必须保留在 binding/receipt |
| `backtest_live_consistency` | 对 historical/native、external worker、simulation、delayed stream 和 live 建立按语义维度的 support matrix；对可比范围生成 shadow/differential artifact | 已有 native/worker equity/position curve 一致性测试，但不等于延迟流或真实交易的一致性；需要 connector capability receipt、clock/order/accounting 差异表和有界 Claim |

### 统一 CLI 与报告约束

CLI 对两类提供统一 `inspect / preview / compare / bind / attest` 语义，具体
resolver 按上述小类分模块实现，不把所有交易逻辑继续堆入一个 CLI 文件：

1. `inspect` 返回当前显式设定、默认来源、引擎 binding 和已有 Evidence refs；
2. `preview` 生成紧凑 schedule/order/lifecycle/accounting 样本和 artifact ref，不返回整段日志；
3. `compare` 只显示受控的 semantic diff，防止 session policy 与因子/数据/成本一起变；
4. `bind` 把审定设置和 profile/rule versions 冻结进 RunSpec/TrialPlan refs；
5. `attest` 在 Evidence Admission Gate 核对实际 job receipt 与冻结设计，发现不一致时路由真实义务或 CapabilityGap。

每个命中小类的须报条目必须独立说明：采用了什么设置/规则版本；为什么
对当前产品、venue、时段和 Trial 适用；哪些变量被固定/比较；CLI artifact 证明了
什么；还有哪些执行、容量或实盘差异。报告展示短表/时序图和有语义 alias
的 chip；完整 order trace、rule snapshot、FieldHistory 和 equity series 通过 ref 懒加载。

行业依据与报告中必须区分：

- `S-HYPOTHETICAL-PERFORMANCE` 只支持“历史/仿真不能自动等同真实成交、流动性、
  保证金和风险条件”，不支持某个固定滑点或容量阈值；
- `S-DOE-NIST` 支持将 session policy、仓位或执行假设做受控比较，不能证明
  因子的经济机制；
- 交易时段、合约生命周期、费用、保证金和结算的直接依据必须是按产品/地区/
  venue/effective period 定位的官方规则或已审计 Product-Market Profile，不得用
  通用论文或当前 UI 默认值代替。

当前能力盘点是一份可演进的 seed；后续新产品、新地区、L2/live connector 或
交易所规则更新时，先更新 profile/source registry 和 capability receipt。只有小类的
问题、选择条件或 Evidence 标准改变时，才修订 Requirement/Graph 并对受影响研究
执行 continuation；不为每份新规则新增图节点。

## Grill 179.39 — 用户验收目标是必须回答的 Contract 义务

**决定：增加 `UserAcceptanceObligation`，但不将它塞入七类 Verification
Obligation Catalog。** 它由用户与 Planning Agent 在 Research Decision Contract 中创建，
回答“研究是否达到用户要求”；Verification Obligations 回答“这个结果能否被可信地
解释”。达到指标不能自动解除机制、数据、设计、统计、策略或市场义务。

### 目标必须先变成可判定 contract

例如“找到一个样本内外 Sharpe > 1.2、最大回撤 < 15% 的因子”不能只存一句
自然语言。Planning Agent 必须与用户确认或根据明确上下文结构化为：

```json
{
  "objective_id": "...",
  "title_zh": "样本内外收益风险目标",
  "subject_scope": {
    "factor_family_refs": [],
    "factor_instance_policy": "one_or_more",
    "product_market_refs": [],
    "strategy_ref": "..."
  },
  "criteria": [
    {"sample_role": "selection_or_validation", "metric": "net_sharpe", "op": ">", "value": 1.2},
    {"sample_role": "selection_or_validation", "metric": "max_drawdown", "op": "<", "value": 0.15},
    {"sample_role": "latest_untouched_or_prospective_holdout", "metric": "net_sharpe", "op": ">", "value": 1.2},
    {"sample_role": "latest_untouched_or_prospective_holdout", "metric": "max_drawdown", "op": "<", "value": 0.15}
  ],
  "metric_definition_refs": [],
  "cost_and_accounting_profile_refs": [],
  "minimum_evidence_qualification": "eligible",
  "completion_policy": "all_criteria",
  "status": "open"
}
```

如用户没有说清“样本内外”是要求两者各自达标、合并达标，还是只要求最终
holdout 达标，Planning Agent 不得自选最容易通过的解释。`net_sharpe` 必须绑定
收益频率、年化、无风险利率/超额收益、净成本和策略 leg；`max_drawdown` 必须绑定
同一权益曲线和币种/会计口径。

### Trial 和结果必须逐项回答

- TrialPlan 声明 `objective_refs` 以及本 Trial 能评估的 `criterion_ids`；数据可用性、
  机制分析等非绩效 Trial 可以声明 `not_evaluated` 及理由，不伪造指标回答。
- 每个相关绩效 Trial 的 EvidenceEnvelope 必须附 `objective_evaluation_delta`，按 criterion
  返回 `satisfied|not_satisfied|indeterminate`、实测值、比较符、sample/stage、metric definition、
  qualification 和 Evidence refs。
- `research_decision` 不从报告文本重新计算；CLI 从已录取 Evidence 确定性投影
  contract 的当前结果，Agent 只解释冲突、限制和下一个 Trial 的信息价值。
- 研究报告必须有“用户目标达成情况”表：每条标准一行，显示口径、范围、
  当前值、状态、Evidence chip 和限制；不用一句“已达标”覆盖多个样本/标的。

### 未满足就不能完成，但不允许无限试错或污染 holdout

Work Package 只有在所有必需 `UserAcceptanceObligation` 满足，且用于判定的 Evidence
达到 contract 要求的 qualification 时，才能标记 `completed_objective_met`。任一标准
`not_satisfied|indeterminate` 时：

1. 必须保持 objective open，不得用 bounded closure 伪装成用户目标已完成；
2. Research Agent 必须准备下一个有信息价值、符合 ledger/holdout 规则的 Trial；
3. 若没有合规的新 Trial、能力/数据不足或资源已耗尽，运行可停止，但 Work
   Package 只能进入 `paused_exhausted_objective_open`，等待新数据、新能力、新资源或用户
   显式修订/放弃目标；不得静默关闭。

最新 untouched/prospective holdout 只在预声明的最终评估时开启。如该 holdout 未达标，
结果必须记录为未满足；Agent 不得反复查看同一 holdout 调参直到通过。后续只能
把它降为已观测的历史/市场环境 Evidence，并等待新的 prospective 数据或用户修订
目标/范围。用户目标越具体，selection/multiplicity ledger 越必须完整；否则“找到达标因子”
只是过度搜索的结果。

### 最小 CLI/持久化，不增加新热路表

CLI 提供 `objective inspect / evaluate / status / revise`：

- `inspect` 校验标准口径和当前 Trial 可评估性；
- `evaluate` 从 Evidence refs 产生紧凑 delta，不加载整份报告/曲线；
- `status` 投影每条 criterion 的最新有效评估和总体状态；
- `revise` 只接受用户对话中明确的目标/阈值/范围修订，保留版本和原评估。

Contract 定义存在既有 Research Decision Contract JSON/version；当前状态和 delta 存在
branch checkpoint/trace，指标表、equity curve 和完整 EvidenceEnvelope 用 artifact refs。不为
Objective 新建一张每 Trial 读写的数据库表。

## Grill 179.40 — 用户目标贯穿现有 Graph，不增加目标节点

**现状审计：当前 v8 的 Graph/Research Cycle 尚没有可执行的
`UserAcceptanceObligation`。** `Research Decision Contract` 只作为 hash/binding 存在，
TrialPlan 绑定 Verification Obligations，closure 只检查 actionable frontier；因此现有实现
可能在 Sharpe/回撤目标未满足时仍形成 bounded closure。实施 v8 时必须补齐，
但不得为此复制 Work Package 或增加一组目标节点。

| 现有节点/门 | 必须增加的确定性行为 | 必报条目 |
|---|---|---|
| Planning / `hypothesis_preregistration` entry | 解析并冻结 objective criteria、指标口径、样本角色、产品/策略范围和 completion policy；有重大歧义时向用户确认 | 用户原始目标、结构化解释、仍有的歧义与版本 |
| `hypothesis_preregistration` | 目标 ref 与假设/因子范围绑定；不把阈值写成机制预测 | 目标与经济假设的关系以及不能推出的结论 |
| `validation_design` entry | 当前 Trial 声明能评估哪些 criterion，所需数据/策略/市场/统计义务是否已处置 | 本 Trial 回答/不回答的目标项及原因 |
| `validation_design` | TrialPlan 冻结 `objective_refs/criterion_ids`、metric/sample refs 和 selection/holdout ledger | 指标评估设计、控制变量、空间和停止/开启条件 |
| `cheap_factor_diagnostics` | 只有诊断本身就是 criterion 才评估；Sharpe/回撤不得从 IC 结果推断 | 可评估项的结果，其余明确 `not_evaluated` |
| `authoritative_backtest` | JobAttempt 绑定 objective/criterion refs，生成净权益曲线和冻结口径的 metrics | 运行范围、成本/会计、目标指标表和 equity-curve artifact |
| Evidence Admission Gate / `job_evidence_ready` | 验证指标来自正确 Trial/Run/sample/equity series，且 qualification 达到 criterion 要求 | 每个 criterion 的 evidence identity、qualification 和不可判定原因 |
| `statistical_robustness` | 评估不确定性、selection/multiplicity 和退化；不修改用户阈值 | 点估计与不确定性、选择影响、阈值只能/不能回答什么 |
| `result_audit` | 将 admitted Evidence 转为每 criterion 的 evaluation delta，并与 Verification Obligation delta 分开 | 用户目标表、义务/Claim 变化、冲突和限制 |
| `factor_improvement_required` | 允许目标驱动新因子/参数/策略候选，但必须记入 adaptation ledger 且禁止重用已开启 holdout 作选择 | 为何这一改进有新的可证伪机制/信息价值，而不是只追阈值 |
| `research_decision` | 聚合当前 objective status；有未满足必需项时拒绝 `completed_objective_met`，优先合规新 Trial，无可行路径时仅允许 open pause | 已满足、未满足、不可判定项；下一 Trial 或 pause 原因 |
| Graph continuation/re-entry | 新 objective revision 只重审相关 criteria/Trial/report requirements；原 Evidence 保留 | 修订 diff、受影响项、沿用 Evidence 和重开原因 |

### 必要 guard 修订

- `hypothesis__capability_resolution` 除现有假设/义务 discovery 外，要求
  `user_objectives_frozen_or_explicitly_none=true`；
- `validation_design__cheap_diagnostics` 要求当前 Trial 的 criterion binding 完整；
- `backtest__job_evidence_ready` 要求预声明 objective metrics/series 产物已保留，但不要求指标已达标；
- `result_audit__research_decision` 要求 applicable criterion deltas 已生成；
- Work Package completion guard 要求所有 required objectives 均为 `satisfied`；
- search exhaustion 不再等于 completion；目标未满足时只能产生
  `paused_exhausted_objective_open`。

Objective evaluation 和 Verification Obligation adjudication 可在同一次服务调用/事务中
批量写入 trace，但使用不同的 delta 字段和状态机；UI 可在同一报告阶段
展示两张表。这样不增加 Graph topology、不新建热路表，也不把研究可信性和
用户业务目标混为同一件事。

## Grill 179.41 — 方法型节点与“按义务选方法”的冲突

**决定：接受推荐方案。** 当前 v8 实际定义存在两个过度固定方法的节点：

- `cheap_factor_diagnostics` 无条件要求 cross-sectional IC 和 quantile
  monotonicity；
- `statistical_robustness` 无条件要求 bootstrap Sharpe。

这与 Grill 179.4 已接受的原则冲突：Graph 应要求 Research Agent 说明
estimand、依赖结构、不确定性、selection/multiplicity、方法前提和反证，
而 IC、分组单调性、bootstrap Sharpe 只是当前义务和 Claim 需要时才绑定的
方法。否则：

1. 时序因子、条件策略、执行问题或非 Sharpe estimand 会被强迫跑不适用方法；
2. 方法不适用会被误报为 CapabilityGap；
3. 新统计 Skill/后端方法难以按义务动态加入；
4. Agent 为经过固定节点而制造无意义 Trial，增加 token、Job 和数据库读写。

**用户纠正：不接受“为了 continuation 保留旧 node ID”的增量补丁思路。**
应先按业务语义重新编排整体节点，允许删除、合并或替换方法型节点；再对每个现有
Work Package 做 continuation eligibility 检查。不能为了使旧研究能切换而在新图中
保留空节点。

方法节点的业务重编方向仍然是：

- `cheap_factor_diagnostics` 的稳定语义改为“优先取得能低成本缩小当前义务或
  反驳当前候选的 Evidence”；
- `statistical_robustness` 的稳定语义改为“使用与已冻结 estimand、设计和依赖结构
  相符的方法评估不确定性、选择影响和敏感性”；
- 删除两节点中 IC、分组单调性、bootstrap Sharpe 的无条件 capability binding；
- Requirement selector/TrialPlan 声明需要的 method capabilities，确定性 registry 只解析
  当前命中方法；
- 若没有任何有信息价值的低成本诊断，Graph 可依据 TrialPlan/guard 跳过
  `cheap_factor_diagnostics`，但报告跳过原因；
- 不因旧 node ID 存在就默认保留；只有新业务模型仍需要相同状态时才保留。

这不改变既有 IC/分组单调性/bootstrap 的可用性；它们仍是 FactorTester
的已有 capability，只是不再因节点名称而必然运行。

## Grill 179.42 — 撤回在旧拓扑上增加跳过边的提案

**状态：撤回，不实施。** v8 当前只有
`validation_design__cheap_diagnostics__authoritative_backtest` 路径，没有从
`validation_design` 直接进入 `authoritative_backtest` 的边。Grill 179.41 允许
“没有信息价值的低成本诊断时跳过”后，必须明确这一转移怎样发生。

~~原推荐是后继 Graph 新增一条显式普通边
`validation_design__authoritative_backtest`，而不进入空的 diagnostics 节点再立即离开。
该边只在以下确定性 guard 均满足时候选：~~

```json
{
  "selection_and_trial_plan_frozen": true,
  "actionable_obligations_planned_or_bounded": true,
  "authoritative_execution_required": true,
  "applicable_low_cost_diagnostic_count": 0,
  "diagnostic_skip_adjudicated": true,
  "current_trial_stage_executable": true
}
```

`applicable_low_cost_diagnostic_count` 由 Requirement/Method selector 计算，不由 Agent 为了
少做工作自由填零。`diagnostic_skip_adjudicated` 要求 Research Agent 报告：

- 已检查哪些低成本候选方法；
- 为什么它们不适用或不会对当前义务提供信息；
- 为什么权威回测是当前最小可行 Evidence 动作；
- 回测之前仍未解决的义务和限制。

~~该边绑定 `trial_design_validity.target_contrast`、
`trial_design_validity.controlled_variable_isolation` 以及当前 Trial 命中的
`strategy_design.*` / `market_execution_accounting.*`，并用
`explain_transition` 报告跳过理由。这是研究选择，不是系统隐式近道，
因此不应实现为不可见的 system transition。~~

撤回原因：在尚未重新编排“Trial 设计—执行—Evidence admission—裁决”完整
业务状态前，直接增加一条边会把旧拓扑固化。上述 guard/report 要求仍可作为
新拓扑的语义输入，但不预设节点名和边。

## Grill 179.43 — 方法型节点的实际 continuation 影响盘点

**数据库只读盘点，时点 2026-07-22：**

- Active Graph 是 `factor-research@v8`；
- v8 当前研究的现行 incarnation 分别在 `factor_semantics` 和
  `hypothesis_preregistration`；
- 它们所在 Work Package 的旧 incarnation trace 也没有经过
  `cheap_factor_diagnostics`、`statistical_robustness` 或 `authoritative_backtest`；
- 另有 4 个 v4/v5 现行研究停在 `cheap_factor_diagnostics`；
- 没有现行研究停在 `statistical_robustness` 或 `authoritative_backtest`；
- 历史 trace 中有 6 次 `validation_design→cheap_factor_diagnostics` 和 2 次
  `cheap_factor_diagnostics→authoritative_backtest`。

因此，若后继 Graph 经业务重编删除这些方法型节点：

1. 当前 v8 的两个 Work Package 可继续进入 topology compatibility 审计；
2. 那 4 个当前停在 `cheap_factor_diagnostics` 的旧研究不得切换，继续 pin 在
   原 Graph；
3. 任何后续在源 Graph 进入被删节点的研究，同样不得切换；
4. activation 只发布新默认 Graph，不强制迁移 pinned Work Package。

Continuation eligibility 必须由程序使用 source/target Graph 和 branch trace 一次计算，
不由 Agent 自行判断或逐节点查库。按用户的严格要求，“接触过被删节点”
包括同一 Work Package 所有 incarnation 的历史 trace，不只是当前 node。任一历史
node/edge 在 target Graph 中被删除或无审计的语义对应时，该 Work Package 不得切换，
而是继续 pin 在原 Graph。日后若需更宽松迁移，必须另行审计显式的 historical
transition mapping，不改这个默认。

## Grill 179.44 — 旧验收研究未删除与 Work Package 生命周期缺失

**实际数据库结论：** UI 看不到的 4 个 cheap-diagnostics 研究没有被删除。
它们属于旧 owner `default$MaxA@1` 下的两个 workspace：

- `Issue140 Graph v4 SgCCS acceptance`；
- `Issue140 Graph v4 TrDualMomentum acceptance`。

两个 `research_workspaces.deleted_at` 均为 NULL。它们合计包含 12 个 Graph incarnation、
多个 Work Package/trace 和 11 条 acceptance run。四个当前停在
`cheap_factor_diagnostics` 的 Work Package 本身没有绑定 Run/Job，但不能只删这四行
而遗留同 workspace 的其他验收对象。

### 为什么 UI 看不到

`ProfileResearchProjection` 现在以“当前 authenticated owner + 指定 workspace”作精确
过滤。旧实例的 owner 是 `default$MaxA@1`，而当前服务器用户是 `18717974771`，
且旧实例的 `created_by_profile_ref/current_owner_profile_ref` 为空。因此它们被权限投影
隔离，而不是 archived/deleted。“查不到”不得被 UI 解释为“已删除”。

### 必须增加的生命周期

**用户已接受。**

研究 Work Package 增加明确状态，不复用 branch `running/paused` 或 workspace
`deleted_at`：

```text
active → archived → deleted
  ↑         ↓       ↓
  └─ restore ─┘   restore
```

- `active`：默认研究列表，允许常规继续/交接；
- `archived`：从默认列表移除，保留全部报告/Evidence/Job/trace，可恢复；
- `deleted`：进入“最近删除”，不参与运行、continuation 或普通检索，但在清理前
  可恢复；
- permanent purge：不是普通“删除”按钮的同义词，必须做引用图/产物/文件预检
  和事务性删除，不得只删 Graph branch 行。

Archive/delete/restore 是用户数据管理，不是 Graph 节点、义务或审批流。不修改
Graph topology，但 continuation guard 必须拒绝 `archived/deleted` Work Package。

### CLI/API/UI 一致性

FactorTester CLI 必须先提供：

- `research list --state active|archived|deleted|all`；
- `research archive <work-package-ref>`；
- `research delete <work-package-ref>`；
- `research restore <work-package-ref>`；
- `research purge <work-package-ref> --dry-run/--apply`（只用于可永久清理对象）。

FTClient 使用同一 API，在研究入口提供 Active / Archived / Recently Deleted 筛选；
详情菜单提供归档、删除和恢复。UI 不直接操作 SQLite，不实现 CLI 之外的隐藏
数据能力。列表查询仍一次分页读；state 条件进入同一索引，不逐项查库。

### 最小持久化决策

Work Package 现在没有 canonical 表，只有重复出现在 Graph instances 中的
`work_package_id`。归档/删除是 Work Package 级别状态，不应复制到所有 historical
incarnations，也不能放在可包含多个 Work Package 的 `research_workspaces`。

**工程决定：** 在现有数据模型上增加一个极小的 canonical
`research_work_packages` 对象，每个
Work Package 一行，仅保存 owner/workspace/profile identity、title、lifecycle state/timestamps
和 current logical refs；Graph instances/branches/traces/runs 仍保留原表。这是一个新表，但比在
每个 incarnation 重复 lifecycle 字段、多行更新和复杂投影更少读写且语义唯一。

该表不保存报告、Evidence、义务、Trial 或 token telemetry；列表查询在原有分页 SQL
中一次 JOIN，使用 `(owner, workspace_id, lifecycle_state, updated_at)` 索引。Archive/delete/
restore 各是一次条件 UPDATE，不逐 trace/run 写入状态。Purge 才在 dry-run 生成完整
引用计划后事务删除相关对象。

## Grill 179.45 — 按业务生命周期重编研究主路径

**工程/研究方法决定：删除方法型节点，节点只表示稳定业务状态。**
后继 Graph 的研究主路径重编为：

```text
hypothesis_preregistration
        ↓
data_contract ↔ factor_semantics
        ↓
validation_design
        ↓
trial_execution
        ↓
[EvidenceAdmissionGate]
        ↓
result_audit
        ↓
research_decision
   ├─→ validation_design        新 Trial / 下一阶段
   ├─→ factor_improvement_required
   └─→ completed | paused_open
```

### 删除/替换的 v8 节点

| v8 节点 | 后继处置 | 原因 |
|---|---|---|
| `cheap_factor_diagnostics` | 删除；IC、分组单调性等成为 TrialPlan 中的可选低成本 method/action | 方法不是稳定研究状态 |
| `statistical_robustness` | 删除；bootstrap、deflated Sharpe、置换/敏感性等由 TrialPlan 和 statistical obligations 选择 | 不同 estimand/设计需要不同方法 |
| `authoritative_backtest` | 替换为 `trial_execution` | 权威回测只是 Trial 执行类型之一；IC、因子表、微观结构、外部/前瞻证据也可是 Trial |
| `job_evidence_ready` | 删除；Job/artifact 等待并入 `trial_execution`，qualification 由 `result_audit` entry 的 Admission Gate 完成 | Evidence 可来自同步 CLI、Job、外部数据或前瞻流，不应被 Job 身份限定；Gate 不是节点 |

`trial_execution` 不把所有试验强制变成异步 Job：

- deterministic CLI measurement 可同步完成并产生 receipt/artifact；
- 计算密集、回测、大数据或长时运行提交 JobAttempt；
- 外部/实盘/延迟流产生 connector receipt 和 observation window artifact；
- 所有类型最终都通过同一 `EvidenceAdmissionGate` 进入 `result_audit`，但
  qualification checks 按来源类型选择，不要求不存在的 Job ID。

### 方法如何编排

TrialPlan 保存 primary obligation、estimand、对照/信息边界和有序 `evidence_actions`，
每个 action 声明 capability requirement、预期 Evidence kind、成本、前置/停止条件和是否
异步。Research Agent 在 `validation_design` 优先选择信息价值高/成本低的 action，
但 Graph 不预设 IC 必须早于 backtest，也不预设 bootstrap 必须在回测后对所有
研究执行。

一个 Trial 可以预声明多个有依赖的 action，但不允许在一次 `trial_execution` 中
不经中间裁决全部跑完；详见 Grill 179.46。不用 Graph 节点表示每个方法，
也不为方法顺序创建新数据库行；当前 action index/status 存在 TrialPlan execution
checkpoint。

### 因子/数据语义的反馈

`data_contract ↔ factor_semantics` 不是无限循环。前置数据 inventory 说明“数据源有什么”；
factor semantics 说明“表达式/派生家族需要什么”。只有新增字段/时序/产品依赖时，
通过 entry-resolution frame 做增量 data check 并返回 `factor_semantics`；不重跑整份数据
contract，不为增量字段创建新永久节点。

### Continuation 影响

按 Grill 179.43 的严格规则，只有历史 trace 未触及被删/替换节点，且当前
node 在 target Graph 中存在的 Work Package 才可切换。当前两个 v8 Work Package 满足
这一初步条件；4 个旧 cheap-diagnostics Work Package 不满足，留在原 Graph。

## Grill 179.45a — 保留跨角色能力协调状态，但不放回义务目录

Grill 179.45 的主路径图只画研究生命周期，不表示删除所有协调状态。
按 Grill 179.8–179.13 已接受的跨角色语义，后继 Graph 保留：

- `capability_resolution`：只解析当前 target entrypoint、已触发条件和候选边的
  provider-neutral requirements；禁止全图预解析；
- `capability_gap`：保存精确 gap、受影响/未受影响范围和 EntryResolutionFrame；
- `skill_candidate_review`：等待新 Skill 的 grill/人工执行授权和验证 receipt；
- `code_improvement_required`：等待 Server Agent 修复后端/增加 CLI 能力并返回 receipt。

它们是可见、可恢复的协调/等待状态，不是 Verification Obligation 大类。
CapabilityRequirement/Binding/Gap/MaintenanceTask 仍按 Grill 179.21 的对象边界处理，不重建
`capability.*` 认知义务。

实际 trace 证明 SgCCS Work Package 已经过 `capability_resolution`、
`capability_gap` 及恢复边；因此保留这些节点同时满足业务需要和严格
continuation 规则，不是为迁移而伪造空节点。

只有以下事件写 server trace：新 gap、route 变化、maintenance task 状态实质变化、
receipt 返回和 resume。相同 requirement/input/registry/approval hashes 的 binding cache hit 不写新行、
不启动 Agent；只在报告中引用既有 binding receipt。

### 独立行业/拓扑审计后的裁决

独立审计建议把 `capability_resolution` 也收窄成目标节点的确定性 entry gate；这一
建议在“全新系统”中成立，但本后继 Graph **暂不采纳删除节点**，理由不是迁移方便，
而是当前语义确实包含跨角色、可持续等待的协调过程：

- cache 命中的 binding resolution 是纯 entry gate，不形成节点停留、Agent 调用或新 trace；
- 新 gap 需要把受影响研究暂停，并把 MaintenanceTask 交给 Server Agent；这时才进入
  `capability_gap` 等协调状态；
- Server receipt 返回后需要有确定、可 replay 的恢复位置，随后重新执行目标 entry gate；
- 当前 SgCCS 已有 accepted trace 经过 `capability_resolution/capability_gap`，而后继
  continuation 又采取 fail-closed 规则，直接删除会使本来可继续的当前研究无法切换。

因此实现上采用“**正常命中时是门，出现协调事实时才显式成状态**”的双层投影：
Graph protocol 保留协调 node IDs 及恢复边；常规 UI 主路径、Agent 小状态包和自然语言
研究章节不显示无事件的 `capability_resolution`。只有产生 gap、任务、receipt 或恢复
动作时，报告才逐条显示该协调过程。未来只有在所有历史 trace 都有显式、审计通过的
映射且协调 checkpoint 有同等可恢复语义时，才可另行提案删除这些 node IDs。

独立审计同时确认：固定 IC/bootstrap/backtest 方法节点应删除；TrialPlan 应用紧凑
`evidence_actions` 表达方法选择；Evidence admission 必须保持确定性 gate + admitted
checkpoint，不成为 Agent 推理节点。行业依据包括 NIST DOE 的逐轮设计/分析、
ICH E9(R1) 的 objective-estimand-design-analysis 对齐、Bailey 等对重复选择/holdout
过拟合的警告，以及 W3C PROV 对 Plan/Activity/Entity/Agent 的区分。它们支持上述
语义边界，但不被表述成“行业规定了这张具体状态图”。

## Grill 179.46 — 每个实质 Evidence Action 后必须重新裁决

**研究方法决定：** TrialPlan 可预声明有序 `evidence_actions`，但运行时每次只释放
一个当前可执行 action：

```text
trial_execution(action n)
        ↓
[EvidenceAdmissionGate]
        ↓
result_audit
   ├─→ trial_execution(action n+1)  仍有信息价值且冻结设计仍有效
   ├─→ validation_design           需修订设计/新 Trial
   ├─→ factor_improvement_required
   └─→ research_decision
```

原因是 action n 的 Evidence 可能：

- 证伪一个前提，使后续 action 失去意义；
- 扩大/缩小义务或新建义务，改变下一个最有信息价值的验证；
- 暴露数据、时序、方法或后端缺口；
- 命中停止条件，不应继续消耗计算/token/holdout。

一个 action 可产生多个紧密耦合输出，例如同一 IC Job 的 IC 表、分组结果和
数据质量摘要，或同一回测的净权益曲线、Sharpe、回撤、换手和成本分解。它们
作为同一 EvidenceEnvelope 的 metrics/artifacts 批量 admission，不为每个数字绕图一次。

Action n+1 的继续可以是确定性的：若 action n 的 admission/audit 没有改变它依赖的
obligation/design/method/stop hashes，且预声明 guard 成立，直接释放下一 action，不另启
reviewer。只有语义变化、冲突、低置信度或新义务时调用 Research Agent。

持久化不新增 action-event 热表：TrialPlan 保留冻结 action definitions，branch checkpoint 保留
`current_action_id/status/input_hash/output_evidence_refs`，trace 只在状态实质变化时写一个紧凑
delta。详细结果、表格和曲线仍在 artifact/journal。

## Grill 179.47 — Work Package 生命周期回填与旧验收数据清理

**工程/数据治理决定：迁移必须显式、可回滚，不根据 title/owner 字符串模糊
自动删除或转移归属。**

1. 从 `research_graph_instances` 的逻辑 `work_package_id` 集合一次回填
   `research_work_packages`；初始 lifecycle 为 `active`，保留原 owner/workspace/profile refs。
2. 能通过已有 Profile tombstone/migration receipt 证明新旧身份是同一用户的，才转移 owner/
   profile；只因 alias 像 `MaxA` 不足以转移。
3. 无法证明归属的旧研究进入管理员可见的 `legacy_orphan` 迁移队列，不向
   普通用户泄露，不伪装成 deleted。
4. 本次两个 Issue140 acceptance workspace 只使用已审计的 exact workspace/work-package/
   run IDs 生成 cleanup manifest；先备份数据库和本地 artifacts，跑 dry-run 引用图、
   计数与 integrity check，再在一个事务中 purge。
5. Purge 必须包含该 Work Package/workspace 独占的 instances、branches、traces、runs、jobs、
   artifacts/index/tombstones；共享 factor family、Graph versions、data source 和其他研究引用的
   artifacts 不删。
6. 验收包含 purge 前后逐表行数、无孤儿引用、SQLite `integrity_check`、正常 MaxA
   SgCCS Work Package/report 可打开，以及 Active/Archived/Deleted 列表只读查询基准。

迁移后，超级管理员 UI 可从服务器管理入口查看 legacy/orphan 计数和 exact refs；
归属修复/永久 purge 不是普通用户 UI 审批，通过 CLI/server maintenance 执行并保留
receipt。普通用户只能对已归属自己的 Work Package 归档、软删除和恢复。

### 独立生命周期审计后的收窄

旧 Issue140 记录不可见的原因已经确认不是删除：两个 acceptance workspace 的 owner
仍是 `default$MaxA@1`，而当前 principal 是 `18717974771`；Profile projection 同时按
owner 与 workspace 过滤，旧 instance 又没有可证明的新 Profile refs。因此不得仅凭
`MaxA` alias 自动改归属，也不能把 HTTP 404 解释成 archived/deleted。

canonical Work Package 最小字段收敛为 identity、owner/workspace、创建/当前 Profile、
title、`lifecycle_state`、`lifecycle_revision`、created/activity/lifecycle timestamps。
状态机收敛为：

```text
active → archived → deleted → [purged]
  ↑          ↑
  └──────────┘  archived 可恢复为 active；deleted 只能先恢复为 archived
```

- archive/delete 前若存在非终态后端 Job，返回 409，要求等待或取消；branch 的逻辑
  `running` 不能替代真实 Job 检查；
- archived/deleted 拒绝 transition、fork、handoff、Graph switch 和 new Job；恢复不自动
  继续研究或提交任务；
- purge 不是持久状态，而是 deleted 后、经过 retention/policy、dry-run plan hash、revision
  CAS 和明确 apply 的物理清除；
- 普通 owner 可 archive/delete/restore；orphan cleanup 与无归属永久 purge 只能由
  superadmin/server maintenance；Research Agent 不得自行 purge；
- lifecycle 变更历史进入既有 server audit sink/receipt，不伪装成 Graph research trace。

列表查询先由 `(owner, workspace_id, lifecycle_state, activity_at, work_package_id)` 索引
取得一页 Work Packages，再批量聚合该页 current branches；不得逐研究 N+1。handoff/
lifecycle CAS 只更新 canonical Work Package 一行，不再 UPDATE 所有 incarnations。

两个 Issue140 workspace 应作为 workspace-scope orphan cleanup 一次处理。dry-run 必须列出
12 instances、10 logical Work Packages、12 branches、53 traces、11 runs、12 succeeded
Jobs 和 artifact metadata，并验证没有跨 workspace/pin 引用。当前 artifact metadata 与
物理文件可能漂移；清理器只能在受控 artifact root 按记录的 relative path 删除，缺失文件
记为 `missing_already`，不得全盘按 Job ID 猜测路径。清理后执行 foreign-key/reference
复核和 SQLite integrity check，并永久保留最小 purge receipt（plan hash、计数、actor、时间）。

## Grill 179.48 — Grill 收口与实施规范

**状态：本轮语义 Grill 到此结束。** 后续不再逐个询问行业通用实现细节；只有新的
权限、不可逆数据损失、信息披露或真实产品政策歧义才重新进入 grill-with-docs。

后继 Graph 的 canonical 设计由以下组合构成：

1. Verification Obligation 大类仅保留 `hypothesis_validity`、`data`、
   `factor_semantics`、`trial_design_validity`、`statistical_validity`、
   `strategy_design`、`market_execution_accounting`，加临时 fallback `other`；
2. capability、Evidence qualification、research decision、report coverage 和 lifecycle
   都不是认知义务大类；它们分别是协调对象、admission gate、裁决动作、报告门和
   Work Package 生命周期；
3. 主研究状态为 preregistration、data/semantics、validation design、trial execution、
   result audit、research decision、factor improvement；IC、分组、bootstrap、回测等是
   TrialPlan `evidence_actions`，不是固定方法节点；
4. Evidence admission 是 `trial_execution → result_audit` 的确定性 gate，并先原子保存
   admitted checkpoint；缺少下游能力不能使已接受 Evidence 回滚或要求重跑 Trial；
5. capability 正常 cache hit 是 entry gate；只有新 gap/task/receipt/resume 才投影为显式
   协调状态和报告段落；
6. 每个实质 Evidence Action 后重新裁决信息价值、停止条件和义务 delta；未变化的下一
   action 可以由确定性代码释放，语义变化才调用 Agent；
7. Graph continuation 必须由用户显式触发，保留同一 Work Package 和同名当前节点；
   当前节点不存在、或历史 accepted trace 触及无审计映射的删除/重定义节点/边时拒绝；
8. 每个 node/edge/gate 必报项目由 immutable Graph 定义，Research Agent 用 requirement ID
   逐条提交中文 sentence/list/table/figure；结构化 Evidence、Trial、义务 delta 和审计详情
   用 alias-bearing Chip/表格行绑定并懒加载；
9. 每个可激活义务小类必须在发布前具有 provider-neutral CLI resolver、紧凑 schema、
   fallback route、报告 contract 和行业依据边界；无实现的 Graph 只能 draft；
10. Agent packet 与 transition input 保持独立硬预算；Agent packet 上限不是行业常数，
    而是每个 Graph 版本在激活前以完整局部 anchor 清单、真实 provider token 和服务端延迟
    重新校准，并保留至少 10% 且不少于 512 bytes 的语义余量；协议另设绝对防护上限。
    完整审计 trace、统计表、权益曲线和 stdout 分别使用审计上限或 artifact refs，超预算时
    只能去重或改为引用，不能截断义务、Evidence 或必报内容；
11. Work Package lifecycle 使用最小 canonical owner 行，UI/CLI 共享 API；旧 orphan 验收
    数据通过 exact-manifest server maintenance 清理，不自动归属、不做兼容性读取。

实施前先把本文件 Sections 3–8 的初始表转换为单独的 canonical machine-readable
catalog/topology/report manifests；原表保留为 Grill 历史但不得被 builder 导入。实施按可
独立回滚批次提交：共享 Graph schema/validator → catalog/resolver contracts → 后继拓扑与
continuation preflight → TrialPlan actions/admission → 标准化报告/UI → lifecycle/cleanup →
历史 v1–v3 恢复与真实 SgCCS shadow acceptance。每批测试通过即提交，不堆到最后。

## Grill 179.49 — 研究发生时间、登记时间与历史对话补登记

**已接受并纳入实施。** 节点访问和报告内容日后可以从既有 Agent 对话补登记，但补登记
不能伪造原研究顺序、移动当前 Graph HEAD，或把导入时间冒充研究发生时间。

统一使用一个可附着于 checkpoint event 和 Report Item 的最小 timing envelope：

- `recorded_at` 是服务端可信的不可覆盖登记时间；现有 trace `created_at` 在存储层继续承担
  此语义，并用于 topology、cursor、HEAD、幂等和审计顺序；
- `occurred_at` 是可选的研究发生时间，可表示当时进入节点、完成边上判断或在 Agent
  对话中形成该条报告内容的时间；
- `time_basis` 仅为 `transition` 或 `historical_backfill`；
- 历史补登记必须提供 `time_source_refs`，指向可复核的原 Agent 对话、checkpoint、Job 或
  artifact；普通实时 transition 不要求重复保存来源正文；
- UI 的页面访问时间只属于本地产品 telemetry，不是研究事件，也不得进入 Active Graph
  或研究报告；确定性生成 Markdown/PDF 的运行时间同样不进入正文，避免相同研究事实因
  重新渲染而改变 canonical bytes。

checkpoint 级 `research_occurred_at` 是该研究步骤/节点访问的默认发生时间；同一
checkpoint 内绑定到具体 `report_requirement_id + subject_ref` 的报告块可以用独立
`report_timing.occurred_at` 表示该条内容在 Agent 对话中形成的时间。报告条目未覆盖时
继承 checkpoint 时间。两者都只改变本地 immutable narrative/fragment hash，不参与
Graph 排序、幂等主键或研究 freshness。

旧 v1/v2 narrative 没有 `occurred_at` 时，显示层可回退到 `recorded_at`，但必须标注为
“登记时间/发生时间未单独记录”。补登记通过独立 CLI action 读取可信历史 Carrier 和来源
引用，向原 Work Package/branch 插入缺失的 immutable report fragment 并重建本地 journal、
index 与报告投影；它不得推进 branch、改变 `latest_trace_id`、Profile freshness、Work Package
`updated_at` 或触发 Graph transition。相同输入必须幂等，冲突叙事、错误 branch、断裂
checkpoint 或来源循环一律 fail closed。

该能力复用现有 trace、local journal 和 artifact refs，不新增 event/report 时间数据库表。
FTClient 正文可显示“研究发生于 / 补登记于”，版本树继续按可信 trace 顺序绘制；历史
发生时间只改善叙事定位，不重新排序或改写版本树拓扑。

补登记必须从可信 root 按 server trace lineage 重建到当前 HEAD，不是在任意既有完整
journal 中插入一条旧章节。如果旧派生 journal 曾把中途 checkpoint 错当 root，补入更早
checkpoint 会与不可变 fragment 的 root/predecessor 语义冲突；一次性迁移必须先归档该
Work Package 的旧派生产物，再从可信根重建，不能修改旧 fragment、保留兼容分叉或在
重建中间阶段把 REPORT 暂时回退到历史 HEAD。历史 fragments 先 stage，最后只以当前
可信 HEAD 原子生成 JOURNAL/INDEX/REPORT；Profile/branch/Work Package 的 head 与
语义时间字段保持不变。

最终 shadow acceptance 必须由用户显式把测试研究切换到 v9，并以 Codex 对话
「MaxA (2)」作为历史来源恢复真实实验记录和中文逐条报告。来源引用、节点发生时间、
报告条目发生时间、Trial/Job/Evidence 绑定均须可复核；不得另造替代实验、用迁移日志
冒充研究报告，或因恢复而产生第二个 Work Package。恢复完成后再从 v9 当前可信 HEAD
继续 shadow research。

若对话记录缺少完成报告所需的服务器交互、Job receipt、统计结果或 artifact，必须在
恢复期间真实调用服务器补跑；新运行保留新的 Job/Run/Evidence 身份和当前可信记录时间，
并在报告中逐条标记为“为补齐历史记录而复跑”，不得回填成旧时间。是否复跑由证据完整性、
v9 entry requirements 和研究义务决定，不机械重复所有既有测试。必要的统计结果表、
equity curve、分组单调性或其他能实质支持判断的图像须生成内容寻址 artifact，嵌入中文
报告并绑定对应 Trial/Job/Evidence；历史 fragment 回填与当前 v9 正常 transition 必须分开。

## Grill 179.50 — 运行配置、公式排版与限额下的回测曲线

**决定：实验结果必须同时投影运行配置，因子语义必须显示排版公式；默认长期保存回测
曲线图片而不是完整时间序列。** 三者均为本地报告/Artifact 投影，不复制进 Agent packet，
也不增加研究 Graph 热路径数据库读取。

每条 Trial 结果表必须绑定 `run:` 与 `job:`；正文逐项列出足以理解比较的关键控制量，
包括因子家族/版本/参数、产品与频率、样本阶段和时间、策略/session 设置（含显式
`end_session_skip`）、成本/滑点/保证金以及数据与后端身份。Run Chip 通过 checkpoint-scoped
lazy endpoint 读取不可变 ResearchRun，并显示 configuration revision、RunSpec hash、Trial
role/stage、comparison、sample identity 和完整冻结 RunSpec。完整 JSON 不进入正文，不能用
当前可编辑配置替代历史 RunSpec。

`factor_semantics.expression_identity`、`observable_meaning_direction_units`、参数化/派生比较
以及 `factor_semantics` 节点 action 允许并要求在适用时提交 `math` block。Markdown/PDF 使用
LaTeX；FTClient 主视图用随 App 固定版本打包的离线 MathJax 把公式排版为 SVG，LaTeX 源码
只放在可展开审计区，失败时才显示中文 fallback。不得依赖 CDN，避免网络、提供方升级或
服务器版本使历史公式失效。

回测完成后，Artifact 阶段从与指标相同的净收益/权益序列确定性生成一张内容寻址的
`equity_curve` 图：默认采用可缩放 SVG，并包含净值与回撤两个面板；正文显示图和关键指标
表，Chip 显示毛/净口径、基准、成本/保证金、原始点数、降采样算法/点数、绘图器版本、
image hash、Run/Job/Evidence refs 与底层序列 retention 状态。图像生成在撮合完成后进行，
不得把绘图放进计算热循环。

服务器限额策略为：

- `summary`：长期保留小型曲线图、指标摘要和绘图 receipt；生成完成并校验 hash 后可清理
  完整序列；
- `full`：图和完整序列均保留，计入用户限额；
- 序列已按限额清理时，图片仍是可读的历史投影，但不得声称支持逐点重算；需要复核时，
  只能在数据仍可得的情况下用同一 RunSpec 新建 Job 重跑。

历史 Job 有净收益序列时可确定性补图并标注“历史投影补全”；没有序列时不得从指标猜造
曲线，必须真实复跑或明确记录不可恢复。FTClient 对图像使用缩略预览和点击懒加载原图；
本地图像文件按 content hash 复用，页面打开不反复读服务器数据库。

## 13. Graph 版本 UI 与历史存储

服务器现有 `research_graph_versions` 已是历史版本的 canonical store；每个版本
保存完整不可变 `graph_json`、parent、content hash 和创建身份，Active pointer
单独保存。不得为 UI 再复制一套 Graph 数据库。

FTClient「研究」内部增加 Graph 浏览视图：

- 版本树：parent lineage、Active badge、hash、发布时间和缺失祖先；
- 拓扑：当前版本节点/边，点击后查看节点 entry requirements、报告条目和边规则；
- 义务目录：按大类展开小类的中文问题、选择条件、所需证据和反例；
- 报告规则：按 node/edge anchor 查看必报 ID、方法、subject/binding contract；
- 版本比较：只显示 Change Manifest 和确定性 structural diff；
- 审计：只读显示 proposal/review/grill/activation refs，不在 UI 批准；
- 研究关联：显示每个 Work Package 当前 pin 的 Graph 版本及可用后继版本。

热路径保持一条版本摘要查询；选中版本后按 exact version 读取服务器 hash cache；
diff 只加载两个选中版本。不得为画版本树逐节点/逐边查询数据库。

当前服务器可确认 v4–v8，v4 指向缺失的 v3。v1–v3 只能从 exact Git/backup/
artifact 来源恢复；找不到 canonical bytes 时保留缺失祖先占位，禁止根据文档描述
合成一个看似真实的历史图。

用户进一步要求 v1–v3 必须全部恢复。已定位的 canonical code lineage 是：

- `689e141e78c90d5cbb6d7b96e236919056db7525`：Observed v1 与 Draft v2；
- `f1ac3d3b46e17120647ac958ba369f0999e90a4c`：统计协议对齐后的 Draft v3；
- 当前 v4 数据库行明确 `parent_version=3`。

已在隔离 checkout 中验证 canonical identities：

- v1: `d8d76b80fbca0342d3b8477e1594bfd7da1dab2924c7d2d078bf64e8ba44d64e`
  （13 nodes, 13 edges；不同 factor family/configuration 输出相同）；
- v2: `95a82ea250f1502b7ce7706f85a663738afc08f5ec7f8bcebc71d7082f6bf689`
  （14 nodes, 19 edges）；
- v3: `ae7bbc1ad50b22e75c6f781ced3510cd05de250f966bbb402e7bba999421c3b2`
  （14 nodes, 21 edges）。

恢复批次必须：

1. 建立隔离 historical checkout，不修改当前 branch；
2. 用历史代码和当时固定 plan 生成 v1，证明 plan 中因子名/配置不会改变投影身份；
3. 用各自 commit 直接生成 v2、v3；
4. 用对应历史 `graph_content_hash` 和 validator 验证 canonical bytes；
5. 备份目标 SQLite，执行 `PRAGMA integrity_check`；
6. 在一个事务中插入 v1–v3，actor 标明 `history-recovery:<commit>`；
7. 验证 parent lineage 0→1→2→3→4，且 v4–v8 hash 和 Active v8 pointer 不变；
8. 再由当前共享 Graph protocol 做只读兼容验证和 UI 版本树验收。

如果历史 v1 plan 身份无法由代码和测试唯一证明，必须继续寻找当时 session/
artifact，而不能改用当前 plan 猜测；最终验收仍要求 v1–v3 全部存在。

## Grill 180.1 — Provider 用量信任链与 v9 Shadow 激活

**决定：调用方提交的 token 数值只能称为 `caller_reported`；只有服务器通过
provider-neutral receipt verifier 验证的用量才可称为 `provider_actual`，并参与
Active Graph 激活。** 随机 request ID、任意 attestation 字符串或仅保存它们的 hash
都不能证明用量来自 Provider。

该决定修正了当前 `AgentInvocation` settlement 与 v9 shadow gate 的信任边界：

- 普通 CLI/HTTP settlement 继续允许 Agent 无缝结算，但即使同时提交 input/output
  token、provider request ID 和 attestation，也只能形成 `caller_reported`；
- `provider_actual` 只能由 server-owned verified settlement 写入。可替换 verifier
  校验 opaque receipt 与 reservation 中的 owner、provider、runtime、model、
  `input_hash`、request identity 和 token breakdown 一致；不支持验证的 Provider
  可以正常研究，但不能为图激活提供真实用量证据；
- 验证成功后复用现有 `launcher_attestation_hash` 记录“本服务器 verifier 已接受该
  receipt”的持久标记；`provider_attestation_hash` 只表示外部凭据指纹，不能单独作为
  信任标志；
- 复用现有 AgentBudgetPeriod 与 AgentInvocation，不新增 receipt、comparison 或 token
  表，不保存原始凭据。Provider request 唯一约束用于防重放，不被误作真实性证明；
- 每次激活 shadow 由 canonical graph/version、graph Run、baseline Run、共同 RunSpec
  和冻结 workload 计算 comparison lineage。两侧必须使用相同且非空的 workload
  `input_hash`，同时分别绑定精确的 graph instance/branch/run 与 baseline run；
- 激活只读取该 comparison cohort，不能再把两个“当前 budget period”的无关累计用量
  当作对照。两侧均须为已封闭、无 sponsor、角色匹配且全部 `provider_actual` 的完整
  invocation 集合；不允许选择性登记或用其他任务补足；
- activation 冷路径使用一次有界 grouped query 返回两侧 binding、quality、provider
  hashes 和 token 合计，替代现有 measurement-quality 聚合。Routine Agent packet、
  Graph transition 和普通 Job 热路径不增加数据库读取或写入；
- token shadow 与 outcome shadow 均须使用真实 CLI Run/Job。两个空 ResearchRun 或
  测试中手填的 70/10、90/10 只能验证协议，不能作为 v9 真实激活证据；
- outcome shadow 是激活 smoke，不等于 MaxA 的完整 v9 Research Agent 路径。图激活后
  仍须在同一 Work Package 完成语义、TrialPlan、样本内 IC、无费/含费对照、日夜分组、
  Evidence/义务裁决和报告验收。

验收必须覆盖：公开 settlement 不可伪造 actual；有效 receipt 可通过两种 fake Provider
verifier 证明 provider-neutral；篡改 token/request/input/runtime/model/provider、receipt
重放、错误 run/instance/branch/lineage、混入其他 period 或未封闭 cohort 均 fail closed；
graph 真实 receipt 加 baseline 手填用量仍失败；token 聚合保持一次查询且最终 schema
不增加 owner table。

## Grill 181 — Token 校准与 Graph 激活解耦

**决定：校准仍然需要，但校准可得性和 token 回归不再是 Active Graph 激活的
前置条件。** Grill 180 对 `provider_actual` 的信任定义保持不变；没有可信 receipt
时必须如实记录 `uncalibrated` 或 `mixed_or_fallback`，不得把调用方数字升级为真实
Provider 用量。

具体 token、packet 上限、Provider、model、tokenizer 和校准结果属于独立、带 hash 的
运行时 Budget Profile，不属于 Graph canonical content：

```text
Graph hash
  └─ 研究节点、边、义务与报告要求

Budget Profile hash
  └─ Provider/model/tokenizer、packet 上限与校准状态

Run / Transition
  └─ graph hash + budget profile hash
```

- v9 Graph 不再嵌入 `agent_packet_budget` 数值或校准阈值；
- 服务器从当前 Graph 的 node/edge/system-gate 派生校准 anchor，并把 coverage 写入
  Budget Profile；调整 Profile 不改变 Graph hash；
- 无 receipt 时使用当前 Profile 的 packet ceiling，并保留未校准状态；取得可信 receipt
  后生成新的 Profile 版本，后续调用使用新 hash，历史调用保留旧 hash；
- 协议绝对安全上限属于服务器实现；修改它需要代码发布，但不改变研究图版本；
- 激活仍必须拒绝局部 context 超限、routine 加载完整 Graph、未触发条件或未来节点
  gap 进入当前 packet、以及违反风险分层的多 Agent 启动；
- token 对比、延迟和 cache 命中继续记录并供 UI/维护 Agent 优化，但单纯缺少校准、
  token 为零或 v9 token 高于 baseline 不阻止激活；
- 只有预算策略永久跳过必要 reviewer、证据或研究步骤时，才构成研究语义变化并进入
  Graph/执行策略审查。

## Grill 182 — Draft continuation 与运行时预算对象收口

外部审计指出两个残余耦合：本地 Work Package 不能显式试用未激活的 draft，且
schema-v2 校验器仍接受图内 `agent_packet_budget`。用户进一步确认：当服务器随后
激活完全相同的 Graph 时，先前进入该 draft 的 continuation shadow 应视为 live。

最终语义：

1. continuation 的 `execution_mode` 只有 `live` 与 `shadow`。它与描述研究状态如何
   续接的 `same_node_reentry`、`job_evidence`、`pre_trial_checkpoint` 分开记录；
2. `live` 必须命中 Active pointer；`shadow` 可进入已登记且 hash 精确匹配的 draft，
   并明确标记为非生产研究；
3. 激活同一 `graph_id + version + content_hash` 时，只把没有 `shadow_run_id` 的
   continuation shadow 晋升为 live。用于 activation outcome comparison 的 shadow
   不晋升。原 continuation trace 仍保留 `execution_mode=shadow`，因此历史可审计；
4. schema-v2 Graph 出现 `agent_packet_budget` 一律拒绝；v1 历史图只读兼容；
5. 6400 bytes 仅是未配置服务器的 bootstrap default。管理员可通过 CLI 创建并切换
   独立、内容寻址的 Budget Profile；旧 Profile 保留，普通 context/next 使用进程内
   缓存，不增加数据库热路径读取；
6. 改变 Budget Profile hash 不改变 Graph hash。Run/Transition 继续同时记录二者。

验收覆盖 draft shadow 成功、同 draft live 失败、v2 内嵌预算失败、Profile 变化不改
Graph hash、激活只晋升 continuation shadow、HTTP/CLI 模式透传和激活 SQL 上限。

## Grill 183 — Graph 升级删除式简化

用户指出当前实现把研究方法、运行配置、后端能力和单项研究变化都误当成 Graph
升级。只有第一类属于 Graph canonical content。

Graph continuation 因此只检查：

1. exact target hash；
2. 当前节点在目标 Graph 中仍存在；
3. 当前节点 Entry Requirements 的新增或语义修订；
4. 既有本地义务/Evidence 是否覆盖新增要求，由 Research Agent 在 re-entry 中判断。

历史访问过的节点、边、数据契约、因子语义和 Trial 不参与 continuation eligibility，
也不被重跑。升级仍表现为附属于当前节点的 re-entry 记录，而不是迁移节点。实现删除
了 Work Package 全历史 topology footprint 查询及 replay 校验，因而同时减少一次
数据库读取。生产激活的剩余 proposal/review/audit/authorization 对象是否全部折叠为
一次 exact-hash 激活命令，继续按 Grill 183 的最后一个治理边界收口。

普通 continuation 已先完成同方向收缩：authenticated user/Research Agent 发出的
命令本身就是显式切换请求，`continuation-preview` 给出 exact target hash，
`continue` 只接受该 hash。删除额外 Maintenance approval Gate、Gate 反查和对应
CLI 参数；不可变 trace 仍保存 actor、source/target Graph hash、checkpoint、当前
节点及 requirement diff。该变化净删除普通路径代码与测试夹具，并不降低 lineage
或 stale-target 检查。
