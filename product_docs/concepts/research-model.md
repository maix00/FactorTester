## Research 的职责 {#research-boundary}

Research 是研究目标、参与身份、协作上下文和证据集合的根对象。它可以包含多份 Report；Report 是面向阅读的结构化表达，不是 Research 的别名。报告中的文字只有在引用正式 Evidence 时才建立证据关系。

Research 不应被实现为嵌套目录。需要表达层次时，使用 Research 内的报告章节、对象引用或 Evidence 关联；不要把一个 Research 挂到另一个 Research 下面。

## Profile 与 Research Workspace {#profile-research-workspace}

Profile 表示执行研究工作的身份。一个 Profile 可以参加多项 Research；每个 Profile 在每项 Research 中有独立的 Research Workspace，用于保存该研究范围内的选择、配置、草稿和协作状态。

Research Workspace 是逻辑对象，不是文件目录，也不是新的权威因子库。因子工作区保存可复用的因子副本；测试配置草稿只在提交前编辑；Research Workspace 保存研究上下文。三者用途不同，不能相互覆盖。

## Report、Evidence 与 Artifact {#report-evidence}

| 对象 | 作用 | 权限含义 |
| --- | --- | --- |
| Report | 组织正文、表格、链接和证据引用 | 报告阅读权限只决定读者能否看报告 |
| Evidence | 记录可追溯的研究事实和来源 | 必须使用正式引用建立关联 |
| Artifact | 保存 Job 产生的结构化输出或文件 | 文件下载仍由对象存储端和研究权限控制 |

Job、RunSpec、Attempt、Artifact、外部权威来源和人工记录都可以作为 Evidence 来源。引用 Evidence 不会自动授予下载原始 Artifact 的权限。

## 对象关系 {#research-object-graph}

```text
Research
├── 参与身份（Profile）
├── 每个参与身份对应的 Research Workspace
├── Report（可以有多个）
└── Evidence（可被多个 Report 引用）
    ├── RunSpec / Job / Attempt
    ├── Artifact
    └── 外部来源或人工记录
```

## 共享前的权限核对 {#sharing-checklist}

共享前分别回答：公开的是 Research 还是 Report；读者能看到正文和哪些证据摘要；读者能否下载相应文件；撤销权限后，服务端、客户端缓存和下载凭证如何失效。界面显示“可见”不能替代 Manager 对对象和文件的授权判断。
