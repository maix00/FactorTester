# ADR-162 — NautilusTrader 执行内核与 FactorTester 控制面

状态：拟议；Issue #443 的隔离纵向切片按本决策实现。生产切换须在 T/TL
语义验收后另行决定。

## 决策

每台服务器一个 FactorTester Manager（7998）继续拥有认证、用户、研究对象、
Run/Job、服务发现、配额、报告挂载和 Web/CLI 入口。Manager 管理的业务端口
只提供数据和执行 API，不启动第二个 Manager、控制库或任务权威状态。本机
内网最终仅运行 `feat` 对应的一个业务实例；公网最终仅运行 `main` 对应的
8000 业务实例。过渡期间若已有历史 Job 指向旧端口，Manager 仍须能读取其
冻结结果；停止旧端口不等于删除 Job 或迁移其身份。不得为了实验长期增加
业务端口或部署版本。

NautilusTrader 是目标交易领域内核。它拥有 `Instrument`/`FuturesContract`、
行情事件与 Parquet catalog、历史回测、实时行情上的模拟成交、订单/持仓/
账户/风控及实盘执行适配器。并行 BacktestNode/LiveNode 每进程至多一个，
每个执行进程设硬内存和 CPU 上限；Manager 和 Web 进程不装载整段行情。
连续期货的换月输入由数据供应者提供，NautilusTrader 不负责发现中国期货
主力合约；连续行情不等于可以直接下单的合约。

FactorTester 仍拥有 FactorExpr 的定义、冻结引用、跨频无未来对齐、策略
意图编译、样本内外声明、研究用的品种/产品组分类、权限和研究证据。
回测中的因子由 NautilusTrader 的 `on_bar`/`on_data` 事件驱动，在同一个
执行进程内逐事件更新 FactorTester 的有界状态；浏览器不重算因子，也不预先
物化一份完整因子矩阵供交易读取。NautilusTrader 原生指标可用于等价且已
验证的普通指标，但不能悄悄替代 FactorExpr 的嵌套/跨频算子。预计算序列
仅作逐层对照的离线 oracle，不成为策略运行的另一份权威信号。
回测 RunSpec 以 Nautilus `Venue` 为账户配置边界：每个配置的 Venue 创建一份
模拟账户，持有独立的初始余额、订单、持仓和撮合状态。多个策略可以绑定同一
Venue 并共享这份账户状态；一个 Strategy 也可以向多个 Venue 路由订单。
策略与 Venue 是多对多路由关系，策略不是账户所有者。Nautilus `Portfolio`
提供按 Venue/Account 查询账户和组合状态，不会把各 Venue 的现金自动合并成
可跨场所使用的资金池。

固定的 NautilusTrader `v2.0.0rc7` 每个 `BacktestEngine.add_venue` 注册一个
模拟账户和一套场所撮合状态。一个 RunSpec 使用一个 BacktestEngine，并把行情
与每个 `InstrumentId` 只注册一次；策略按产品的真实 Venue 路由订单。同一
Venue 下的多个策略因此共享余额、保证金、撮合器和流动性消耗，不能各自配置
互相冲突的撮合规则。不同 Venue 各有账户与撮合状态，但行情源仍是同一份输入，
不按策略复制。Venue 初始余额需显式合计到 RunSpec 总资金；目前只支持基础币种，
多 Venue 不会把总资金重复复制到每个账户。

标准 Strategy API 没有跨 Venue 现金转账方法。回测 `SimulationModule` 能为其
所属的一个 Venue 账户提交余额调整，但这只是单账户调整原语，不是跨 Venue
原子转账。当前 RunSpec 不定义自动或策略驱动的跨 Venue 调拨。实盘转账只有在
券商 API 与 Nautilus 对应适配器明确支持时才能执行；策略下单路由本身不等于
资金转账。模拟交易和实盘沿用 Strategy/订单执行接口，但其账户映射来自 Live
ExecutionClient 与适配器：同一 Venue 可以存在多个客户端，账户隔离能力须按
具体适配器和路由验证，不能从回测“一 Venue 一模拟账户”推导为实盘永远一对一。

