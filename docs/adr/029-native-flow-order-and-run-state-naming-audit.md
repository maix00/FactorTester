# ADR-029：Native Flow 顺序审计与 RunState 命名迁移

- **日期**：2026-07-02
- **状态**：已接受
- **决策者**：FactorTester 团队

---

## 背景

Native backtest 已经按 `PRE_REPLAY`、`PER_EVENT`、`POST_REPLAY` 拆分为多个
Flow。近期又引入了产品路径、行情频率/数据源、期限结构、换月、交割强平、
预计算信号、Long-Short、手续费、保证金和现金约束等模块。模块增多后，两个问题
变得明显：

1. 需要按真实 flow order 审计每个模块的位置是否符合回测行业语义。
2. 很多 flow callable 仍把整个 `BacktestRunState` 形参命名为 `account`，
   容易把“运行态容器”和“单策略账本/账户权益”混淆。

## 决策

### RunState 命名

Flow callable 和模块 helper 中，表示整个 native run 容器的形参使用 `state`。
`account` 只保留给真实账户/账本语义或历史外部兼容字段，不再作为新 flow
内部的运行态容器名称。

已迁移的 flow 区域：

- 运行窗口、产品选择、行情、期限结构、账本初始化。
- BAR/SIGNAL 的因子信号注册和读取。
- 分组 membership、Long-Short target、订单 sizing/construct、现金约束。
- ORDER 的成交价、手续费、滑点、账本更新、订单终态。
- 净值记录与 POST_REPLAY 风险指标。

### 当前接受的 flow order

`PRE_REPLAY`：

1. 解析运行时间窗口。
2. 解析产品路径。
3. 解析行情数据源与频率。
4. 检查产品覆盖期。
5. 展开期限结构。
6. 装载行情数据。
7. 初始化交易账本。
8. 建立交易日映射。
9. 加载历史交易规则字段。
10. 生成因果估值序列。
11. 登记交割强平通知与换月通知。
12. 登记 BAR 事件、实时因子信号或预计算信号。

这个顺序的行业语义是：先确定 run window 和产品集合，再确定所需行情与覆盖期，
随后展开可交易期限结构并加载数据。账本初始化只创建初始现金/空持仓，因此可以在
历史交易规则字段加载前完成；真正依赖交易规则的 sizing、fee、margin 在事件阶段读取
`MarketDataModule.current_historical_fields`。

`PER_EVENT/SIGNAL`：

1. 读取信号时点价格、成交量和交易规则字段。
2. 读取实时或预计算因子信号。
3. 计算信号时点权益。
4. 计算分组 membership target。
5. 合成 Long-Short target。
6. 将目标解析到可交易合约。
7. 记录信号时点净值。
8. 计算目标下单量，应用流动性/手数取整等 sizing override。
9. 构造订单。
10. 用同批卖出资金进行现金约束调整。
11. 登记下一 bar 开盘执行的 ORDER 事件。

这个顺序保持了“target 先于 order、ORDER 最后执行”的事件语义。Long-Short 是平行
策略 lane，消费来源策略 target 并生成自己的 target；它不应依赖分组测试特有的
`groupIndex`，只依赖来源策略 id/alias。

`PER_EVENT/ORDER_NOTICE`：

1. 处理换月通知。
2. 处理交割强平通知。

`ORDER_NOTICE` 语义上是订单意图通知，与 SIGNAL 平行汇入后续 ORDER 处理链。
换月通知在旧合约存在持仓时生成“平旧合约、开下一合约”的 ORDER；交割强平通知在
合约存在持仓时生成反向平仓 ORDER。两者都不直接改账本，后续成交价、手续费、滑点、
账本更新和订单终态仍统一由 ORDER flow 处理。

`PER_EVENT/ORDER`：

1. 读取订单时点价格与交易规则字段。
2. 解析成交价。
3. 执行手续费/滑点等 `cash_update` override。
4. 更新现金与持仓。
5. 计算订单后权益。
6. 记录订单后净值。
7. 确认订单终态。

ORDER 阶段保持最后执行。默认订单执行语义固定为下一 bar 开盘价；其他价格列或撮合
细节应由后续滑点/撮合模块在明确接口下扩展，不能让公共 order timing 重新变成模糊参数。

`POST_REPLAY`：

1. 根据 per-event buffer 整理最终净值曲线。
2. 基于完整净值/收益序列计算风险指标。

风险指标是全序列统计，不在 per-event 中增量更新。

## 审计结论

### 已确认正确的语义

- 预计算因子策略不会额外注册实时 BAR signal flow；实时因子策略才注册 BAR。
- 无 Long-Short 策略时，Long-Short flow 不应出现在前端 activity manifest。
- 分组派生组的 `product_mask_names` 在 membership 完成后再筛选，而不是先缩小产品池再重排。
- margin 模式下权益为 `cash + occupied margin + floating PnL`，不是简单
  `cash + notional`。
- 流动性与最小手数属于 sizing override，手续费与滑点属于 ledger update override。
  这些模块的位置符合“模块自己注册介入点”的方向。

### 仍需继续拆解的语义缺口

- `FactorTesterState.account` 仍是结果详情链路的历史字段名。它不是 native flow
  内部命名，但后续若重构 snapshot/detail store，需要一起迁移为明确的 run-state
  挂载字段。
- `Flow.inputs` / `Flow.outputs` 已能做审计 warning，但生产路径仍未强制执行。后续
  需要逐步打开 exact/debug 模式下的 strict contract。

## 后果

- 后续读 flow 时，`state` 一律表示整个 native run 的长期状态容器，`Ledger` 才是
  单策略账户/账本。
- 按 flow order 审计时，优先检查模块是否在正确 phase/order 中注册，而不是只看
  文件名或类名。
- 新增模块必须明确声明自己在哪个 flow 介入：PRE_REPLAY 准备、SIGNAL target/order
  意图、ORDER_NOTICE 通知、ORDER 成交账本，或 POST_REPLAY 结果整理。

## 参考

- `tools/testers/backtest/engines/native/scheduler.py`
- `tools/testers/backtest/modules/group_membership.py`
- `tools/testers/backtest/modules/long_short.py`
- `tools/testers/backtest/modules/order_book.py`
- `tools/testers/backtest/modules/ledger_module.py`
- `tools/testers/backtest/modules/term_structure.py`
- `docs/adr/026-native-run-state-and-flow-context-boundaries.md`
