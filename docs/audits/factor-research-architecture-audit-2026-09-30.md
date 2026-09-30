# FactorTester 因子研究架构缺陷与改进清单

- 审计日期：2026-09-30（Asia/Taipei）
- 基线：本机缓存 `origin/feat@9d35ee47f33cbc756103626a9a9eaeeb57631030`（本次 GitHub fetch 因 HTTP/2 framing error 失败；不据此声称已核实最新远端 HEAD）。
- 范围：研究数据身份、RunSpec/ExecutionPlan、因子源码版本、受保护样本暴露、因子执行后端、研究报告协作及相关 Issue/ADR 状态。
- 证据边界：以下标为“已证实”的项目由当前源码、测试或仓库记录直接支持；这不等于已证明生产历史结果实际出错。未实际访问生产业务数据，也未运行生产任务或迁移。

## 结论与当前架构基础

FactorTester 已有若干成熟的核心边界：因子 DSL 的批量/增量执行分离、冻结的因子身份和源码版本、产品组与提交时产品范围快照、RunSpec/ExecutionPlan/Job 生命周期、研究图与版本化 TrialPlan、受保护样本暴露检查、结果 artifact 哈希、因子集合成员历史以及跨服务器研究目录基础设施。统计设计已把比较、样本角色、停止规则和多重检验计划纳入 TrialPlan；本审计没有证据支持“平台完全没有多重检验机制”这一说法。

目前最重要的不足集中在研究证据的不可变性：行情内容版本未绑定到运行身份；保护样本只比较完全相同的产品范围；运行时因子版本校验仍依赖当前目录，即使 RunSpec 已冻结历史公式。这些边界会影响可复现性和 holdout 防泄漏，应优先修复。

## 成熟研究架构参照

公开实现提供的是可借鉴的工程模式，不是必须照搬的规范：Microsoft Qlib 将行情数据准备、Data Loader、Data Handler、Dataset 与缓存分层；其 Experiment/Recorder 按实验组织单次运行，并保留参数、指标和 artifacts。Alphalens 的输入显式关联日期、资产、因子值和多个前瞻收益期，再计算逐期 IC。mlfinlab 的交叉验证实现将标签信息区间用于 PurgedKFold，并支持 embargo，体现了时间区间重叠应进入验证边界的原则。

据此，本平台的成熟度差距不在“缺少一个通用因子平台”，而在已存在的 RunSpec、TrialPlan、Job 与 artifact 是否都指向可复核的数据/源码版本，以及保护样本和标签时间范围能否证明没有重叠。已有 Qlib 风格的数据/执行层、运行记录和结果产物，以及 TrialPlan 里的比较与多重检验计划；改进应补齐它们之间的不可变身份和可验证契约，不重复造一套实验跟踪系统。

