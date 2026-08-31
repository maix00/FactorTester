# ADR-127：回测管线调度体系——事件驱动 DES 与混合架构

> **编号迁移说明：** 本文原文件名为 `009-backtest-pipeline-hooks.md`。因 ADR-009 已用于页面作用域提交状态，
> 本文迁移为 ADR-127；决策内容不因重编号改变。

- **日期**：2026-06-12
- **状态**：已被 ADR-018 取代
- **决策者**：FactorTester 团队

> ADR-018 保留“向量化预计算 + 有状态执行”的方向，但废止每个时间点
> 预生成全部阶段事件、按固定 EventCategory 推进，以及公开
> `EventDrivenFactor` 作者接口的设计。

---

## 行业调研

在设计本体系前，调研了三大主流回测框架的事件驱动/管线调度模式：

### Zipline (Quantopian, 19.9k⭐) — "日程事件 + Pipeline DAG + 可插拔模型"

| 层级 | 机制 | 示例 |
|------|------|------|
| **日程层** | `schedule_function(func, date_rule, time_rule)` | 每天收盘前计算信号、每月初调仓 |
| **数据流层** | `Pipeline` — 声明式 DAG，按依赖拓扑排序批量执行 | `CustomFactor.compute()` 只写一次即被 Pipeline 调用 |
| **交易层** | `order()` → `Blotter` 聚合 → `SlippageModel.process_order()` → `CommissionModel.calculate()` | 所有订单经台账统一处理滑点+佣金 |

**关键设计事实**：
- `CommissionModel` 和 `SlippageModel` 是**可插拔接口**，通过 `set_commission(model)` / `set_slippage(model)` 注入，而非硬编码
- `Blotter` (订单台账) 是订单→交易→佣金的**中转抽象**，引擎只对 Blotter 说话
- `PipelineEngine.run_pipeline(hooks=...)` 在 DAG 编译→执行之间提供钩子注入点
- 事件分 SIM 引擎事件 (`BAR`, `DAY_START`, `DAY_END`) 和用户自定义日程

### backtrader (21.9k⭐) — "Cerebro 万能组装 + Lines 双阶段算子"

| 组件 | 职责 | 注入方式 |
|------|------|----------|
| **Cerebro** | 总调度引擎，持有所有组件引用 | 唯一入口 |
| **Data Feed** | 数据源，自身也是 Lines 对象 | `cerebro.adddata()` |
| **Strategy** | `__init__()` 声明指标 + `next()` 逐K执行 | `cerebro.addstrategy()` |
| **Indicators** | Lines 对象链，`next()` 自动推进 | Strategy 内声明 |
| **Broker** | 订单执行、现金/持仓管理 | `cerebro.broker` |
| **Slippage** | 滑点模型（点差/百分比/成交量份额） | `broker.set_slippage()` |
| **Commission** | 佣金方案（按比例/固定/阶梯），含 `CreditInterest` 利息返还 | `broker.setcommission()` |
| **Analyzer** | 绩效分析（夏普/回撤/交易统计） | `cerebro.addanalyzer()` |
| **Observer** | 实时统计/可视化 | `cerebro.addobserver()` |
| **Sizer** | 头寸规模管理（固定量/按风险/按百分比） | `strategy.sizer` |
| **Timer** | 定时回调（按日期/按K线/按会话） | `strategy.add_timer()` |
| **Trading Calendar** | 交易日历（指定交易所/国家） | `cerebro.addcalendar()` |

**关键设计事实**：
- **Lines 是核心抽象**：数据、指标、运算结果全是 Lines 对象。`[0]`=当前值，`[-1]`=上期值。在 `__init__` 中声明式构建 Lines DAG，在 `next()` 中自动推进
- **双阶段算子**：`a + b` 在 `__init__` 阶段创建 Lines 对象（声明式），在 `next()` 阶段返回实际值（执行式）。同一条表达式在不同阶段有不同含义
- **Cerebro 强组装、弱耦合**：所有组件通过 `cerebro.add*` 注入，引擎不关心组件内部实现，只负责按生命周期调度
- **生命周期是隐式事件体系**：`__init__` → `start()` → `prenext()` → `next()` → `stop()`，各组件覆写对应方法即注册

### QSTrader (3.4k⭐) — "日程驱动 + 模块化管道"