因子节点只有在相同冻结表达式、参数、产品和时间可用性合同下，才可由一个
共享发布者计算一次并向多个策略分发只读值。回测共享一份行情批次和单一引擎，
避免为账户/策略复制行情和撮合状态；不同 Venue 保留 Nautilus 必需的独立账户
与撮合对象。独立参数试验的账户配置必须显式建成不同 Venue 才会得到独立模拟
账户，但不得伪造 Venue 名称来复制交易所流动性。

现有 ADR-143 策略库是唯一持久策略目录，继续保留所有者、共享权限、不可变
版本、配置内临时策略和 Run 冻结引用。分组/多空、因子阈值、因子交叉等
内置策略作为可版本化的模板进入同一个目录；模板版本保存规则、因子引用、
参数模式和执行能力，不伪装成用户上传的 Python 源码。用户可用已冻结因子
配置声明式策略，也可提交符合 NautilusTrader `Strategy` 合同的自定义代码。
旧 `Strategy` 入口源码需显式迁移或标记只读兼容，不能仅改类名后宣称语义
等价。Web 策略库、回测配置和交易台共用同一策略修订选择器与能力状态；
CLI 使用同一 API。回测、模拟盘、实盘加载同一冻结策略修订，按环境绑定
不同数据、账户、执行和风险配置；缺实时数据、经纪商适配、交易权限或风险
校验时，实盘运行不可用。策略库版本不含实盘凭据或运行中的账户余额。
产品/数据源 UI 应投影 NautilusTrader 的合约与 catalog 可用性，不长期双写
一套交易合约或行情目录。研究分类与数据授权是平台元数据，不是
NautilusTrader 的 `Instrument` 或 Parquet 文件。旧目录在真实中国期货数据
映射、权限与历史 Job 验收前保持只读兼容，不提前删除。

回测结果优先使用 NautilusTrader 的 ReportProvider 和 Plotly HTML tearsheet，
包括订单、成交、持仓、账户、权益、回撤和统计。它们作为 Job 生成物保存，
HTML 通过受认证的结果查看器以隔离沙箱加载，并保留引擎版本、数据源、窗口、
因子及成本配置的来源清单。FactorTester 只补 NautilusTrader 未提供的
因子序列、样本内外比较、研究聚合等视图；不要再次计算另一套账本。

交易工作台由 FactorTester 提供。模拟盘和实盘共用行情、订单、持仓、
账户和风险布局，但状态来源、环境标签、权限及操作命令严格分离；
未配置数据/执行适配器时明确显示不可用，不制造虚假的实时状态。
左侧功能入口单列「交易台」，其内部在模拟盘与实盘之间切换。交易台设置
管理行情连接、券商/柜台适配器与账户映射；每项连接显示环境、权限、健康、
最近对账时间和可用操作。切换模式不能复用另一模式的待提交订单或确认态，
实盘下单有独立的服务端权限与风险检查；连接信息不显示凭据明文。
TradingView Trading Platform 无授权，继续使用已引入的开源
Lightweight Charts 作为实时图表底座。图表只读取后端投影，不得拥有
订单或余额的权威状态。实盘下单必须由服务端验证账户、品种、价格、
数量和风险；浏览器不得直接持有柜台凭据。

NautilusTrader 原生 `nautilus` CLI 用于 catalog、数据库和开发运维，不能
替代 FactorTester 面向用户的因子、产品组、Run/Job、生成物和权限命令。
FactorTester CLI 继续通过 Manager API 访问统一状态；交易命令以后增加
薄适配器，转成同一 NautilusTrader 后端命令，Web 与 CLI 不各自实现撮合。
NautilusTrader CLI 不与 GNOME 的 `/usr/bin/nautilus` 混用，执行时固定
绝对路径和构建版本。

## 数据与任务合同

一次 Run 冻结产品成员、实际可交易合约、数据源身份及可获取的源版本、
时间范围、bar 结束时刻、交易日历、换月表、FactorExpr 版本、策略意图、
费用/滑点/保证金/撮合精度和引擎版本。源不提供字节版本时不得声称完全
可重放；结果页显式说明源可能被更新。`ts_event`、`ts_init`、bar 结束时间
及 signal available-at 不得互相替代。主力连续行情只用于研究/信号，
实际订单需映射到当时可交易合约。

