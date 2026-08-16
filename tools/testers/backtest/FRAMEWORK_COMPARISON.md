# FactorTester 回测框架与主流框架对比

本文记录当前 `tools/testers/backtest` 的架构定位、相对行业主流框架的差异、优势、短板和后续取舍。

参考对象按行业常见使用方式分为四类：

- 事件驱动交易仿真：Backtrader、Zipline/Zipline Reloaded、QuantConnect LEAN、vn.py、RQAlpha。
- 向量化研究框架：vectorbt、Backtesting.py 的轻量研究路径。
- AI/因子研究平台：Qlib。
- 本仓外部框架桥：Backtrader、Qlib、Zipline worker，以及预留 RQAlpha。

相关公开资料：

- Backtrader 官方文档：市价单默认在下一根 bar 的开盘价成交，broker 支持 commission/slippage 模型。<https://www.backtrader.com/docu/quickstart/quickstart/>、<https://www.backtrader.com/docu/commission-schemes/commission-schemes/>、<https://www.backtrader.com/docu/slippage/slippage/>
- Zipline 3.0 文档：定位为 Pythonic event-driven backtesting system。<https://zipline.ml4trading.io/>
- QuantConnect LEAN 文档：跨资产、研究、回测、优化、实盘的一体化引擎。<https://www.quantconnect.com/docs/v2>、<https://www.lean.io/>
- RQAlpha GitHub：可扩展、可替换、支持多证券的 Python 回测与交易框架。<https://github.com/ricequant/rqalpha>
- vn.py GitHub：面向实盘交易应用，CTA 策略引擎强调订单管理细粒度控制。<https://github.com/vnpy/vnpy/blob/master/README_ENG.md>
- Qlib 官方资料：AI-oriented quantitative investment platform，覆盖数据处理、模型训练、回测、组合优化、订单执行等研究链路。<https://github.com/microsoft/qlib>、<https://qlib.readthedocs.io/>
- vectorbt 文档：基于 pandas/NumPy/Numba 的高速向量化量化分析与回测。<https://vectorbt.dev/>

## 当前框架定位

FactorTester 当前不是单纯的事件驱动框架，也不是单纯的向量化回测库，而是一个“因子研究页面驱动的模块化回测运行时”：

1. 因子作者接口是 `FactorExpr` / `FactorFamily`，不是用户手写 `Strategy.next()`。
2. native 引擎用 `ExecutableModule + Flow + EventQueue` 表达数据准备、信号、交易意图、订单、账本、结果整理。
3. 前端/CLI 的可编辑字段由后端模块注册，`visible_if`、`editable_if`、默认值、chip、tab 都来自同一套字段定义。
4. 分组策略是一个比较完整的业务全家桶：因子信号、分组数、分组序号、分配方式、调仓策略、派生组 mask、订单登记等集中在 `GroupMembershipModule`，避免为了“纯粹分层”切成过多浅模块。
5. 外部框架不挂 native 的 event queue，而是通过 worker bridge 把同一份策略配置翻译给 Backtrader/Qlib/Zipline 等框架，让它们按自己的规范运行。
6. 资金、账本、StrategyBook、CashPool、TradingRule、Margin、Fee、DMTM 等语义正在向更接近真实账户和交易规则的方向演进。

一句话：它更像“因子实验室 + 可解释回放器 + 多框架一致性桥”，而不是一个单独给用户写策略脚本的通用交易引擎。

## 与主流框架的主要不同