| 组件 | 职责 |
|------|------|
| **TradingSession** | 按 schedule 触发事件 |
| **Strategy** | 生成信号列表 |
| **Portfolio** | 头寸管理、权重再平衡 |
| **Execution** | 订单拆分与执行 |
| **Broker** | 市场交互、手续费 |

强项在于 schedule-driven 的确定性——每天固定时间触发固定模块，适合日频量化策略。

### 三大框架对比矩阵

| 维度 | Zipline | backtrader | QSTrader | **我们的需求** |
|------|---------|------------|----------|----------------|
| 事件模型 | 显式日程 + Pipeline DAG | 隐式生命周期 | 显式日程 | **显式管线阶段** |
| 模块注入 | `set_commission(model)` | `cerebro.add*()` | 构造时注入 | **tab 注册到 Pipeline** |
| 因子计算 | Pipeline DAG 批量 | Indicators 逐指标 | Strategy 自管 | **已有独立因子引擎，不需改造** |
| 交易链路 | order→Blotter→Slippage→Commission | order→Broker→Slippage→Fill | Strategy→Portfolio→Execution→Broker | **trade_intent→拆分→费用→保证金→流动性** |
| Hook 方式 | `run_pipeline(hooks=...)` | 生命周期方法覆写 | 日程事件 | **按 priority 排序的 hook chain** |
| 核心抽象 | Pipeline Term (Factor/Filter) | **Lines** (一切皆数据线) | Strategy + Portfolio | **Model 协议 + Hook Chain** |

### 行业调研对本设计的启示

1. **事件粒度不宜过细**：三框架均用粗粒度阶段（`__init__`/`next`/`stop`），细粒度逻辑由可插拔组件内部处理，而非由引擎逐一发射事件
2. **可插拔组件 > 原始事件**：费率、保证金、流动性应定义 **Model 协议**（对标 Zipline 的 `CommissionModel`、backtrader 的 `Commission`），引擎只对协议说话
3. **组装与执行分离**：backtrader 的 Cerebro 是最干净的"先在 `__init__` 声明 DAG，再在 `next()` 执行"模式——pre 阶段计算矩阵，step 阶段只读矩阵
4. **pre-compute + 循环只读** 是零开销的唯一保证：Zipline 的 Pipeline DAG 批量计算和 backtrader 的 Lines 双阶段算子都避免在循环内做矩阵运算

---

## 背景

当前 `simulate_group_trading_book()` 将所有交易逻辑硬编码在一个大循环中：
费率表查询、保证金占用计算、流动性约束裁剪、买卖拆解、盈亏核算——全部内联在 300+ 行的循环体内。

每次新增一个维度（min_tick 精度、多时段品种、保证金模式），都需要在循环中嵌入 `if` 分支，
且各维度的参数准备散落在 `_simulate_group_from_preloaded()` 的千行参数中。

前端已有 **fee** / **liquidity** / **product** / **margin** / **rebalance** 等多个 tab，
但它们的配置最终汇聚为 `group_configs` dict 传入后端，tab 之间没有独立的后端注册入口——
每个 tab 的实现散落在不同分支和 if-else 中，无法独立开发、测试和部署。

### 为什么不能纯向量化

无费率、无流动性、无保证金时，分组回测可以纯向量化：

```
P&L = membership @ returns    # 一次矩阵乘法
```

但一旦引入任何摩擦，就必须逐期推进状态：

| 条件 | 能否纯向量化 | 原因 |
|------|------------|------|
| 无费率 + 无流动性 + 固定权重 | ✅ | `membership @ returns`，全量矩阵乘法 |
| 有费率 | ❌ | 费率取决于交易量 = |desired - quantities|，`quantities` 是上期状态 |
| 有流动性 | ❌ | 流动性上限依赖当前净值 `equity` 和前期名义市值 `prev_notional` |
| buy_and_hold / recycle | ❌ | 是否保留持仓取决于上期 `quantities > 0` |
| 保证金 | ❌ | 保证金超标需缩放 `desired_quantities`，依赖当前 `equity` |

**根本原因**：费用/流动性/保证金/持仓模式构成一条马尔可夫链：

```
equity₀ → quantities₀ → desired₁ → buy/sell₁ → fees₁ → equity₁ → quantities₁ → ...
```

只要链中任一环节依赖上期状态，整个系统就必须逐期推进。这就是必须引入事件驱动回测的数学原因。

### 目标

