## Workspace {#workspace}

Workspace 是一次研究或执行活动采用的配置与资源视图，不绑定固定因子家族，也不能阻止研究范围扩大或缩小。

## WorkPackage 与 Branch {#workpackage-branch}

WorkPackage 是研究材料与提交的持久化包；Branch 表示在包内演进的一条研究历史。它们负责隔离研究，不代替具体的因子、FactorSet 或 RunSpec 身份。

## 冻结对象 {#frozen-objects}

具体因子和 FactorSet 可以冻结并获得稳定引用；factor family 是定义和发现入口，不是一次试验的冻结研究对象。RunSpec 冻结测试配置，Job 记录一次执行，Artifact 记录输出。