| 维度 | FactorTester 当前方向 | Backtrader / Zipline / LEAN / vn.py / RQAlpha | vectorbt / Backtesting.py | Qlib |
|---|---|---|---|---|
| 用户主接口 | 因子族、参数、产品路径、分组/IC/分析模块 | 用户编写策略生命周期回调 | 用户给出价格、信号、组合规则，偏研究脚本 | 数据集、模型、策略、执行器工作流 |
| 运行核心 | 模块注册的 Flow + causal EventQueue | 事件驱动 loop，broker/order/portfolio 内置 | 向量化数组或轻量事件循环 | 研究 pipeline + executor/exchange/account |
| 字段来源 | 后端模块注册为前端/CLI manifest | 代码参数/API 为主 | Python API 参数为主 | YAML/配置/实验管理为主 |
| 因子计算 | FactorExpr 批量预计算或未来增量执行；同一信号可喂 native/worker | 通常在策略回调内手写指标或接 indicator | 强项是向量化指标与参数扫描 | 强项是 ML 因子、模型训练、组合优化 |
| 分组测试 | 一等公民，分组、派生组、Long-Short、产品路径、trace 都是业务语义 | 需要用户自行实现组合和分组逻辑 | 可快速矩阵化，但解释链路要自己补 | 可做组合策略，但不是围绕本页面分组业务定制 |
| 真实交易规则 | 正在显式建模历史字段、涨跌停、DMTM、保证金、费率、期限结构 | 成熟 broker/exchange 模型，但国内期货规则需适配 | 通常较简化 | 有 Exchange/Account 概念，但国内期货细节仍需定制 |
| 可解释性 | 目标是 snapshot/trace/order-flow/flow progress 全链路追踪 | 订单/交易日志成熟，但因子分组 trace 不是默认业务 | 快，但细节 trace 往往弱 | 实验指标强，逐单回放解释不是核心 |
| 多框架一致性 | 显式目标：同一配置跑 native 和 worker，对齐 target/equity | 单框架为主 | 单框架为主 | 单平台为主 |

## 优势

### 1. 领域入口更贴近“因子测试”

主流事件驱动框架一般从“策略代码”开始，用户要自己把因子排序、分组、调仓、产品池、Long-Short 组合写出来。FactorTester 从因子族、参数组合、产品路径、分组回测、IC 测试出发，更适合页面化、模板化、批量因子研究。

这使得很多对研究员重要的对象成为一等概念：

- 因子族和因子候选。
- 产品路径候选和产品组模板。
- 分组数、分组序号、派生组、分组 mask。
- 分组策略与 Long-Short 策略的结果、trace、snapshot。
- 每个设置字段的 chip、默认值、fallback、visible/editable 条件。

### 2. 后端注册驱动前端/CLI，降低界面与业务逻辑漂移

Backtrader/Zipline/LEAN 主要是代码 API，UI/CLI 通常不自动知道某个策略有哪些字段。FactorTester 的 `ExecutableModule.fields` 同时承担：

- 后端运行配置定义。
- 前端 tab/chip/content manifest。
- CLI help/参数合法性来源。
- 默认值、可见性、可编辑性、scope 规则。

优点是设置项不容易在前端、CLI、后端三处变成三套语义。缺点是字段注册质量要求很高：一旦 label、default_if、visible_if 写错，会直接影响所有入口。

### 3. Flow/EventQueue 比简单 pipeline 更适合表达“因果回放”

向量化框架的速度很强，但订单延迟、成交时点、强平通知、换月通知、逐日盯市、保证金追缴这类事件不容易自然表达。native 的 Flow/EventQueue 能表达：

- SIGNAL 只产生目标或订单草稿。
- TRADE_INTENT 表达换月、交割强平、风控强平等非信号来源交易意图。
- ORDER 表达真实成交、费用、现金和持仓更新。
- LEDGER 表达逐日盯市、保证金重算、账本生命周期事件。

这比“每根 bar 固定跑一串函数”更接近离散事件仿真，也比纯向量化更容易防止未来函数。

### 4. 分组策略集中放置是合理的

`GroupMembershipModule` 当前承担了较多分组业务语义：分组隶属、分配方式、买入持有、membership_change、派生组 mask、订单执行登记。它看起来大，但并不一定应该拆小。

原因是这些逻辑共享同一个核心不变量：先在完整候选池中计算分组 membership，再按分组/派生规则形成 target，最后调度订单。若强行拆成许多小模块，会让这个不变量分散在多个接口里，反而降低 locality。