1. 建立**事件驱动 DES（离散事件仿真）引擎**——事件队列按 `(时间戳, 事件类别, 优先级)` 排序，从队列顶部 pop 下一个事件处理；同一时间的不同类别事件有可配置的执行顺序
2. 建立**混合架构**：向量化预计算（因子值/returns/membership） + 事件驱动逐期推进（状态/费率/流动性）
3. 建立**可插拔 Model 协议**（对标 Zipline CommissionModel、backtrader Commission）
4. 分组回测退化为**一种订单执行策略模块**——不再独占整个回测流程
5. 为需要维护跨期状态的**路径依赖因子**提供事件驱动 evaluate 通道（区别于现有声明式 FactorExpr DSL）
6. 新目录 `tools/backtest/`——独立于 `tools/factors/`，专注回测引擎

---

## 决策

### 核心理念：事件驱动 DES + 向量化预计算混合

本方案用真正的**离散事件仿真（DES）**替代简单的钩子链。

**什么是 DES**：程序流程由事件决定，而非由固定时间步循环决定。所有事件登记到一个**未来事件列表（FEL）**中——FEL 是一个按 `(时间戳, 事件类别, 优先级)` 排序的优先队列。引擎主循环不断从 FEL 顶部 pop 下一个事件处理，处理完后可能产生新事件 push 回 FEL。

**为什么混合**：
- **向量化层**负责所有"无状态"计算——因子值、returns、membership。这些只需一次矩阵运算，不需要逐期推进。
- **事件驱动层**负责所有"有状态"计算——持仓、现金、净值、费率、流动性、保证金的逐期推进。这些构成马尔可夫链，必须逐期处理。

**分组回测的地位**：分组回测退化为"一种订单执行策略"——和其他策略（等权分配、风险预算、信号驱动等）地位平等，都是订单事件的消费者。

**路径依赖因子的地位**：现有 FactorExpr DSL 覆盖所有纯声明式因子（40+ 个全部可用）。但一旦因子需要维护跨期状态（如自适应均线 AMA：`ama(t) = ama(t-1) + sc * (price - ama(t-1))`），就需要注册为事件驱动的因子求值事件。

---

### 架构全景

```
tools/backtest/                   ← 新目录，独立于 tools/factors/
│
├── __init__.py
├── engine.py                     ← EventDrivenEngine: 主循环 + FEL
├── events.py                     ← BaseEvent, MarketDataEvent, SignalEvent,
│                                    OrderEvent, FillEvent, FactorComputeEvent, ...
├── event_queue.py                ← EventQueue: heapq 优先队列，按
│                                    (timestamp, category, priority) 排序
├── state.py                      ← WorldState: equity, quantities, cash,
│                                    positions, pnl_history
├── clock.py                      ← SimulationClock: 时间推进
│
├── factors/                      ← 事件驱动因子（跨期状态 evaluate）
│   ├── __init__.py
│   ├── event_driven_factor.py    ← EventDrivenFactor 协议
│   │    on_bar(ctx) 替代 evaluate()
│   └── adaptive_ma.py            ← 示例：AMA 递归因子
│
├── orders/                       ← 订单执行策略模块
│   ├── __init__.py
│   ├── order_strategy.py         ← OrderStrategy 协议
│   ├── group_rebalance.py        ← 分组调仓（现有 simulate_group_trading_book）
│   ├── equal_weight.py           ← 等权分配
│   └── risk_budget.py            ← 风险预算
│
├── models/                       ← 可插拔 Model 协议
│   ├── __init__.py
│   ├── fee_model.py              ← FeeModel 协议 + 实现
│   ├── margin_model.py           ← MarginModel 协议 + 实现
│   ├── liquidity_model.py        ← LiquidityModel 协议 + 实现
│   └── product_model.py          ← ProductModel 协议 + 实现
│
└── context.py                    ← BacktestContext: 上下文传递
```

### 核心组件

| 组件 | 位置 | 职责 |
|------|------|------|
| `EventQueue` | `tools/backtest/event_queue.py` | heapq 优先队列，按 `(timestamp, category, priority)` 排序 |
| `EventDrivenEngine` | `tools/backtest/engine.py` | 主循环：`while queue: event = queue.pop(); dispatch(event)` |
| `BacktestContext` | `tools/backtest/context.py` | 上下文传递（预计算矩阵、全局状态引用、配置） |
| `WorldState` | `tools/backtest/state.py` | 净值/持仓/现金/盈亏历史，事件驱动层唯一可变状态 |
| `SimulationClock` | `tools/backtest/clock.py` | 仿真时间推进，管理交易日历 |

