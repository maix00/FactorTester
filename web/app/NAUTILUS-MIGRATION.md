# React → Nautilus 字段迁移核对

2026-10-27；代码基线 138875324 后续工作区。只读源码契约核对，不代表真实 Job 验收。

## 当前权威边界

| 页面/对象 | 应使用的来源 | 当前状态 |
|---|---|---|
| Job 配置查看 | Job.run_spec_hash → /api/run-specs/:hash → configuration.payload.analyses.backtest.execution.nautilus_contract | 已接入；只展示有效 Nautilus 契约，不回退旧 configuration/job_spec/execution_plan |
| Venue 与撮合枚举 | nautilus_bridge.native_configuration.native_configuration_schema；capabilities.simulated_venue_config | 数据源属性读取该 schema 的 BookType；完整原生 Venue 编辑尚未接入配置页 |
| 数据源能力 | capabilities.market_data_sources.members，按 member_key 匹配；注册来源快照单独标注 | 已展示 frequency、mode_available、data_kind、market_depth、delivery_mode、supported_book_types 等实际字段 |
| 产品静态属性 | 同一 Nautilus Instrument 转换/注册路径产生的投影 | 仍只有 product-fields 来源元数据，不能冒充完整 Instrument 详情 |
| 历史交易规则 | Instrument 更新、费用/结算等现有规则的权威投影 | 尚无完整 React 审计视图，不在浏览器重算或复制规则 |
| 因子、产品组、数据源身份 | 平台注册目录的冻结 ref / member key | 继续保留，不能当作旧回测字段删除 |

## 已证实的剩余依赖（不能只在前端隐藏后声称完成）

1. `tools/testers/settings/json_schema.py` 从 authoring registry 投影字段，仍包括 initial_capital_major、strategy_book_mode、fee_mode 等。不是直接从 Nautilus 原生 schema 生成完整 Venue 表单。
2. `nautilus_bridge/venues.py:freeze_native_venues` 仍在显式 Venue starting_balances 之外读取顶层 base_currency/initial_capital_major，并保留 nautilus_venue/nt_capacity_policy 等旧草稿继承分支。
3. `nautilus_bridge/run_spec.py:freeze_execution_contract` 仍含这些输入映射；不能先删前端必需输入而让提交断链。
4. `catalog_staging.py` 从来源 point_value 生成 Instrument multiplier；产品元数据 API 目前没有复用该转换结果的完整 Instrument 投影。前端禁止自行另写字段映射器。
5. 因子结果行情请求仍沿用已有 factor-series 纯模型的配置适配；尚需直接绑定冻结数据源与原生运行区间。不得把当前来源行情当作历史冻结数据。

## 后续实现顺序

- 在同一 Issue 的明确后端范围中替换 authoring DTO、冻结编译与校验；原生 Venue 使用 name/account_type/oms_type/starting_balances/native_config，枚举从原生 schema 获取。
- 原子移除对应旧输入/继承分支，再切换前端表单；JSON 和配置项视图保持同一数据，不双写新旧字段。
- 产品详情复用 Instrument 转换的只读投影，来源原始字段作为来源审计保留；静态定义与随时间变化的交易规则分开。
- 真实保存→RunSpec→Nautilus Job 验证，再逐项清除旧 UI 元数据；当前未达到删除旧 Web 条件。

本轮未修改后端或 Nautilus 计算代码。上述清单用于跟踪未接通部分，不把缺口关闭为“完成”。

## 数据领域解耦边界更新

用户确定：产品/数据源保持引擎中立，属性与 Nautilus 完整显式对应；每个数据源独立维护
可选 Nautilus 加载接口；行情、历史规则作为同一 Bundle 的不同成员类型。
见 [ADR-184](../../docs/adr/184-source-owned-typed-bundles.md) 与 [#447](https://github.com/maix00/FactorTester/issues/447)。

因此产品前端不能依赖 Nautilus 实例化后才取得基础元数据；展示来源中立属性，以及适配模块
声明的对应关系和执行能力。Nautilus Instrument 只在适配边界构造。历史规则成员不进入
K 线频率候选。当前仅完成设计与依赖审计，尚未切换注册表、加载和前端成员类型。

### 来源提供方与执行位置

平台来源与用户在电脑客户端添加的来源分别展示、分别授权；不能从“Local”或 provider_kind
推断归属。提供方（platform/user）、执行位置（server/client）、所有者/设备/访问范围应独立。
客户端源不注册为 Manager 的可执行来源；路径、凭据及数据默认留在客户端。服务端任务需要
显式的数据可读性或授权物化，不自动上传、不按同名源替代。当前只是设计约束，尚未添加
完整客户端来源管理 UI 或新远程读取能力。