行情 adapter contract 由具体 `DataSourceMember` 提供；通用 Nautilus source
registry 仅校验并解析该契约，不维护供应商名称、列映射或时间语义白名单。
例如 LocalCNFutures 的合约 DAY1 term-structure 文件以 `TRADING_DAY` 日期标签
索引，并在其来源适配器中映射结算价，再用该来源的交易日历得到事件时刻。
此实现只声明 LocalCNFutures 能力，不代表 Nautilus 或其他 FactorTester 来源
都具有相同列、结算价或交易日历。RunSpec 冻结选中的 adapter 身份；不能通过
已验证契约的来源成员必须在提交前失败关闭。

分钟内层因子只在其完整周期的结束事件后更新；外层频率在下一次更新前
只能读取最后一个已完成内层周期的值。日度节点按交易日历给出的真实收盘
时刻发布，不把日期零点或尚未结束的日 K 线当成可用值。NautilusTrader 在
策略回调之后仍可能于相同时间戳撮合零延迟新订单，因此策略意图须明确
最早可执行事件或配置有依据的延迟；不能仅凭 `ts_event <= 当前时间` 就
断言没有同根 K 线的未来成交。回测结果记录信号的生成、可用和首次可执行
时间，并以真实 T/TL 数据逐项核对。

固定的 NautilusTrader `v2.0.0rc7` 在外部 Bar 的 OHLC 依次更新撮合簿后才
调用 `on_bar`，普通零延迟市价单会立即按当前簿撮合。FactorTester 在 Nautilus
撮合器中接通 `AT_THE_OPEN` 市价单：策略在已完成的 Bar 回调中发出信号并提交
订单，撮合器保存待开盘单，在下一根外部 Bar 的原生 open 撮合腿执行；不额外
合成 QuoteTick，也不构造无限深度。旧数据中秒/毫秒混用要先按原字段语义归一
到纳秒并保留来源，不能把这种编码偏差当成新引擎的交易控制。

开盘腿使用 NautilusTrader 从该 Bar 总成交量分配出的本腿成交量，并由
`liquidity_consumption` 让同一开盘腿上的订单共享可用量；撮合继续走现有
FillModel，因此滑点可沿用 Nautilus 模型。这个路径对 OHLC Bar 的四段成交量
分配进行限制，**不等同于可配置的整根 Bar 参与率上限**；RunSpec 当前仍拒绝把
旧 `participation_rate` 静默映射为该机制。执行报告按 Nautilus 的 Bar 到达/处理
时间记录成交事件，同时使用 open 腿的价格，不伪造早于完整 Bar 到达的事件时间。
需要真实价差、开盘竞价、完整 Bar 参与率或排队精度时，必须接入对应报价/深度或
另行扩展容量规则。Bar 按小批次送入，不另存 Quote 面板，也不在前一根 `on_bar`
中读取下一根 Bar。集成验证见 `tests/server/test_nautilus_bridge_bar_timing.py`、
`tests/server/test_nautilus_bridge_backtest_runner.py` 和 Nautilus 子模块的
`crates/execution/tests/integration/matching_engine.rs`；它们不证明中国期货开盘
竞价或真实盘口容量，也不代表通用 Job worker 已接通。

现有 `FactorExpr.compile_incremental` 是接入起点，但其 `SignalAlign` 编译器
目前拒绝日度跨频节点，也不能把所有表达式都视为可逐事件执行。每个冻结
因子须在提交 Job 前完成能力检查；不支持的节点给出明确错误及缺口，不能
静默改用预计算信号。新增交易日收盘节点和 NT 事件适配器须通过分钟/日度
边界、夜盘、缺失 K 线、样本内外切分及同时间戳撮合测试后才能用于原研报
复现。

现有 T/TL 的 Python 结果仅是待解释基线。迁移验收逐层比较原始行情、
嵌套因子、跨频映射、信号、订单、成交、费用、保证金和收益；
先确定差异原因，再决定哪一实现正确。商品期货和实盘不得代替国债期货
研究复现。仅有 OHLCV 时使用有声明的 bar 撮合假设，不推断 L2 排队。