### 事件体系

#### 事件分类（EventCategory）

不同类别事件在同一时间戳下按类别优先级排队，保证执行顺序可控：

```python
class EventCategory(IntEnum):
    """事件类别 — 值越小越先执行"""
    MARKET_DATA   = 10   # 行情数据到达（向量化预计算结果的逐期切片）
    FACTOR        = 20   # 路径依赖因子求值
    SIGNAL        = 30   # 信号生成（membership → 买卖意图）
    ORDER         = 40   # 订单拆解（trade_intent → 手数/方向）
    FEE           = 50   # 费用核算
    MARGIN        = 60   # 保证金占用
    LIQUIDITY     = 70   # 流动性约束
    FILL          = 80   # 成交确认
    PNL           = 90   # 盯市盈亏
    REPORT        = 100  # 报告/日志
```

#### 事件数据结构

```python
@dataclass(order=True)
class BacktestEvent:
    """FEL 中的单个事件。排序键：(timestamp, category, priority, seq)"""
    timestamp: pd.Timestamp
    category: EventCategory
    priority: int = 0
    seq: int = 0                # 全局递增，保证同优先级 FIFO

    # 载荷（不在排序键中）
    event_type: str = ""        # "bar_open", "fee_compute", "pnl_mark" ...
    payload: dict = field(default_factory=dict, compare=False)

class EventQueue:
    """基于 heapq 的未来事件列表（FEL）"""
    def push(self, event: BacktestEvent) -> None: ...
    def pop(self) -> BacktestEvent: ...
    def peek(self) -> BacktestEvent | None: ...
    def __len__(self) -> int: ...
    def __bool__(self) -> bool: ...
```

#### 事件执行流程

```
┌─────────────────────────────────────────────────────────┐
│                EventDrivenEngine.run()                   │
│                                                         │
│  # 1. 向量化预计算（所有无状态因子一次性完成）            │
│  factor_values = evaluate_all_factors(products, timerange)│
│  returns_mat = compute_returns(products, timerange)      │
│  membership_mat = compute_memberships(factor_values)     │
│                                                         │
│  # 2. 初始化事件队列                                     │
│  for t in range(T):                                     │
│      queue.push(MarketDataEvent(t, returns_mat[t], ...)) │
│      queue.push(SignalEvent(t, membership_mat[t]))       │
│      queue.push(OrderEvent(t))                           │
│      queue.push(FeeEvent(t))                             │
│      ...                                                │
│                                                         │
│  # 3. 事件驱动主循环                                     │
│  state = WorldState(initial_capital)                    │
│  while queue:                                           │
│      event = queue.pop()   # 从 FEL 顶部取下一个事件     │
│      dispatch(event, state, ctx)                         │
│      # dispatch 可能 push 新事件回队列                   │
│                                                         │
│  return state.results()                                 │
└─────────────────────────────────────────────────────────┘
```

#### 与行业事件模型的对比

| 维度 | QuantStart | Zipline | **本方案** |
|------|-----------|---------|-----------|
| 队列数据结构 | Python `Queue` (FIFO) | 日程 + Pipeline DAG | **heapq 优先队列** |
| 事件排序 | FIFO（按到达顺序） | 日程（时间规则） | **`(timestamp, category, priority, seq)` 四元组** |
| 同类事件顺序 | 不区分 | 日程固定 | **category 内按 priority，同 priority 按 FIFO** |
| 可配置性 | 无 | schedule_function | **priority 用户可调，category 顺序可重排** |
| 时间推进 | 心跳轮询 | 日程驱动 | **next-event time progression（DES 标准模式）** |

### 混合架构的职责边界

