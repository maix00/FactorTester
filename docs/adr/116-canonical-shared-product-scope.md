# ADR 116：冻结配置中的规范共享产品范围

## 状态

已接受，针对 Issue #279。

## 背景

冻结配置过去在 analysis、local-setting 和 UI 投影中重复可执行设置。产品选择还把 `paths` 重复为 `selected_paths`，留在单个 analysis 下，并可能依赖可变的产品组/分类行。若冻结整个目录和数据源投影，就会把运行时所有者的 provider 元数据和完整产品目录复制进每个 RunSpec，而执行并不会因此改变，因为 worker 会通过已部署源注册表解析稳定 source ID。

## 决策

- `shared.product_selections` 是所有所选 analysis 使用的产品范围唯一冻结表示；analysis 和策略组只保留稳定 selection ID。
- 一个 selection 只保存规范 `paths` 数组，不再同时保存 `selected_paths`。
- 已有产品分类冻结稳定元数据和定义 SHA-256；其已解析 selection paths 已包含执行语义。
- 配置内分类冻结完整 item 定义，因为外部目录行无法恢复。
- RunSpec 只保存选定的数据源或 bundle ID。provider 成员、频率目录、时区、字段映射、能力维度、命名方案、可用性和产品数由部署源注册表所有，不复制进 configuration。
- UI 候选目录和重复可执行 UI 设置不冻结。等价因子 alias 及重复的 owner/family/parameter 投影规范化，但不删除 revision manifest 或哈希。
- 源 Manager 在 capability preview 和提交前各执行一次相同的冻结；Web、Swift、CLI 和联邦消费同一接口。
- 因子或可执行分类源码由不可变内容哈希及生成物/源码传输引用表示；RunSpec 不为自包含而重复实现文本。

## 后果

历史执行不依赖可变产品组行；内嵌对象保持模板安全，不插入账户目录表。数据源身份和可用性在选定执行节点检查。可复现性依赖选定 ID 与部署执行版本，而不是 RunSpec 中未使用的 provider 快照。配置大小只随真正执行的对象增长，不随可见源/产品目录增长。