更好的边界是：

- 保持“分组策略全家桶”作为深模块。
- 把真正跨策略复用的基础设施抽出去，例如 `TargetStrategyModule`、`StrategyBook`、`MarketDataModule`、`TradingRuleModule`、`CashPoolModule`。
- 不为每一个分组内部步骤都创建独立 public Module。

### 5. 外部框架桥有助于行业对标

ADR-030 的方向是正确的：外部框架不注册 native flow，而是作为独立 worker 按自己的 loop 跑。这样可以避免“把 Backtrader/Zipline/RQAlpha 伪装成 native module”的混乱。

这个设计的优势：

- native 保留自己的解释性与模块化。
- 外部框架保留自己的 broker/order/portfolio 语义。
- 同一份配置可以做 target trace、equity curve、订单语义的一致性测试。
- 框架不支持的字段可以通过 capability 显式拒绝，而不是静默忽略。

### 6. 对中国期货细节的建模潜力强

主流通用框架往往提供通用 broker/commission/slippage，但中国期货的历史交易规则、夜盘归属下一交易日、主力/合约展开、平今平昨、逐日盯市、保证金调整、涨跌停方向约束等，需要大量本地语义。

FactorTester 已经把这些点拆到更接近真实来源的模块：

- `MarketDataModule`：数据源、频率、行情字段、历史交易规则字段。
- `TradingRuleModule`：记账规则、逐日盯市、交易规则历史字段。
- `MarginModule`：保证金、追缴、强平通知。
- `TermStructureExpandModule` / `RolloverModule` / `DeliveryForceCloseModule`：期限结构、换月、交割前处理。
- `CashPoolModule` / `StrategyBookModule`：现金池、ledger 路由、可动用现金限制。

这比把所有逻辑塞在一个 broker 类里更容易持续演进。

## 短板和风险

### 1. 模块很多，接口深度还不均衡

当前模块数量已经较多，且有些模块是深模块，有些仍像“字段容器 + 一两个 flow”。风险是调用者需要知道太多小模块的组合顺序，导致接口变浅。

建议继续坚持两个原则：

- 像分组策略这种业务全家桶，保持集中，不为了形式拆开。
- 像现金池、交易规则、DataIndex、FieldHistory 这种真正跨业务复用的基础设施，放到语义 owner 处。

### 2. native 的真实账户语义仍在建设中

主流事件驱动框架通常已经有较成熟的 broker/account/order 生命周期。FactorTester 正在自建：

- ledger 与 cash pool 的分离。
- strategy 到 ledger 的路由。
- 共享 cash pool 时单策略 equity 曲线是否适用。
- margin requirement / reserved / deficit / liquidation。
- DMTM 是否只重置 lot 成本和保证金，还是同时结算现金。
- 多账本、多 cash pool、多币种、FX 事件。

这些是框架成为“真实交易规则模拟器”的必要路径，但也是当前最大的复杂度来源。短期内比 Backtrader/LEAN 更容易出现会计口径 bug。

### 3. 数据源和历史交易字段决定上限

FactorTester 的优势依赖数据语义。若历史交易规则、合约生命周期、结算价、涨跌停价、交易日映射、夜盘归属、品种/合约映射不完整，native 引擎越真实，越容易暴露缺数据问题。

相比 vectorbt 这类框架“只要 OHLCV 就能跑”，FactorTester 的 exact/auto 模式更像交易仿真，对数据完整性要求高。

### 4. 与外部框架的一致性难度高

Backtrader、Zipline、Qlib、RQAlpha 各自对成交、订单生命周期、现金、费用、撮合时间有内置假设。FactorTester 想做跨框架一致性时，必须区分：

- 本来应该一致的：同一信号、同一目标、同一取价时点、同一手续费/滑点/手数规则。
- 合理不一致的：框架不支持的 partial fill、交易所规则、订单状态模型、日终结算语义。

如果 capability report 不够严格，最危险的不是“跑不通”，而是静默得到看似正常但语义不一致的结果。