```
┌──────────────────────────────────────────────────────────┐
│              向量化层 (Vectorized — 无状态)                │
│                                                          │
│  FactorExpr.evaluate()                                   │
│  ├── 所有现有 40+ 因子                                   │
│  ├── returns 矩阵 (T × P)                                 │
│  ├── membership 矩阵 (T × M × P)                          │
│  └── 费率/保证金率矩阵 (T × P)  ← 预计算                   │
│                                                          │
│  输出：预计算矩阵 → 注入 BacktestContext                    │
│  时间：一次性完成，事件循环开始前                           │
│  速度：numpy 批量运算，毫秒级                              │
└──────────────────────┬───────────────────────────────────┘
                       │ 预计算矩阵（只读引用）
                       ▼
┌──────────────────────────────────────────────────────────┐
│           事件驱动层 (Event-Driven — 有状态)               │
│                                                          │
│  EventDrivenEngine.run()                                 │
│  ├── MarketDataEvent: 从预计算矩阵读取当期切片              │
│  ├── FactorComputeEvent: 路径依赖因子 on_bar()            │
│  ├── SignalEvent: membership → trade_intent              │
│  ├── OrderEvent: 订单策略生成买卖量                       │
│  ├── FeeEvent: 费率核算（读预计算矩阵 + 当前交易量）       │
│  ├── MarginEvent: 保证金检查/缩放                        │
│  ├── LiquidityEvent: 流动性裁剪                          │
│  ├── FillEvent: 成交 → 更新 quantities                   │
│  ├── PnLEvent: 盯市 → 更新 equity                        │
│  └── ReportEvent: 日志/进度                              │
│                                                          │
│  状态：equity[t], quantities[t], cash[t] 逐期推进         │
│  时间：逐事件处理，等所有该期事件处理完才进入下一期         │
│  速度：每期 ~数百次 Python 调用，可忽略 vs numpy           │
└──────────────────────────────────────────────────────────┘
```

### Model 协议（对标 Zipline 的可插拔组件）

模型协议移至 `tools/backtest/models/`，保持与之前设计兼容但定位更新：

```python
# tools/backtest/models/fee_model.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class FeeModel(Protocol):
    """费率模型 — 对标 Zipline CommissionModel + backtrader Commission"""
    def compute(self, buy_qty: np.ndarray, sell_qty: np.ndarray,
                contract_value: np.ndarray, ctx: BacktestContext) -> np.ndarray:
        """计算费用矩阵 (M × P)。从 ctx 读取预计算的费率矩阵。"""
        ...

# tools/backtest/models/margin_model.py
@runtime_checkable
class MarginModel(Protocol):
    """保证金模型"""
    def occupy(self, position_notional: np.ndarray, ctx: BacktestContext) -> np.ndarray:
        """保证金占用 (M × P → M)"""
        ...

# tools/backtest/models/liquidity_model.py
@runtime_checkable
class LiquidityModel(Protocol):
    """流动性模型"""
    def cap(self, desired_quantities: np.ndarray, quantities: np.ndarray,
            equity: np.ndarray, ctx: BacktestContext) -> np.ndarray:
        """流动性约束裁剪"""
        ...

# tools/backtest/models/product_model.py
@runtime_checkable
class ProductModel(Protocol):
    """品种模型 — 合约乘数、min_tick、lot_size"""
    def price_round(self, prices: np.ndarray, ctx: BacktestContext) -> np.ndarray: ...
    def quantity_round(self, quantities: np.ndarray, ctx: BacktestContext) -> np.ndarray: ...
```

### 上下文模型

```python
# tools/backtest/context.py
@dataclass
class BacktestContext:
    """在事件之间传递的共享上下文。

    分为两部分：
    1. 预计算矩阵（只读）— 向量化层一次性产出
    2. 可变数据槽（读写）— 事件驱动层逐期更新
    """

    # === 向量化预计算（只读） ===
    returns_mat: np.ndarray          # (T, P) 收益率矩阵
    membership_mat: np.ndarray       # (T, M, P) 分组归属矩阵
    factor_values: dict[str, np.ndarray]  # factor_name → (T, P)
    fee_rate_mat: np.ndarray         # (T, P) 预计算费率矩阵
    margin_ratio_mat: np.ndarray     # (T, P) 保证金率矩阵
    price_mat: np.ndarray            # (T, P) 价格矩阵
    tradable_mask_mat: np.ndarray    # (T, P) 可交易掩码

    # === 品种元数据（只读） ===
    point_values: np.ndarray         # (P,)
    min_ticks: np.ndarray            # (P,)
    lot_sizes: np.ndarray            # (P,)

    # === 可变数据槽（事件层读写） ===
    config: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    stop: bool = False
```

### 路径依赖因子：EventDrivenFactor 协议

这是对现有 FactorExpr DSL 的补充（非替代）：

