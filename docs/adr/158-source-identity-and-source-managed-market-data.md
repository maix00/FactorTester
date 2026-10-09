# ADR-158：稳定数据源身份与源管理的行情更新

- **日期**：2026-10-09
- **状态**：已采纳；实现与兼容验收见 Issue #404
- **相关**：[ADR-037](037-research-run-job-persistence-boundary.md)、[ADR-039](039-research-result-artifacts-and-user-quotas.md)、[ADR-116](116-canonical-shared-product-scope.md)、[ADR-148](148-product-definitions-and-submission-snapshots.md)

## 背景

初版因子研究审计把“ResearchRun 未绑定行情字节版本”视为复现缺口，并提议平台级 DataSnapshotManifest、不可变分区引用及不可重放运行确认。用户明确选择了更轻的边界：平台确认使用的是同一个数据源即可；同一源内的行情可能实时更新或被源修订，源自身负责其数据变化与版本生命周期。因而，在同一源内行情变化时重新计算应继续使用该源当前提供的数据。

当前执行计划已把解析得到的数据源 key 与产品、频率、字段和日期范围纳入身份；计划校验不依赖行情文件内容、mtime、大小或行数。Availability profile 的旧 snapshot_ref 则来自文件元数据，并伴随错误的 replayable=true 声明，混淆了来源身份与数据内容版本。

## 决策

### 1. 运行输入身份

- 平台侧的数据来源身份是注册数据源的稳定 key。源身份语义发生变化时，必须使用新的 key；显示名称、路径或当前内容不是身份。
- 执行计划身份包含所选 source key、产品范围、频率、字段、时间范围和其他计算配置。同一个 source key 的行情追加、修订、覆盖或数据更新时间变化不改变计划身份。
- 改选 source key 或修改计算范围/配置仍需重新规划。执行计划校验不得比较数据文件 mtime、大小、行数、footer 统计或统一内容哈希。

### 2. 数据内容由数据源管理

- 新的 ResearchRun/Job 按所选 source key 读取该 source 当前提供的数据。数据源负责数据更新、可用性、读取一致性、缓存失效和其自有历史版本的保留策略。
- 平台不建设统一的行情字节快照、DataSnapshotManifest、revision provider、内容哈希、分区复制或“不可精确重放”确认门禁。
- 如果某个数据源本身支持可寻址的历史版本，它可以继续按自己的接口管理和提供该版本；这不是其他数据源或平台 Run 生命周期的前置条件。
- 用同一 source key 和相同参数再次计算，表示向同一数据源重新执行相同研究请求。数据源内容演进后，结果可以变化；平台不承诺跨演进时逐字节重现旧结果。旧结果及产物仍按 Run/Job/Artifact 自己的生命周期保留。

### 3. Availability profile 的含义

- Profile 是一次来源可用性与覆盖范围的观察，包含 source key、产品/频率、覆盖信息和观察时间；它不冻结所覆盖的行情字节。
- 文件大小、mtime、行数和 Parquet footer 统计只能用于覆盖探测或数据源自身缓存 freshness，不能构成行情内容版本，也不能推出精确可重放。
- 新 Profile schema 不输出元数据型 snapshot_ref 或 replayable=true。Profile schema 升级必须改变请求缓存身份，保留旧 Profile ref 的读取能力，不覆盖或迁移历史观察。
- 旧 schema 的 Profile ref 继续只读可查。API 明确指出旧 snapshot_ref 只是元数据 marker，旧 replayable 字段不保证逐字节重放；读取旧记录不执行行情数据迁移。

## 验收

- source key 不变、数据源内容更新时，已有计划校验通过，新的计算能读取源当前数据；数据内容/时间戳不进入计划 hash。
- source key、产品/频率/字段/日期范围变化时，计划 hash 改变并要求重新规划。
- 新 availability profile 不输出伪数据快照或精确重放声明；升级 schema/cache identity 后，旧 Profile ref 仍可读取并带有 legacy 语义提示。
- 不做数据库 schema 迁移、历史 Run/Job/Artifact 改写、全量行情扫描/哈希或生产数据修复。
