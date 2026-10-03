# ADR-157：Run 级样本使用合同，不再依赖 TrialPlan

- **状态**：分阶段迁移；新 Run 的写入路径已切换，历史 TrialPlan 只读兼容。
- **日期**：2026-10-03
- **取代**：TrialPlan 作为新运行、样本保护和 Evidence 身份前置条件的要求；历史记录格式继续可读。
- **相关**：[ADR-037](037-research-run-job-persistence-boundary.md)、[ADR-039](039-research-result-artifacts-and-user-quotas.md)、[ADR-156](156-retire-research-graph-agent-workflow.md)。

## 背景

TrialPlan 将研究动机、统计协议、运行成员、样本角色、停止规则和决策标准放进一个独立业务对象。样本成员和运行绑定确有保护价值，但普通 Run、Job Evidence 和报告不应为了这些可选规则而先登记整份计划。声明统计方法也不等于执行了该方法。

## 决策

普通运行继续以不可变 RunSpec、ResearchRun、Job 和 Artifact 表达执行事实。假设、研究理由与决策记录归报告正文或可选附件；实际执行的分析输入归 RunSpec/执行配置；只有需要保护样本时才附加小型 Run 级 `sample_use` 合同。

合同 schema v1 包含 `purpose`（`exploration`、`selection`、`validation`、`confirmation`、`holdout`）和 `protection`（`open` 或 `sealed`）。`validation` 不自动代表封存测试集。sealed 合同还必须冻结 `comparison_id` 与完整的 `member_run_spec_hashes`，且包括当前 RunSpec。合同哈希绑定服务端推导的样本哈希，包含同一研究者对数据用途所作的不可变选择。

样本暴露登记直接在创建 Run 的 SQLite 写事务中执行。检查限定于同一 owner，并依据冻结日期范围和精确产品成员集合判断重叠；读取时不展开可变产品组。一个 sealed 比较的每个 RunSpec 只能暴露一次。任何先前重叠暴露都会阻止新 sealed 比较；open 暴露允许明确记录后续探索，但会使原样本不再满足“此前未暴露”的 sealed 条件。历史 TrialPlan 标记的 confirmation、holdout 与 validation Run 仍参与旧暴露检查，避免省略新合同绕过已有封存限制。缺少日期或成员证据时，对可能影响 sealed 样本的情形失败关闭。

Run Evidence 以实际 `run_spec_hash`、Job、Artifact 与可选 `sample_use_hash` 为身份。`trial_plan_hash` 是可选历史引用，不是新运行或 Evidence 的必需字段。报告新模板不生成空 TrialPlan 字段；旧报告中的有效哈希仍按历史引用显示，空字符串被规范化移除。

## 写入与读取边界

- `/api/runs` 不再接受 `trial_binding`；请求带该字段时返回 410，并引导使用 Run 级 `sample_use`。
- TrialPlan 创建 HTTP 路由、管理端路由和 CLI 创建子命令已退役。CLI 仍可通过 `trial-plan show` 读取历史对象。
- 历史 Run、Job detail、Evidence identity 和报告只在确有旧 TrialPlan 哈希时投影对应字段；不会伪造空身份。
- 历史 TrialPlan 表与 Run 列暂不删除，不重写或迁移其正文。其清理必须另行只读盘点、备份并取得数据迁移授权。

## 不在本决策中的能力

`sample_use` 不声明或执行多重检验、顺序停止、继续/拒绝标准、训练切分、模型调参或资源限制。这些信息属于实际执行配置、统计分析任务或报告；若方法没有计算实现，平台不得通过一个计划字段声称已执行。

批量展开、幂等重试、阶段复用、恢复与收集继续复用现有 Run/Job/Artifact 权威，不在此引入第二个任务状态对象。输入快照和 IC 附件仍各自按其工作包演进。

## 验收条件

- 不创建 TrialPlan 也可提交 Run、读取 Run/Job、生成并验证 Evidence、绑定报告。
- 没有 `trial_binding` 写路径；旧 TrialPlan 可以按 owner 读取，历史 Run 与报告引用仍可显示。
- open validation 与 sealed holdout 语义明确，精确产品/日期交集、owner 隔离、完整候选成员、单次暴露、未知历史和并发创建均有测试。
- Run Evidence 不依赖 TrialPlan 哈希；有效 RunSpec/Evidence 身份通过其实际来源验证。
- 新报告不写入空 TrialPlan 字段，旧有效哈希仍可读取。

## 实施记录

- Run 级 sample-use contract、owner/日期/成员暴露校验及原子创建已进入实现。
- 新 Run 与 Evidence 投影不再合成空 TrialPlan 身份；历史投影仍保留实际哈希。
- HTTP/Manager/CLI 的 TrialPlan 写入已停用，历史 show/read 路径保留。
- 完整聚焦测试、Issue 集成与部署状态记录在 #405 的实施回执中；生产部署需遵循仓库发布门槛。
