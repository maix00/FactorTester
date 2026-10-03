## Workspace {#workspace}

Workspace 是一次研究或执行活动采用的配置与资源视图。它可以关联用户、Profile、Research 或测试工作台，但不自动改变任何全局对象的所有权。Workspace 不绑定固定因子家族，也不能阻止研究范围扩大或缩小；真正的边界由对象引用、权限和提交快照决定。

因子工作区、Research Workspace 和测试配置草稿是三个不同用途的工作面：前者管理可复用因子副本，后者保存某项研究的上下文，测试草稿只在提交前可编辑。名称相似不代表它们可以互相覆盖。

## Report 与 ReportBranch {#report-branch}

Report 是可独立阅读、授权和发布的研究报告；ReportBranch 是报告正文的一条可编辑版本线。不同 Profile 可以在各自的 Branch 上协作，并通过受控的跨 Branch 操作复用章节。报告身份不依赖执行 Workspace 或服务器位置。

## 冻结对象 {#frozen-objects}

具体因子和 FactorSet 可以冻结并获得稳定引用；factor family 是定义和发现入口，不是一次试验的冻结研究对象。产品路径、数据源成员、策略代码和因子源码也必须以可追溯引用进入提交。

RunSpec 冻结测试配置，Job 记录一次执行，Attempt 记录一次尝试，Artifact 记录输出。任何结果页都应沿这条关系读取，不应从当前编辑器或服务器目录重新推导历史输入。

## 选择对象还是复制内容 {#reference-vs-copy}

能复用的业务对象使用稳定 ref；需要编辑的页面状态使用草稿；需要审计的执行事实使用不可变快照。复制一段显示名称、源码或 JSON 不能替代对象引用，因为复制物可能缺少版本、所有者、权限和来源。