### 随时间变化的交易规则

中国期货的价格跳动、合约乘数、限价下单量、开仓/平仓/平今手续费及多空
保证金须来自数据源登记的权威历史记录，按事件时刻与交易日冻结，并保存
生效时间、公告及数据版本。最新快照、从成交记录反推的交易时段和缺失字段
都不能充当历史规则。费用由实际成交时刻选择；订单创建时刻不能代替成交
时刻。交易时段与逐日结算政策也要有独立的历史版本来源。

具体合约的乘数在运行前逐合约核验并冻结。本机 2026-10-15 的 FieldHistory
快照中，T、TL 在本轮 2025-02 至 2026-05 的区间内均只有 10,000 的
基线记录，没有乘数变更；这不是公网 Job 的数据版本证明，也不能推广到
其他品种。同一具体合约若出现不同乘数，先拒绝运行并核实合约定义；
不在回测中动态切换持仓乘数。

固定上游 `v2.0.0rc7` 的 `BacktestEngine.add_instrument` 对同一合约 ID
仍会新建撮合器。隔离引擎实验证实旧挂单可能保留在缓存中却再不成交；
已有持仓的保证金不会因重登记自动重估。因此可变交易规则事件必须在
回放边界**原子**处理：先结束更早事件，按新精度保留合法旧单并以可审计
事件取消不合法旧单，按生效前已完成的可信行情刷新初始/维持保证金及
账户状态，最后放行同一时刻的行情和新订单。预校验失败须保持旧状态并
中止该 Run；提交期间失败不能继续使用可能只更新一部分的状态。若内核
无法事务回滚规则事件，任何
持久化或回调失败必须使本次回测不可恢复地中止并丢弃运行态，禁止继续撮合
或导出正式结果。

分工以现有扩展点为先：FactorTester 冻结规则及生效时间，利用原有
`FeeModel` 在真实成交时刻选费率；逐笔开仓/平仓/平今类别必须由执行账本
明确给出，不能由买卖方向猜测。同一 ID 的 Instrument 更新需要内核保留
撮合器而非重建；任务分支仅针对这一缺口加了最小修正，并复用已有的
`OrderMatchingEngine::update_instrument`。已有持仓的保证金重估与账户事件
尚未完成，FactorTester 在此期间继续拒绝这类切换。不能靠重复调用
`add_instrument`、直接改缓存或以最新字段覆盖历史来绕开拒绝。
有关实测与待完成验收见 Issue #443。

费用时间轴只在费率变化时保留一条规则；若后续行情快照首次观察到
费率变化的时间晚于公告中的精确生效时间，执行前拒绝该时间轴，不能把
变化误推迟到行情时刻。只有交易日、没有精确时刻的变化尚缺权威交易时段
边界映射，也不能被猜成自然日零点。现有流式冻结入口可使费用时间轴只
保留变化点，避免在内存中保留每根 Bar 的 14 字段快照；
`freeze_fee_schedule_from_history` 进一步只在历史规则精确生效时刻、
交易日切换及区间端点查规则，行情事件仅顺序扫描。仓库合成基准的
1,000 个事件、两条费率版本中，逐事件冻结的单个热样本为
16,396.819 ms，稀疏冻结三个热样本的中位数为 71.238 ms；
该比值只反映小型规则表的 Python 冻结开销，不是整场回测加速比。
同一稀疏路径顺序扫描 100,000 个合成事件的三个热样本中位数为
1,297.278 ms，进程峰值约 138 MB（含 Python、pandas 和规则表）。
真实 T/TL 多合约数据的耗时、峰值内存及源字段完整性仍属切换前
验收门槛。

