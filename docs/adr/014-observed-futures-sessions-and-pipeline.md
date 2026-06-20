# ADR-014: 观测交易时段与 LocalCNFutures 数据管线

## 状态

已采纳。

## 背景

新品种的本地 MIN1/DAY1 行情可能早于 sectors 元数据出现。若把 sectors 作为交易时段唯一来源，品种虽然可计算，日盘/夜盘 Category 和窗口分析仍会进入未知状态。纯苯 `BZ.DCE` 已有完整行情，但 sectors 暂无记录。

Windows 文件名兼容还使新合约文件采用下划线，而 macOS 历史数据保留竖线。CNFutures 和离线主力生成曾使用不同路径规则，增量生成可能漏读历史文件。

## 决策

1. 从重复出现的 MIN1 bar 端点推断观测交易时段。只保留至少半数交易日出现的分钟，过滤偶发脏数据；连续端点段还原为计划区间，支持跨午夜夜盘。
2. `src_local_cnfutures_observed_sessions` 保存观测日盘段、夜盘段、样本日数、源文件 mtime 和推断时间。
3. 规范品种视图以 sectors 为权威值；完全缺少 sectors 的新品种使用 observed sessions，并通过 `_session_source` 明示来源。
4. Category 先按夜盘是否存在分流。有夜盘按 23:00/01:00/02:30 细分夜盘1/2/3；无夜盘再按日盘计划细分日盘、日盘2、日盘3。
5. 合约 parquet 的便携写入名、旧名候选和解析集中在 `contract_files` Module。运行时与离线生成共用该 interface。
6. 离线脚本统一位于 `sources/LocalCNFutures/scripts/`。轻量 catalog 同步可在应用加载时执行，仅为缺元数据新品种读取一次 MIN1；主力和期限结构生成只能通过显式 pipeline 命令执行。

## 后果

- BZ 等新品种无需等待 sectors 更新即可获得可解释的交易时段 Category。
- 推断值不会覆盖权威 sectors，数据来源可审计。
- macOS 历史竖线文件和 Windows 下划线文件可共同参与增量生成。
- 页面请求不会触发重型 parquet 重建；原始数据更新任务应显式运行：
  `python -m sources.LocalCNFutures.scripts.pipeline --generate-main --generate-term-structure`
- 可用 `--dry-run` 检查变化，或用 `--force-sessions` 全量重算观测时段。
