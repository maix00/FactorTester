# ADR-047: Workspace、Work Package 与 Branch 的身份边界

## 状态

已接受。

本 ADR 中的 WorkPackage、Graph Branch、Graph checkpoint、TrialPlan binding 与 Graph Evidence admission 约束已由 ADR-156 取代。Workspace 与冻结 Run 配置相互独立的规则仍有效；报告协作迁移为稳定 ReportBranch。

## 决策

`Workspace` 是用户编辑执行配置的长期、可变环境。提交一次 Trial 时，系统把所需配置冻结为独立的 configuration snapshot；`RunSpec`、`TrialPlan`、`ResearchRun` 与 `JobAttempt` 引用该快照。Workspace 只保留来源和组织语义，不声明研究对象。

`WorkPackage` 是一项研究的稳定业务容器，由用户与 Profile 持有。它拥有研究图实例、Branch 集合、报告、义务账本和研究历史，不属于某个 Workspace。创建时记录的 Workspace 只是一项历史 provenance，不参与对象身份或授权。

`Branch` 是 WorkPackage 中的一条研究决策路径。它由 `work_package_id`、物理 `instance_id`、`branch_id`、incarnation、Graph 版本和 checkpoint 定位。Branch 可以在不同阶段执行来自不同 Workspace 的冻结配置；同一 Workspace 也可以为多个 WorkPackage 或 Branch 提供配置快照。

具体研究对象只能由冻结的 `factor` 或 `factor-set`、TrialPlan binding 和报告富文本引用声明。Factor family 只可作为可导航的模板引用，不能充当一次 Trial 的冻结 subject。

## 不变量

- Workspace 不声明或限制 factor、factor family、factor-set、产品研究范围或 Graph 路径
- Graph Run、JobAttempt、EvidenceUse 和报告发布不得要求 Workspace 与 Branch 相等
- Profile 创建研究不得因存在多个 Workspace 而失败；显式 Workspace 选择只改变创建 provenance
- Evidence 的 Graph admission 以 WorkPackage/Branch 为环境和 subject，不以 Workspace 为权限边界
- 切换、修改或删除可变 Workspace 不得改变已有 WorkPackage、Branch、报告、义务或 Evidence 的身份
- Run 仍必须冻结有效配置快照；解除 Workspace 门禁不解除 owner、Profile、WorkPackage、Branch、incarnation、checkpoint、TrialPlan 或 frozen subject 校验

## 生命周期

1. 用户在 Workspace 中编辑执行配置
2. 创建 WorkPackage 与初始 Branch；Workspace 只可记录为创建来源
3. Agent 在 Branch 上推进 Graph、维护报告和义务
4. 提交 Trial 时冻结当次 configuration snapshot、factor/factor-set、RunSpec 与 TrialPlan
5. Run 和 JobAttempt 回写到 Branch，但不因其来源 Workspace 不同而失效
6. WorkPackage 可分叉、归档或恢复；Workspace 后续变化不影响其历史

## 后果

数据库中为迁移保留的 `workspace_id` 列不得参与 Branch、Evidence 或 Job 的业务等值判断。新代码需要 Workspace 来源时，应明确命名为 provenance；需要研究身份时必须使用 WorkPackage/Branch 引用。
