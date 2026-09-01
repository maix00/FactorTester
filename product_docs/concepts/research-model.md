## 研究对象的边界 {#research-boundary}

Research 是一个研究上下文，不是单篇文章的别名。它拥有研究目标、参与的研究身份、研究工作区和可以持续演进的证据集合；一个 Research 可以包含多份 Report。Research 可以单独公开或共享，Report 也可以有更窄的公开范围。

研究报告是面向阅读的结构化投影。它包含章节、段落、表格、对象引用和证据引用，但不能因为某段文字出现在报告里，就推断它已经成为正式证据或满足研究义务。

## Profile 与 Research Workspace {#profile-research-workspace}

Profile 表示执行研究工作的身份。Profile 可以参与多个 Research，但每个 Profile 在每个 Research 中都需要一个独立的 Research Workspace，用于保存该研究上下文下的草稿、提交和协作状态。

Research Workspace 不等于 Profile 的因子工作区。因子工作区是 Profile 可复用的独立副本；Research Workspace 只保存本研究所需的选择、RunSpec、报告材料和协作产物，不能把一次研究的临时修改悄悄变成全局因子库变更。

## Report 与 Evidence {#report-evidence}

Evidence 是跨 Research 可复用的事实对象。Job、RunSpec、Artifact、外部来源和人工记录都可以成为 Evidence 的不同来源，但只有通过正式绑定才会出现在报告或研究图的证据关系中。

权限按传播范围区分：报告公开时，报告读者可以看到被引用证据的摘要和关联关系，但不自动获得生成物或文件下载权；Research 公开或共享时，授权范围内的读者才可以按该 Research 的权限下载相应生成物和文件。UI 上的“可见”不能替代服务端权限判断。

## 对象关系 {#research-object-graph}

```text
Research
├── Research Workspace（按参与 Profile 分开）
├── Report × 多份
├── Profile × 一个或多个参与身份
└── Evidence × 可跨 Research 引用
    ├── RunSpec / Job / Attempt
    ├── Artifact
    └── 外部来源或人工记录
```

Research 不嵌套 Research。需要组织层级时，应使用报告章节、研究图节点或 Evidence 关联表达，而不是把一个 Research 挂到另一个 Research 下面。

## 共享时要核对什么 {#sharing-checklist}

共享前至少确认四件事：公开对象是什么、读者能看到什么、读者能下载什么、撤销共享后哪些缓存和下载凭证立即失效。报告的阅读权限、Research 的证据下载权限和 Profile 的写入权限是三个独立判断。
