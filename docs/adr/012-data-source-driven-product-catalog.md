# ADR-012: 行情数据源驱动本地期货品种目录

## 状态

已采纳。

## 背景

`LocalCNFutures` 曾在模块导入时读取 `sectors.csv`，并把其中的行当作全部可回测品种。新上市品种可能已经具备主力分钟、日线、具体合约和展期映射数据，但 sectors 元数据更新较慢。纯苯 `BZ.DCE` 即属于这种情况：行情完整，却因 sectors 缺行而无法进入回测。

`sectors.csv` 同时包含行业、交易时段、历史版本等有价值信息，因此不能直接删除；问题在于它承担了错误的主实体职责。

## 决策

建立 SQLite 本地期货品种目录，分为三层：

1. `src_local_cnfutures_discovered_products`：扫描 `main_mink` 和 `main_dayk` 的实际主力行情文件。至少存在一种主力行情，品种才进入目录。
2. `src_local_cnfutures_sectors`：完整导入 sectors，作为可空的补充元数据快照。
3. `local_cnfutures_products`：以行情发现表为左表，按交易所和品种代码 LEFT JOIN sectors。

`wind_mapping.parquet` 只记录已发现品种是否具有主力到具体合约的映射，不能单独创造可回测品种。OpenCTP 产品与合约规格继续独立提供中文名、乘数、最小跳动、保证金和手续费等增强字段，其在线可用性不控制品种是否存在。

`CNFutures` 只读取规范视图。缺少 sectors 元数据时仍创建品种，中文名回退为品种 alias，行业进入“未分类”，交易时段进入“未知”。

## 后果

- 新品种随本地行情文件出现即可进入回测，不再等待 sectors 更新。
- sectors 可独立更新和审计，且不再是品种存在性的单点故障。
- 目录同步为幂等快照替换；运行中的模块若要看到新增文件，仍需重新加载品种目录。
- 只有 wind mapping、没有主力行情文件的记录不会进入回测，避免产生不可计算的空品种。