### 5. 性能容易被真实语义拖慢

vectorbt 的速度来自矩阵化；Backtrader/Zipline 的事件 loop 通常也较稳定。FactorTester 同时做：

- 因子预计算或增量计算。
- 产品路径展开。
- 期限结构展开。
- 历史交易规则向量化查询。
- 逐事件 flow 回放。
- snapshot/order-flow/trace 记录。

因此性能瓶颈会出现在数据准备、历史字段查询、term structure、event loop、结果整理多个位置。必须继续保持：

- 能预计算的因子尽量预计算。
- 按 factor、产品池、run window、warmup window、数据源、频率分组复用。
- 历史字段查询向量化，不做逐点查询。
- snapshot/trace 懒生成或分层存储，避免一次性重物化全部细节。

## 与各框架的具体优劣对比

### Backtrader

优势对方：

- 成熟 broker/order/commission/slippage 机制。
- 策略写法简单，社区资料多。
- 市价单下一 bar open 的语义清晰。

FactorTester 优势：

- 因子分组、派生组、产品路径、设置注册、结果 trace 是一等业务。
- 更容易统一前端/CLI/后端字段。
- 更适合用同一份 FactorExpr 做 native 与外部框架一致性验证。

FactorTester 劣势：

- broker/account 语义仍在建设，成熟度不如 Backtrader。
- 用户若只想快速写一个 `next()` 策略，Backtrader 更直接。

### Zipline / Zipline Reloaded

优势对方：

- 经典 event-driven 架构，强调避免 look-ahead。
- Pipeline/Asset/TradingCalendar 语义成熟，适合股票日频/分钟研究。

FactorTester 优势：

- 更贴近中国期货和产品路径/分组业务。
- 因子表达式树与页面模板结合更强。
- 可以把 Zipline 作为 worker，而不是把自身改造成 Zipline 风格。

FactorTester 劣势：

- 日历、资产生命周期、corporate action 等通用资产基础设施还不如 Zipline 成熟。

### QuantConnect LEAN

优势对方：

- 多资产、实盘、回测、优化、数据接入、brokerage model 都很完整。
- 账户、证券、现金簿、订单模型更工业化。

FactorTester 优势：

- 在本项目语境下更轻，更可控，更贴合因子页面和本地数据。
- 能把每个业务设置后端注册到前端/CLI，适合交互式研究平台。
- 可以更深入定制中国期货历史规则和本地字段。

FactorTester 劣势：

- 离 LEAN 的 broker/security/cashbook 成熟度还有距离。
- 多币种、外汇、跨市场撮合、实盘对接不是当前强项。

### vn.py / RQAlpha

优势对方：

- 更贴近中国市场交易实践。
- vn.py 实盘生态强，CTA/网关/风控/监控成熟。
- RQAlpha 的 mod 扩展思路适合本土市场回测。

FactorTester 优势：

- 因子表达式、分组测试、IC 测试、模板、产品路径管理是平台核心，不只是策略插件。
- 可以把 RQAlpha/vn.py 语义作为外部 adapter 对照，而不是被其生命周期绑定。

FactorTester 劣势：

- 真实撮合、交易网关、实盘稳定性不如 vn.py。
- RQAlpha adapter 仍需按 capability 显式补齐，不能只声明支持。

### vectorbt / Backtesting.py

优势对方：

- 上手快，参数扫描和向量化速度强。
- 适合研究早期大量策略变体验证。

FactorTester 优势：

- 事件因果、订单、资金、保证金、历史交易规则、trace 更细。
- 适合需要解释“这个时间点为什么买/卖/没交易”的分组回测。

FactorTester 劣势：

- 速度和简洁性不如向量化框架。
- 对数据完整性和配置正确性的要求更高。

### Qlib

优势对方：

- AI/ML 因子研究、数据集、模型训练、回测评估链路成熟。
- 面向实验管理和模型迭代。

FactorTester 优势：