参考： [Qlib 论文](https://arxiv.org/abs/2009.11189)、[Qlib 数据层文档](https://github.com/microsoft/qlib/blob/main/docs/component/data.rst)、[Qlib Recorder 文档](https://github.com/microsoft/qlib/blob/main/docs/component/recorder.rst)、[Alphalens IC API](https://alphalens.ml4trading.io/api-reference.html)、[mlfinlab PurgedKFold 实现](https://github.com/hudson-and-thames/mlfinlab/blob/master/mlfinlab/cross_validation/cross_validation.py)。

## 已证实缺陷与能力缺口

| ID / 优先级 | 发现与证据 | 影响与改进方向 | 状态 |
| --- | --- | --- | --- |
| F-01 / P1 | **保护样本暴露检查漏掉部分产品范围重叠。** `trial_plan/binding.py` 的查询按 `sample_universe_hash` 完全相等、日期相交来查历史暴露；`trial_plan/sample_identity.py` 明确列出 `partial_universe_overlap_not_detected`。现有测试主要覆盖相同 universe 的重复使用。 | 一个验证/holdout 运行可以换成部分重叠或超集产品，当前检查不会识别既有暴露。保存服务端规范化的具体产品成员/可比较范围，并在日期区间与产品集合均相交时阻止受保护样本重复暴露；无法无歧义展开的范围应拒绝受保护角色或显式降级为不可证明，而不能静默放行。 | 已建立 [Issue #402](https://github.com/maix00/FactorTester/issues/402) 并登记独立 Claim；实现待验收。 |
| F-02 / P1 | **RunSpec 没有绑定行情内容版本。** `single_factor_test/planning.py::_backtest_plan` 冻结源标签、产品、频率、字段与日期；`build_execution_plan` 的哈希和缓存键没有行情 revision。`tools/data/availability/parquet_footer.py` 的 `snapshot_ref` 来自文件大小、mtime、行数等元数据；`derive_sample_identity` 明确列出 `data_snapshot_identity_not_bound`。`research_cycle/data_availability_evidence.py` 也将数据 checksum、日历、合约成员 vintage、session/timezone 等列为未决维度。 | 同一 RunSpec 重试时不能保证读取相同 bars，也不能充分证明当时可用的数据版本、调整方式和交易日语义。增加服务端冻结的 Data Input Manifest/分区引用；数据读取、计划哈希、缓存键、重放和证据收据共用该引用。源不支持稳定版本引用时，明确标记不可精确重放并要求确认。当前没有验证到具体线上历史任务发生漂移。 | 待建 Issue 与设计；不得用文件 mtime 冒充内容校验和。 |
| F-03 / P1 | **冻结因子历史版本与 RunSpec 校验路径不一致。** `factor_revisions.py::assert_run_spec_factor_revisions_current` 对已经冻结的 RunSpec 再调用 `_assert_factors_current`；`planning.py::build_execution_plan` 在规划/验证时调用它。另一方面，`factor_param_resolver.py::_resolve_frozen_factor` 和 ADR-146 支持按冻结 fingerprint 加载历史源码。当前 `test_factor_revision_manifest.py` 覆盖“当前公式变化后报错”，没有覆盖“冻结 v1、编辑到 v2、旧 Run 仍解析 v1”。 | 当前目录变化可能挡住仍能按历史 fingerprint 精确解析的冻结 RunSpec，削弱重试和复现。新 Run 冻结时检查当前目录；冻结后的执行只按不可变 ref/fingerprint 解析历史源码和依赖，历史字节缺失、哈希不符或身份不完整时才失败。完整重试影响范围尚需回归测试确认。 | 待建 Issue 与冻结后编辑回归测试。 |
| F-04 / P2 | **`groupby_scope(trading_day)` 在外部回测适配器上没有交易日来源。** `FactorStepAdapter.update` 支持显式接收 `trading_day`，但 Qlib、Backtrader、Zipline 的因子适配器调用没有传入该值。核心现在会显式拒绝缺少交易日的流式计算，避免把夜盘错误归到日历日。 | 三种 worker 后端上无法使用交易日作用域增量因子。应从框架/数据源的权威交易日映射透传；没有权威信息时继续显式拒绝。该项属于 #397 的现有写入范围/Claim，本任务不接管也不修改其文件。 | #397 仍 OPEN，保留现有 Claim，等待该任务结束后再评估。 |
| F-05 / P2 | **旧 publication 的 fork 兼容尚未完成。** Issue #396 的验收说明指出旧 main publication 没有 authoring bundle，writer branch 表为空，因此无法按新协作协议 fork；Issue #396 仍 OPEN、`ready-for-agent` 且没有 Claim/完成记录。 | 用户无法从某些旧报告准确继承可编辑章节和附件。应提供显式、幂等的兼容准备流程；缺源码或资源时明确拒绝，不能从渲染文本伪造，也不能建空分支冒充 fork。 | 下一项或随后按优先级处理；必须按 #396 Ownership 实施。 |
| F-06 / P2 | **ADR/上下文与真实实现状态不一致。** `CONTEXT.md` 写标准 Conda 环境为 `ft`，`docs/development-environment.md` 写为 `GTHT`。ADR-148/#381 与 ADR-149/#382 仍写“实施中”，但对应 Issue 已关闭且记录了双端集成/部署验收。ADR-154/#394 仍称协作分支未发布/待实现，而 #394 的 Done-by 记录包含跨端部署验收；旧 publication 兼容另由未完成的 #396 跟踪。 | Agent 会重复实现已完成能力，或按过时的环境说明运行测试。应更新知识入口与 ADR 的当前状态，明确已完成能力和 #396 遗留的旧 publication 边界；不要把活动中的 ADR-155/#397 标成完成。 | 本分支已更新 `CONTEXT.md` 和 ADR-148/149/154；待差异检查与提交。 |

## 顺序化改进队列

按研究结论可信度、回归风险和依赖排序。每项单独建 Issue（已有 Issue 则复用），按其 Ownership 在独立分支/工作区实现并跑聚焦测试；跨模块 schema、API 或数据迁移先写验收与兼容策略。当前请求没有授权 feat/main 集成、推送、生产迁移或部署。

1. **保护样本的部分范围重叠检查（F-01，P1，Issue #402）**：保存足以比较产品交集的规范范围，并覆盖相同集合、子集、超集、无交集、日期交叠、历史记录缺范围、重试和并发绑定。
2. **冻结行情输入身份（F-02，P1）**：先完成 source/partition revision 能力盘点，再定义 Data Input Manifest；验证源内容原地变化、冷/热缓存、重试、旧数据源和缺少稳定版本时的显式状态。不得宣称元数据 hash 是数据内容 hash。
3. **统一冻结因子解析（F-03，P1）**：先复现 v1 freeze → 当前源码编辑为 v2 → v1 Run 重试；验证嵌套依赖、历史源码缺失和新 Run 的当前版本门禁。
4. **旧报告 publication fork 兼容（F-05，P2，Issue #396）**：复用已有对象传输与 branch 协议，验证旧 publication、资源完整性、重试、权限和不同 Profile 身份。
5. **外部框架交易日透传（F-04，P2，Issue #397）**：等现有 Claim 完成后复核，不与活动写入者重叠。
6. **研究执行方法学验证（P2，待审计）**：用合成价格序列校验 IC/收益滞后、异步产品时间对齐、费用/滑点、截面排序、缺失值和多重检验实现；当前 TrialPlan 有设计结构，但需逐个核实执行结果、失败边界和证据绑定，不能仅凭 schema 断言统计实现正确或缺失。
7. **决策策略与执行能力矩阵（P2，待审计）**：ADR-046 的 `待实现` 状态需要与现存 entry/exit、订单生命周期、流动性、Buying Power、策略净额化实现和测试逐项核对；只为确实缺少验收的语义创建后续任务。
8. **真实规模性能基线（P3，待审计）**：记录真实数据规模、对象大小、机器/运行时、缓存冷/热、样本数与耗时分布后，再优化列表目录、因子求值和 Job/报告传输。当前审计没有生产负载基线，不对线上 p95 作判断。

## GitHub Issue 生命周期与范围复核

本次在 2026-09-30 定向审阅了近期提交与因子研究/回测/研究报告相关的 OPEN Issues。无法访问 GitHub 最新远端时以本机缓存 `origin/feat@9d35ee47` 和 Issue 当前可读生命周期记录交叉检查；没有做全仓所有领域 Issue 的关闭扫描。

### 有 Done-by/Released-by、且引用提交已进入本机 origin/feat 的 OPEN 候选

下列 Issue 仍显示 OPEN，评论里有完成、合并或部署记录，且本机缓存的 `origin/feat` 提交历史包含对应 `refs #N`：

- 2026-09：[#388](https://github.com/maix00/FactorTester/issues/388)、[#389](https://github.com/maix00/FactorTester/issues/389)、[#390](https://github.com/maix00/FactorTester/issues/390)、[#391](https://github.com/maix00/FactorTester/issues/391)、[#392](https://github.com/maix00/FactorTester/issues/392)、[#393](https://github.com/maix00/FactorTester/issues/393)、[#394](https://github.com/maix00/FactorTester/issues/394)、[#395](https://github.com/maix00/FactorTester/issues/395)、[#398](https://github.com/maix00/FactorTester/issues/398)、[#399](https://github.com/maix00/FactorTester/issues/399)、[#400](https://github.com/maix00/FactorTester/issues/400)、[#401](https://github.com/maix00/FactorTester/issues/401)。
- 2026-08：[#351](https://github.com/maix00/FactorTester/issues/351)、[#352](https://github.com/maix00/FactorTester/issues/352)、[#355](https://github.com/maix00/FactorTester/issues/355)、[#359](https://github.com/maix00/FactorTester/issues/359)。#355/#359 有生产部署回执；#351/#352 有部署验收回执。
- 2026-05 至 06：[#63](https://github.com/maix00/FactorTester/issues/63)、[#64](https://github.com/maix00/FactorTester/issues/64)、[#65](https://github.com/maix00/FactorTester/issues/65)、[#67](https://github.com/maix00/FactorTester/issues/67)、[#74](https://github.com/maix00/FactorTester/issues/74)、[#77](https://github.com/maix00/FactorTester/issues/77)、[#79](https://github.com/maix00/FactorTester/issues/79)、[#81](https://github.com/maix00/FactorTester/issues/81)、[#118](https://github.com/maix00/FactorTester/issues/118)、[#120](https://github.com/maix00/FactorTester/issues/120)。其中一些评论只证明本地合并或单测，仍要核验其最终实现/验收目标是否完整，再决定是否关闭；“提交进入 feat”本身不是完整验收证明。

### 仍需保留、重新认领或解决父子范围的 OPEN Issues

| Issue | 复核结论 |
| --- | --- |
| [#402](https://github.com/maix00/FactorTester/issues/402) | 本审计第一项的独立实现 Issue，已 Claim；实现和测试未完成。 |
| [#396](https://github.com/maix00/FactorTester/issues/396) | 旧 publication 缺失 authoring bundle 的 fork 兼容缺口；未见完成记录，保留。 |
| [#397](https://github.com/maix00/FactorTester/issues/397) | `groupby_scope` 有活动写入 Claim 与适配器交易日来源缺口；不接管、不改其范围。 |
| [#173](https://github.com/maix00/FactorTester/issues/173) / [#182](https://github.com/maix00/FactorTester/issues/182) | #173 是 IC 方法学/语义母 Issue，#182 是实现切片；#182 有 Claim 但长时间无新进展。不是重复单，应核验实现 worktree 后决定续作或调整范围。 |
| [#302](https://github.com/maix00/FactorTester/issues/302) / [#304](https://github.com/maix00/FactorTester/issues/304) | #302 明确是父/产品决策与验收总项，#304 是 Delay 批次和多产品范围 Job 切片；均无完成评论，保持父子关系。 |
| [#114](https://github.com/maix00/FactorTester/issues/114) / [#121](https://github.com/maix00/FactorTester/issues/121) / [#129](https://github.com/maix00/FactorTester/issues/129) | #121 明确取代 #114 的架构部分；#129 是要求审查异步计算计划的独立只读交付，但目前未见审计结论。需要按现存 `tools/backtest/`、Job/SSE 实现和 ADR-009/010 逐项核销，避免继续在旧原型和新架构上重复工作。 |
| [#314](https://github.com/maix00/FactorTester/issues/314) | 仍为账本/资金池结果能力，依赖 #312；无完成评论，不属于可关闭候选。 |
| [#78](https://github.com/maix00/FactorTester/issues/78) | 只有旧 Claim 评论、未见完成回执；需检查原 Claim/worktree 与当前测试后重新认领或关闭。 |
| [#127](https://github.com/maix00/FactorTester/issues/127) | 具体期限结构/Carry 因子能力缺口；未见完成回执，保留待范围核验。 |
| [#384](https://github.com/maix00/FactorTester/issues/384) | 最新记录按用户要求暂停；不视为完成。 |

此外，2026-05 至 06 的其他 OPEN 旧条目仍在因子/回测搜索结果中；这次没有据标题猜测已完成。下一次范围复核应读取 Issue 全文、生命周期评论、最新 worktree/Claim，再把可确认的已实现工作写入 `Done-by`，不将历史本地合并误认为部署。

仓库规则要求 Issue 关闭单独授权，因此本次只记录候选与范围关系，没有调用关闭操作。工作区/任务分支的归档与清理同样不在本审计授权范围内。

## 已审查但未认定为缺陷的部分

- TrialPlan/Research Graph 已表示样本角色、比较计划、停止和多重检验设计；应继续验证执行/证据，但不应把“缺少统计设计模型”列成已证实缺陷。
- RunSpec 已冻结因子身份、配置版本、产品范围和部分生成物；问题在于行情数据输入及历史因子版本执行门禁仍不完整，不是所有运行输入都未冻结。
- 交易日作用域缺失会显式失败；这是后端能力缺口，不是当前观察到的静默错误结果。
- 本审计没有证明特定用户、研究报告或生产回测数据已因此产生错误结果。