```python
# tools/backtest/factors/event_driven_factor.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class EventDrivenFactor(Protocol):
    """事件驱动因子 — 需要维护跨期状态，不能用 FactorExpr 声明式表达。

    与 FactorExpr 的区别：
    - FactorExpr: 每期结果 = f(当期数据 + 固定窗口历史数据)，无跨期状态
    - EventDrivenFactor: 每期结果 = f(当期数据 + 上一期自身状态)，有路径依赖

    示例：
    - 自适应均线 AMA: ama(t) = ama(t-1) + sc * (price(t) - ama(t-1))
    - 趋势状态机: 切换 trend/range/breakout 状态
    - 组合感知因子: 需要知道当前持仓做加权
    """

    @staticmethod
    def event_category() -> EventCategory:
        """返回 EventCategory.FACTOR"""
        ...

    def on_bar(self, timestamp: pd.Timestamp, prices: np.ndarray,
               ctx: BacktestContext) -> np.ndarray:
        """逐期 evaluate。可以读写 self 内部状态。"""
        ...

    def reset(self) -> None:
        """重置内部状态（跨批次复用前调用）"""
        ...
```

### 执行顺序保障

同一时间戳下的多类事件，按 `EventCategory` 整数值从小到大执行。用户可通过配置覆盖默认顺序：

```python
# 默认类别顺序（不可调）
DEFAULT_CATEGORY_ORDER = (
    EventCategory.MARKET_DATA,   # 10: 数据先到
    EventCategory.FACTOR,        # 20: 路径依赖因子
    EventCategory.SIGNAL,        # 30: 信号
    EventCategory.ORDER,         # 40: 订单
    EventCategory.FEE,           # 50: 费率
    EventCategory.MARGIN,        # 60: 保证金
    EventCategory.LIQUIDITY,     # 70: 流动性
    EventCategory.FILL,          # 80: 成交
    EventCategory.PNL,           # 90: 盈亏
    EventCategory.REPORT,        # 100: 报告
)

# 用户可调：同一个 category 内部多个 handler 的 priority
# priority 越小越先执行，默认 0
queue.push(BacktestEvent(t, EventCategory.FEE, priority=5, ...))
queue.push(BacktestEvent(t, EventCategory.FEE, priority=0, ...))
# → priority=0 先执行
```

### 性能保障

1. **heapq 操作 O(log n)**：n 约等于 T × 每期事件数（~10），对 10000 期约 100K 事件，pop + push 约 2ms
2. **向量化预计算一次完成**：所有因子值/returns/membership 在事件循环开始前批量算完，事件驱动层只切片读取
3. **事件 IDLE 检测**：同一时间戳的所有事件处理完后，没有新事件产生 → 自动跳到下一个时间戳
4. **无注册方时事件不生成**：如果用户选了"无费率"，FeeEvent 不会 push 到队列

---

## 实施路径（4 个 Issue）

### Issue #110-1: 基础设施 — `EventQueue` + `BacktestEvent` + `BacktestContext`

- 创建 `tools/backtest/` 目录结构（`__init__.py` 留空）
- 创建 `tools/backtest/events.py`
  - `EventCategory` IntEnum（MARKET_DATA=10, FACTOR=20, ..., REPORT=100）
  - `BacktestEvent` dataclass（`order=True`，排序键 `(timestamp, category, priority, seq)`）
- 创建 `tools/backtest/event_queue.py`
  - `EventQueue` 类：`push()` / `pop()` / `peek()` / `__len__()`，基于 heapq
- 创建 `tools/backtest/context.py`
  - `BacktestContext` dataclass（预计算矩阵 + 可变数据槽）
- 单元测试

### Issue #110-2: 引擎 + WorldState + 主循环

- 创建 `tools/backtest/state.py`
  - `WorldState` 类：`equity` (M,) / `quantities` (M, P) / `pnl_history` / `turnover_history`
  - `update_quantities()`, `update_equity()`, `snapshot()`
- 创建 `tools/backtest/clock.py`
  - `SimulationClock` 类：时间推进、交易日历
- 创建 `tools/backtest/engine.py`
  - `EventDrivenEngine` 类：
    - `precompute(ctx)`: 向量化预计算（调用现有 FactorExpr.evaluate）
    - `init_events()`: 初始化事件队列（每期 push 10 类事件）
    - `run()`: 主循环 `while queue: dispatch(queue.pop())`
    - `dispatch(event, state, ctx)`: 按 EventCategory 分发
- 单元测试（含 3 期 × 2 品种 × 2 组的 smoke test）

### Issue #110-3: Model 协议 + 订单策略 + 事件驱动因子

