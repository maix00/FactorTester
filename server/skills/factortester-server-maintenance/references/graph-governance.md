# Graph 版本治理

区分三种操作：`publish` 创建不可变的已审查 Graph 版本；`activate` 只改变新研究的默认版本；`continue` 明确将合格 Work Package 分支迁移到后代版本并保留历史。

## 发布与激活

验证 schema、父版本链、内容 hash、Requirement Catalog、resolver 覆盖、Report Methods、能力描述、拓扑、Change Manifest 和 token 预算。活动子类别缺少实际 resolver 或报告契约时只能保持草稿。

发布后的治理顺序：

1. 预留并结算一次真实 proposer 调用。
2. 用 `auth-conversation:` 引用和精简差异提出方案。
3. 独立 reviewer 通过 `research-graph proposal <proposal-id>` 读取服务器的精确审查包，检查不可变目标、Change Manifest 和证据引用，按返回的命令契约提交结论。
4. 检查 `research-graph activation-status <graph-id> <version>`。
5. 在具有精确 hash 的人工授权后执行 `research-graph activate <graph-id> <version> --yes`。

`activation-status` 是简要门槛的权威来源。升级验证在一个事务内确定性派生，在切换默认指针前回滚所有临时实例、分支和轨迹，不保留验证 Work Package。除非 Graph 契约要求，不强制 grill 记录。proposer 不得用自行重构的总结替代审查包；reviewer 主体和 lineage 应独立，其调用已经结算。

激活不迁移正在运行的研究，记录旧新指针和回退目标，不在激活过程中运行因子研究、创建义务或更改证据。

## 分支续接

需要用户明确请求，并做确定性的源到目标预检。目标须通过完整不可变父链可达且包含当前节点；历史转换保持绑定原 Graph，无需目标仍保留所有历史节点和边。

累计 Change Manifest 只计算一次。保留同一 Work Package 和逻辑 Hypothesis Branch，创建绑定目标版本的新物理实例。只有用户确实需要不同研究方向时才使用 `fork`，不能用 fork 或持久临时分支代替升级验证。

通过派生的 re-entry gate 进入目标节点，不新增迁移节点，不机械重跑能力、数据和语义阶段，不由维护 Agent 虚构因子专属义务。

已有未结束的能力恢复分支时，先只检查当前节点新增或修改的要求，保留同一 episode 和 `resume_node`，完成恢复后走明确的 resume edge。其余升级要求进入所属节点时再评估，不嵌套第二个能力恢复 episode。

Research Agent 只处理实际触发的语义工作：要求覆盖、义务重分类或重新打开、证据资格和逐项中文报告。旧证据保持不可变；范围、来源和时间仍有效时复用。