目录转换的本地数据基线由 `tests/benchmarks/bench_nautilus_catalog_staging.py`
测得：Apple arm64、Python 3.13.9、NT 2.0.0rc7，每次使用新进程和临时
catalog，丢弃首样本，各测 3 个热样本。输入为仓库外的真实
`CFFEX_F_T_2403.parquet`（10,965 根、548,228 bytes）与
`CFFEX_F_TL_2406.parquet`（27,285 根、1,337,803 bytes）；比较每批 512
根和 4,096 根。4,096 根批量在 T/TL 上的中位转换时间分别为 221.021/528.413 ms，
512 根时为 249.454/621.804 ms，分别快约 11%/15%；目录字节减少约 47%/46%。
峰值 RSS 为 4,096 根时约 184/197 MiB，512 根时约 183/204 MiB，未见批量扩大
造成的明显内存增长。因此边界默认采用 4,096 根；
调用者仍可按内存预算调小批量。该测试用占位合约元数据，只验证数据读取、
分批写入与回读成本，不验证交易结果，也不代表完整 Job、生产 p95 或多合约
峰值；正式迁移还须在权威历史字段和真实运行配置下复测。

手续费回调的第一轮隔离基线使用仓库脚本
`tests/benchmarks/bench_nautilus_historical_fees.py`：Apple arm64、Python 3.13.9、
NT 2.0.0rc7，每次新建引擎，首样本丢弃；10,000 根合成 1m Bar、同一合约
10,000 笔交替市价成交、3 个样本。本轮重跑内置零费模型中位 317.744 ms，
FactorTester 历史零费模型中位 340.864 ms，分别约 273.3/273.3 MB 峰值 RSS。
这只量化最密集成交情况下的 Python 回调开销，不是 T/TL 真实数据峰值、
生产 p95 或浏览器耗时；真实冻结数据和资金/持仓事件仍须单独验收。

## 回测配置迁移合同

配置能力的权威流向为 **固定版本的 Nautilus API/配置类型 → FactorTester 能力目录与 RunSpec 编译器 → 前端**。前端只能呈现当前服务返回的能力目录；不能自行维护第二份 Nautilus 参数列表，也不能凭旧字段名称推断等价语义。RunSpec 冻结解析后的参数值与 Nautilus 版本，执行器必须消费这些冻结值；不能消费的参数应标明 `unsupported` 并阻止提交，服务进程负责的运维选项应标明 `service-owned`，不得伪装成用户可选配置。

`BacktestEngine.add_venue` 是 Venue 配置能力面；执行语义另列能力映射。当前 RunSpec 的 `execution_timing=next_bar_open` 由 FactorTester Bar 回调适配为 Nautilus `TimeInForce.AT_THE_OPEN`，并有真实引擎合成成交测试；Nautilus `ExecutionEngineConfig.position_cost_basis` 与 `position_cost_basis_by_instrument` 承载全局 FIFO/LIFO/HIFO/加权平均及稀疏 Instrument 例外。DMTM 的默认、适用产品和例外仍冻结在 RunSpec，但官方结算事件注入与账户入账路径未接通，执行器会拒绝启用。能力目录、RunSpec 审查字段和前端都应显示各自状态，不能把“字段已冻结”当成“执行已支持”。契约测试对照固定 submodule 的 Python stub、RunSpec 映射及执行器构造调用；Rust 配置结构里存在、但 Python 执行入口未暴露的字段不自动算作可用能力。其余 Nautilus 配置类型仍须按同一流向逐项盘点。

现有 `group_test` 表单不能只更换数据源。下表逐一覆盖
`tools/testers/backtest/modules/*` 中公开的 `FieldDefinition`、
`tools/testers/backtest/modules/group/settings.py` 和
`tools/testers/settings/applications.py` 中的提交选项。同名字段可能被策略内层
覆盖，须先解析有效配置再提交。候选列表仅供编辑，不直接传给执行器。