- 创建 `tools/backtest/models/` 目录 + 四个 Protocol 定义
  - `fee_model.py`: `FeeModel.compute(buy_qty, sell_qty, contract_value, ctx) → (M, P)`
  - `margin_model.py`: `MarginModel.occupy(position_notional, ctx) → (M,)`
  - `liquidity_model.py`: `LiquidityModel.cap(desired, quantities, equity, ctx) → (M, P)`
  - `product_model.py`: `ProductModel.price_round(prices, ctx)` / `quantity_round(qty, ctx)`
- 创建 `tools/backtest/orders/` 目录
  - `order_strategy.py`: `OrderStrategy` 协议 — `generate_trade_intents(membership, state, ctx)`
  - `group_rebalance.py`: 分组调仓策略（从 `simulate_group_trading_book` 提取核心逻辑）
- 创建 `tools/backtest/factors/` 目录
  - `event_driven_factor.py`: `EventDrivenFactor` 协议 — `on_bar(timestamp, prices, ctx)` + `reset()`
  - `adaptive_ma.py`: 示例实现（AMA 递归因子）
- 单元测试

### Issue #110-4: 对接现有引擎 — 渐进替换 `simulate_group_trading_book`

- 在 `_simulate_group_from_preloaded` 中增加分支：
  - 无费率 + 无流动性 + 无保证金 + each_period → 纯向量化快速路径（保持现有行为）
  - 否则 → 走 `EventDrivenEngine` 路径
- 初期用 `EventDrivenEngine` 复制现有 `simulate_group_trading_book` 的逻辑（保证数值一致）
- 然后逐步将费率/保证金/流动性逻辑拆入 Model 协议
- 回归测试：对比新旧路径的 `net_returns` / `fee_costs` / `total_equity` 输出一致

---

## 替代方案

### 方案 B: Hook Chain（原案 v1）
用 HookChain + HookContext + 三阶段（pre/step/post）emit，无真正的事件队列。
- 优点：简单、迭代快
- 缺点：同一时间步内事件顺序不可控（只能靠 phase 区分）；不支持"处理事件后push新事件"的 DES 模式；无法统一管理路径依赖因子的事件驱动 evaluate
- 退化为本案的无摩擦特例

### 方案 C: 继承体系
每个维度子类化 `Simulator`，通过方法覆写实现定制。
- 缺点：多维度组合爆炸（fee × liquidity × margin = 8 个子类）
- 缺点：新增维度需修改基类

### 方案 D: 事件驱动 DES + 混合架构（本案）
- 优点：真正的事件驱动——事件队列按 `(timestamp, category, priority)` 排序，同级可配置
- 优点：混合架构——向量化预计算处理 90% 因子，事件驱动处理状态推进和路径依赖因子
- 优点：分组回测退化为一种 OrderStrategy，与其他策略平等
- 优点：`EventDrivenFactor` 协议补充现有 FactorExpr DSL，不破坏现有 40+ 因子
- 优点：新 tab 只需实现 Model 协议 + 注册事件类别
- 缺点：复杂度高于 Hook Chain，需要实现 heapq 事件队列和 dispatch 逻辑

---

## 与行业框架的对照总结

| 维度 | Zipline | backtrader | **本方案** |
|------|---------|------------|-----------|
| 调度核心 | `TradingAlgorithm` | `Cerebro` | `EventDrivenEngine` |
| 事件模型 | 日程 + Pipeline DAG | 隐式生命周期 | **heapq 优先队列 (FEL)** |
| 排序规则 | 日程固定 | 生命周期固定 | **`(timestamp, category, priority, seq)` 四元组** |
| 费率 | `CommissionModel` 协议 | `Commission` 类 | `FeeModel` 协议 (`tools/backtest/models/`) |
| 保证金 | Blotter 内 `process_order` | Broker 内 `get_margin()` | `MarginModel` 协议 |
| 滑点/流动性 | `SlippageModel` 协议 | `Slippage` 类 | `LiquidityModel` 协议 |
| 品种 | `Asset` 对象 | Data Feed 元数据 | `ProductModel` 协议 |
| 因子计算 | Pipeline DAG 批量 | Indicators 逐指标 | **向量化预计算 + EventDrivenFactor 补充** |
| 上下文传递 | `context` 可变对象 | `self.datas`, `self.broker` | `BacktestContext` dataclass |
| 时间推进 | 日程驱动 | Lines `next()` | **next-event time progression (DES)** |

---

## 结果

待实施后填写。
