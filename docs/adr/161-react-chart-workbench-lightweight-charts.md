# ADR-161 — FactorTester 图表工作台与 Highcharts 渐进退出

状态：已接受（Issue #440，2026-10-20）。

## 决策

以 FactorTester 自己的因子—策略—交易—结果链路为工作台核心。React + TypeScript 是独立延迟挂载的界面边界，Lightweight Charts 只负责可交互绘图。FactorExpr、增量因子计算、Strategy Intent Policy、订单撮合和 Job/Run 结果继续是权威来源；浏览器不得用图表插件重新计算因子或盈亏，也不得把因子值当作可交易价格。

首阶段只 fork [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) 到 [maix00/lightweight-charts](https://github.com/maix00/lightweight-charts)，并以 `third_party/lightweight-charts` Git submodule 固定 v5.2.1 / `b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1`。官方 npm 同版本的 standalone 浏览器产物经固定 SHA-512 完整性校验后纳入 `static/vendor/lightweight-charts/`，构建和运行无需在生产主机下载依赖。Apache-2.0 `LICENSE`、`NOTICE` 随产物保存；启用图表时保留库自带的 TV 署名标识，不重复添加文字标注。两个社区指标/绘图仓库尚非纵向链路必需，不作为 submodule 引入；只有具体功能需要、API 与许可核查通过时再单独决策。

新工作台先挂接现有认证、路由及 Job 结果 API。K 线、FactorTester 计算的因子序列、策略信号、目标仓位、订单状态、成交、实际持仓、权益与回撤按同一时间轴展示；量纲不同时使用独立价格尺度或窗格。交易与盈亏只依据真实可交易合约的行情和既有执行规则。结果明细与 Job 生成物保留可审计来源，图表不持有权威状态。

## 渐进迁移

1. 建立独立 React/TypeScript 打包与按需挂载边界，先用产品行情页验证 K 线、成交量、持仓量及范围请求；证明 Manager 和 macOS 嵌入 Web 均可从本地静态资源加载；首屏不得因此预载图表库。
2. 以一条冻结因子曲线、一个策略规则和一个真实行情回测 Job 验证端到端数据合同。优先迁移交易图 Asset Plot，逐项覆盖 ADR-160 的行情源范围加载、原始频率、同刻多事件、订单生命周期、账本字段、价格线和缺失数据语义。Asset Plot 已在任务分支完成浏览器迁移验证；冻结因子曲线、策略规则及完整端到端合同仍须单独验收，不以合成浏览器数据代替真实 Job。
3. 将公共价格查看器、因子序列、IC 与其他 Job 图表逐个迁移；每个入口在数据/交互/性能验收通过后才移除对应的 Highcharts 脚本声明。
4. 最后删除 Highcharts 共享适配器与静态资源。迁移前不能因新图表存在就删除旧资源。

交易图的范围选择、双向滚轮缩放与最小源频率均需保持。样本稠密时的绘制抽样不能删除事件锚点或改变成交/行情数值；未记录的 Level 2、保证金或订单阶段不得凭图表推断。旧图表是逐入口可回退路径，不做双份权威计算或结果存储。

## 验收与回退

逐入口核对同一 Job/合约/时间范围的源 bar、因子值、事件 ID、逐笔账本与策略/账户/资金池筛选结果；覆盖空值、历史 Job、乱序范围响应、移动端尺寸和 macOS 嵌入。记录冷/热加载体积与交互延迟，避免把 Node 合成数据误称为浏览器性能。未通过的入口保留 Highcharts；回退只恢复该入口的渲染选择，不修改 Job、数据库或因子结果。