| 字段键 | NautilusTrader / FactorTester 归属与提交门槛 |
|---|---|
| `engine`, `engine_mode`, `counterparty_profile` | 引擎选择收敛为 NautilusTrader；旧模式及经纪商预设先展开为显式费用、保证金、撮合及字段可见性规则。旧引擎值或未能完整解析的模式拒绝新 Job；历史 Job 仍可读。 |
| `data_source_mode`, `data_source`, `freq_mode`, `freq_fixed`, `historical_field_policy` | FactorTester 解析数据源权限、历史字段与覆盖，冻结实际 catalog、`InstrumentId`、`BarType`，映射 `BacktestDataConfig`。源不存在、缺必需字段、严格历史规则缺失或自动选择无法唯一确定时拒绝。 |
| `product_path_candidates`, `product_path_selection`, 策略内 `productMask`、分类/产品组 | FactorTester 冻结成员与连续主力到可交易合约映射；NautilusTrader 接收真实合约。缺规格、成员、换月表或合约映射时拒绝。 |
| `start_date`, `end_date`, `time_precision`, `start_time`, `end_time`, `timezone`, `evaluation_split` | FactorTester 将交易日或精确时刻转成 UTC，映射 `BacktestRunConfig.start/end` 与数据查询边界；样本切分仍是研究合同。交易日收盘、时区或切分不明确时拒绝。 |
| `signal_freq`, `basepoint`, `daily_basepoint`, `end_session_skip`, `end_session_gap`, `calendar_frequency`, `bar_open_visibility_delay`, `bar_end_visibility_delay` | FactorTester 事件时钟与 `ts_event/ts_init` 可用时刻适配器驱动 NautilusTrader 回调。引擎有 Bar 回调、指标更新和定时器，但没有可替代嵌套因子可用时刻的全局开关；夜盘、跨频因果、bar 内可见性未对照的组合拒绝。 |
| `factor_candidates`, `factor_source_selections`, `factor_set_selections`, `factor_role_bindings`, `factor_mode`, `warmup_mode`, `warmup_window` | 候选/来源属编辑器；冻结因子、角色和预热由 FactorTester 有界增量状态实现。不支持的节点、日度对齐或预热拒绝；`precomputed` 不作为交易信号的静默后备。 |
| `strategy_intent_mode`, `split_count`, `group_index`, `screen_rule`, `screen_lower`, `screen_upper`, `threshold_mode`, `entry_threshold`, `exit_threshold`, `quantile_entry`, `quantile_exit`, `side_mode`, `term_carry_near_rank`, `term_carry_far_rank`, `term_carry_entry_threshold`, `term_carry_exit_threshold`, `term_carry_gross_weight` | FactorTester 公共策略库的版本化分组、阈值及 Term Carry 模板计算意图，NautilusTrader `Strategy` 发单。模板、因子角色或范围无效时拒绝。 |
| `position_policy`, `rebalance_trigger`, `allocation_policy`, `sizing_transform`, `volatility_lookback`, `volatility_warmup`, `target_margin_utilization`, `max_margin_utilization`, `margin_utilization_tolerance` | 目标头寸、调仓和预算仍属 FactorTester 策略适配器，读取 NautilusTrader 账户与持仓。未验证杠杆、权重、保证金限额等价时拒绝。 |
| `initial_capital_major`, `base_currency`, `venues`, `strategy_venue_bindings` | RunSpec 固定 Nautilus 原生 Venue、账户类型、OMS 类型、每个 Venue 的 `starting_balances`，以及策略到 Venue 的多对多路由。每个回测 Venue 一份模拟账户；全 Run 使用一个 BacktestEngine，共享行情输入。同 Venue 策略共用账户与撮合状态。Venue 初始余额之和必须等于总资金；跨币种估值及跨 Venue 现金划转当前不支持。 |
| `margin_mode`, `fixed_margin_ratio`, `collateral_fraction`, `margin_call_mode`, `liquidation_target_buffer`, `margin_custom_product_fields` | NautilusTrader 已有 `MARGIN` 账户、`StandardMarginModel`/`LeveragedMarginModel` 及 `liquidation_enabled/liquidation_trigger_ratio`；优先复用。历史保证金变动和旧缓冲/追缴模式仍须逐事件对照，不能假定参数名称相似即等价。 |
| `fee_mode`, `transaction_fee_source`, `fixed_fee_rate`, `fee_custom_product_fields`, `slippage_mode`, `slippage_bps` | Venue 的内置 `fee_model/fill_model` 覆盖固定及按手数等模型；自定义 `FeeModel` 有逐笔回调，但回调未直接收到成交时间。Nautilus 的概率滑点/单跳滑点不等于 FactorTester 旧的固定 bps 滑点，当前 RunSpec 不接受未映射的 `slippage_mode/slippage_bps`；需选用或实现与旧语义一致的 FillModel 并冻结参数后才能启用。平今/平昨与随时间变化的费率须冻结有效期规则，并证明模型在成交时选用正确版本；其他历史字段变动用带事件时刻的 Instrument/规则更新验证。缺历史规则不能拿最新值替代。 |
| `order_type`, `matching_model`, `volume_execution_price_basis`, `liquidity_mode`, `participation_rate`, `quantity_rounding_policy` | 订单与合约最小量映射 NautilusTrader；L2/L3 数据、`liquidity_consumption` 和填单模型可限制可见深度。Bar 有模拟分配成交量，`VolumeSensitiveFillModel` 的 Python 绑定却没有近期量状态更新接口；不能据此宣称已实现按当根 Bar 成交量固定百分比参与。无逐笔/盘口量时，要么采用声明过的上一根量预算，要么明确标为未支持。 |
| `accounting_mode`, `cost_basis_method`, `daily_mark_to_market_enabled`, `use_int_position`, `trading_rule_custom_product_fields`, `force_close_before_expiry`, `rollover_policy`, `rollover_before_expiry` | `cost_basis_method` 已冻结为版本化逐品种政策，并映射 Nautilus `ExecutionEngineConfig.position_cost_basis` / `position_cost_basis_by_instrument`；支持加权平均、FIFO、LIFO、HIFO 默认值及稀疏例外。DMTM 的 Auto/Custom 资格、默认和例外也冻结，但官方结算事件注入、期货变动保证金入账和成本重置尚未连通，`engine_factory` 会拒绝 DMTM 启用的运行；Basic 默认关闭。Nautilus 可处理 `InstrumentClose`，但 FactorTester 仍须从权威数据源提供对应合约、交易日和官方结算价。平今/平昨库存滚动是另一项未完成的持仓/撮合扩展，不能用 DMTM 成本基准替代；未接通时不得宣称该功能已覆盖。 |
| `custom_product_fields`, `equity_compute_live` | 自定义合约/有效时段字段先归一化进 Instrument 与规则适配器；净值实时写入变成结果投影/保留选项，不改变最终权益。未知覆写字段拒绝。 |