- 本地 FactorExpr + 页面交互 + 分组策略解释链更紧。
- 对单因子/因子族的参数、产品路径、分组组合设置更具体。
- 可以把 Qlib worker 作为外部对照路径。

FactorTester 劣势：

- ML workflow、模型训练、实验管理、数据集生态不如 Qlib。

## 当前设计中值得保留的取舍

### 保留分组策略全家桶

`GroupMembershipModule` 不应该被拆成“rank module / split module / mask module / target module / order scheduling module”这类过细结构。它的核心价值是把分组策略的不变量集中起来：

```text
signal values
  -> full-universe rank
  -> group membership
  -> optional derived mask
  -> target weights
  -> order scheduling
```

这个路径是分组测试业务本身，而不是通用基础设施。拆太细会让每个小模块都变浅，调用者反而必须理解整个组合。

### 保留外部框架桥，而不是把外部框架变成 native module

Backtrader/Qlib/Zipline/RQAlpha 应该是 worker/adapter，不应向 native queue 注册 flow。它们有自己的生命周期和 order/broker 语义。native 的任务是给它们一致的输入、能力检查和结果收集。

### 保持字段注册为前端/CLI 单一来源

字段定义应该继续由后端模块提供，前端/CLI 不应硬编码业务字段。尤其是 `visible_if`、`editable_if`、默认值、displayValue/chip formatter 应继续以注册信息为准。

### 把真实交易规则放到 owner 模块

不要把交易规则散落在订单、费用、保证金、市场数据调用处：

- 时间索引、交易日最后时刻：DataIndex。
- 历史字段查询：FieldHistory。
- 行情和交易字段需求聚合：MarketDataModule。
- 交易规则解释：TradingRuleModule。
- 资金池余额：CashPoolModule。
- 策略到账本路由：StrategyBookModule。
- 分组策略生成 target：GroupMembershipModule。

## 当前最需要补强的方向

1. 明确 cash pool / ledger / strategy / StrategyBook 的最终接口。共享 cash pool 时，单策略 equity curve 应降级为 PnL 或贡献曲线，组合级 equity 才有严格意义。
2. 完成保证金、DMTM、margin call、强平交易意图的闭环。DMTM 不应误用 average cost；应在 lot-based accounting 下按结算价重置 lot 成本，并触发保证金重算。
3. 把 MarketDataModule 的数据源、频率、历史字段需求变成真正的前置订阅/聚合，不要在各模块临时查缺什么。
4. 保持 native 与 worker 的控制变量测试：同一策略配置下，target trace 必须一致；equity curve 只有在 capability 差异被明确声明时才允许不同。
5. 控制模块数量。业务全家桶可以大，但基础设施必须深；避免为了视觉上“分层”制造一堆 pass-through module。
6. 完善 snapshot/order-flow/trace 的延迟生成和查询接口。行业框架通常给日志和交易列表；FactorTester 的机会是给出“每个模块为什么这么做”的可追溯解释。

## 总结

FactorTester 的核心差异不是“又写了一个 backtesting engine”，而是把因子研究平台、分组测试业务、后端注册式设置、因果事件回放、外部框架桥接放在同一个体系里。

这带来三个优势：

1. 对因子研究员更友好：从因子族、参数、产品路径、分组策略开始，而不是从策略代码开始。
2. 对可解释性更友好：目标是能追踪每个时间片、每个模块、每个订单和每个设置默认值。
3. 对本地市场规则更友好：有空间表达中国期货的夜盘、期限结构、平今平昨、逐日盯市、保证金和涨跌停。

也带来三个代价：

1. 实现复杂度高，模块顺序和状态归属必须极其清楚。
2. 性能压力大，必须持续做分组复用、向量化查询和懒生成。
3. 会计和交易规则错误的风险更高，需要用真实模板、控制变量测试和跨框架一致性测试持续锁定。

因此当前最稳的架构策略是：保持分组策略业务集中，保持基础设施深模块化，保持外部框架桥独立，继续把交易规则和账本语义从“能跑”推进到“行业语义明确且可验证”。
