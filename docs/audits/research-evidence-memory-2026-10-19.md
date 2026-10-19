# 研究证据记忆与 Job 结果可读性审计（2026-10-19）

## 结论与边界

推荐建立**可检索的运行证据索引**，不建立另一套 Research Graph、报告正文或生成物权威库。Job/Run、冻结 RunSpec、规范 artifact 及其权限仍是权威来源；索引只保存定位键、紧凑指标、覆盖范围、可用性和来源引用。报告可以引用其中的证据，但不拥有它。Agent 与人工 UI 使用同一个查询 API，返回每条结论所依据的 Run、Job、artifact、样本用途、成本假设和数据源身份。

这次只实施回测结果 Asset Plot 和订单/成交表可读性修复。证据索引的跨模块 schema/API/同步变更应另立 Issue，先用真实 Job 做规模与查询预算验证。不能因为现有旧研究文档曾出现 Graph/TrialPlan 就恢复这些核心对象；当前边界见 [CONTEXT.md](../../CONTEXT.md)、[ADR-037](../adr/037-research-run-job-persistence-boundary.md)、[ADR-156](../adr/156-retire-research-graph-agent-workflow.md)、[ADR-158](../adr/158-source-identity-and-source-managed-market-data.md)。

## 已确认的现状

- Job 的订单、成交、收益曲线等通过注册的规范生成物保存；Job 的低频元数据和结果摘要在持久层。`job_artifact_query` 已提供分页表与按时间范围抽样查询。图像只是生成物的一种呈现，不应成为查询权威。
- 回测结果按声明分为概览、时变指标、交易与账户、收益与风险。订单/成交明细此前直接按原始字段顺序展开，对象字段会撑高行；交易事件与价格分离，难以解释单品种的入场、滑点与离场。本任务调整表格阅读顺序、收起原始对象，并提供同 Job/合约/策略的交易图。
- QuantConnect 的 Asset Plot 将订单事件叠加到行情上，成交标记使用实际成交价；缩放可请求更细行情，订单表与标记联动。其 Research meta-analysis 还支持把回测交易和详细行情并置。这里借鉴交互，不假定该平台的资产/订单模型可直接复制。来源：[QuantConnect Backtesting Results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results)、[Backtest Analysis](https://www.quantconnect.com/docs/v2/research-environment/meta-analysis/backtest-analysis)。

## 检索合同建议

一条 `EvidenceHit` 指向一个 Job 的一个可核查切片：`run_id/job_id/artifact_ref`、owner/权限范围、测试类型、因子冻结 ref 与参数、产品/合约精确成员、产品组提交时快照、数据源稳定 key、频率、样本起止、样本用途（探索/验证/封存）、交易成本与执行假设、指标定义/单位、完成状态和更新时间。可按因子、产品、产品组、任意时间窗口、策略/参数、样本用途与成本口径组合查询；返回原始证据链接与“可比较性”说明。相同因子名但源码/参数不同必须分开；产品组后来改成员不能追改历史 Run。

指标索引只存能从规范 artifact 确定性重建的字段与来源版本。单品种归因若原 Job 只有组合级权益，不得推算为单品种 Sharpe。用户任意窗口若缺少足够密度的原始曲线、交易和成本数据，应标注“无法计算”，不能按整段摘要线性折算。窗口收益、Sharpe、最大回撤要明确日历、收益频率、无风险利率、费用和缺失值规则；窗口边界需处理初始权益/持仓与跨窗交易。多次试验、事后挑选和样本外标签应作为筛选与警示信息，不当成自动认证。

写入触发只在 Job 终态及 artifact 完整性确认后；重试是独立 Job，索引以 Job/生成物引用幂等更新。删除 Job/产物、权限撤销、源离线或跨服务器镜像过期时投影显式失效，查询不能留下悬空的“已验证”结论。跨服务器复用现有 account-domain outbox/cursor/conflict 与对象 Adapter，不让索引成为第二个同步权威。数据源内部实时更新由源管理；新的计算可读取同一稳定源的当前数据，索引必须呈现运行时间与源身份，不承诺旧行情字节精确复现。

## 建议的最小 UI / CLI

人工页面先做一张可筛选表：对象（因子/产品/组）、时间与样本角色、参数、收益/Sharpe/回撤、成本、状态、证据链接；点入 Job 查看原始曲线与订单/成交。相同 API 给 Agent 返回带分页和引用的结构化结果，允许“给因子看各产品各时间”“给产品看各因子”“给任意窗口看可计算结果”。报告编辑器只引用命中的证据，不复制静态指标作为长期记忆。初期不需要新常驻后台任务或全库预计算。

验收预算须先测代表数据：Job 数、artifact 字节数、产品/因子基数、单产品交易数，冷/热查询时间、分页边界、跨服务器离线、删除/权限变更与源更新。可比较性错误与证据遗漏优先于查询速度。