动态生成的 `fee_custom_product_fields`、`margin_custom_product_fields`、
`trading_rule_custom_product_fields` 也必须校验。策略 Hook、附加源码和运行时输入
须冻结；旧 Python 策略入口不能未经迁移就作为 NautilusTrader 策略运行。
Run 选项中的 `task_name`、`acting_profile_ref`、`retention_mode`、
`output_requests` 仍由 Manager 管；`step_mode`、`performance_profile`、
`margin_execution_profile` 须实现事件级审计/剖析或在新引擎提交时明确拒绝。
Swift 的 `execution_target`/本地代码包在缺同版本 NautilusTrader 或数据权限时
拒绝；`service_port` 只能指向既定单业务实例。

界面建议收敛为研究范围与数据、因子与策略、资金与账户、费用/撮合/风险、
结果与审计五个主区域，复杂覆写在高级区有条件展开。提交前展示完整的
“有效执行配置”，逐项标注“NT 原生 / FT 适配 / 未支持”，服务端重复验证，
不允许隐藏但仍生效的旧字段被静默丢弃。T/TL 验收必须逐层比对因子、信号、
订单、成交、费用、保证金、权益及样本内外，不只看最终收益率。

T/TL 冻结证据的当前界限：本地研究稿
`/Users/maxdeux/Documents/GTHT/reports/ft_ht_duration_T_TL.md` 记录研究范围
2024-01-02 至 2026-05-27、样本内截止 2025-06-30、样本外始于
2025-07-01，但其回测章节仍标“待跑”。
`ft_run/ft_dayscope_index.json` 中 DFP:10d 的冻结引用为
`factor:v2:nupERUpfhFNGFIB4AT3UfJiJaTRbaC0r5V1nUU9R6aM`，别名包含
`TsDurDevDayScope`、内层 `SgChgDurDay` / `SgChgPct`、`M:0.6`、
`B:1`、`N:250d` 和外层 `N:10d`、`$F:30m`。
`run/matrix_results_all.json` 中 T 10d Job `48e49b3569804312a47b2333ca6804cf`
及 TL 10d Job `31b43a58677d43f5bcab41e1d81c9ddc` 为成功状态，
但该摘要不含 Job 冻结配置、数据源字节版本或逐层因子值；不能据此认定
二者使用了上述引用、确切样本分割或已复现原研报。取得权威 Job 快照后
才建立逐层 T/TL oracle 与 NautilusTrader 差异回归。

以上 NT 可用入口来自 pinned 上游
`vendor/nautilus_trader/python/nautilus_trader/backtest/__init__.pyi`
（`BacktestDataConfig`、`BacktestRunConfig`、`BacktestVenueConfig`、
`BacktestEngine.add_venue/add_strategy`）与
`vendor/nautilus_trader/python/nautilus_trader/execution/__init__.pyi`
（`FillModel`、`FeeModel`）。可扩展入口**不等于**已实现中国期货平今费、
逐日结算或旧撮合语义。

## 分阶段实施与回退

1. 固定开源 NautilusTrader 标签及 commit，作为 submodule；隔离构建环境
   生成可校验的 wheel/二进制，生产主机不在每次发布时重编整个上游。
   检查 LGPL-3.0 和第三方许可。在任务 worktree 做离线合成验证；实际服务
   验收使用本机 `feat` 的唯一业务实例，不新增长期端口；首个切片仅输出
   能力及一项真实的 NautilusTrader 报告，无下单能力。
2. 把中国期货 T/TL 合约及历史数据只转换一次进独立 catalog；记录
   count、时间/合约覆盖、数据质量、转换耗时、峰值 RSS 和磁盘字节。
   跑一个冻结因子策略及原生报告，并接入现有 Job 生成物/结果查看器。
3. 接入真实行情到 NautilusTrader sandbox；构建 FactorTester 模拟盘界面，
   校验订单生命周期、断线、恢复、账本和图表。无真实订单通道。
4. 完成中国期货执行适配、柜台回报/对账和风险联锁后，才允许实盘界面
   提交订单。生产切换、旧执行器删除、旧数据迁移分别审批。

替换执行器时先完成真实 T/TL 结果对照与历史 Job 只读回放，再按引用清单
删除旧 Python/其他回测框架和多业务端口部署路径。数据或结果仍被引用时不
删除其读取合同；删除执行代码不意味着可删除用户 Job 生成物。任一阶段验收
失败，回退到先前的 `feat`/`main` 应用版本，Manager、控制库和历史 Job 不变。

## 依据与边界

本隔离切片固定上游标签 `v2.0.0rc7`、提交
`55c0e82053142bce3a5cba4de4221d3929c2d3bc`。Mac M4、Python 3.13.9、
预编译 wheel、12 根合成分钟 K 线的单次热导入实验中，回测约 0.195 秒、
原生报告导出约 0.199 秒，进程峰值 RSS 约 214 MiB；五份报告约 4.83 MB，
含两笔成交及账户保证金变化。该实验由
`tests/server/test_nautilus_bridge_integration.py` 复现，只证明桥接可用，
不能作为中国国债期货真实数据的性能或收益结论。真实 T/TL 迁移前需补充
数据规模、冷/热缓存、重复样本、内存和交易语义对照。

- NautilusTrader 官方提供 BacktestNode、SandboxExecutionClient、LiveNode、
  ReportProvider 和 Plotly tearsheet；开源路线不包含完整 Web 交易后台。
- 一进程同时运行多个 Nautilus 节点不受支持；工作进程隔离和资源硬限额
  是部署合同，不因为内核由 Rust 编写就自动省略。
- TradingView Trading Platform 是另行许可的交易界面，本项目无该许可。
- 现有 ADR-037/038/161 的 Run/Job 权威性、单 Manager 与开源图表边界
  在迁移前继续生效；本 ADR 的新目标通过各阶段验收后替代其中的执行
  内核归属，而非立即使历史决策失效。
