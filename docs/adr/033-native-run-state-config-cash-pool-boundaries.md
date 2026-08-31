# ADR 033：原生运行状态、配置、持仓与资金池边界

## 状态

已接受。

## 背景

原生回测运行时把账本身份、可变账本状态、持仓批次、策略/账本配置和 `BacktestRunState` 逐渐堆进 `engines/native/ledger.py`。这样在引入 StrategyBook、资金池和账本路由后，一个导入路径看起来像是多个语义层的共同所有者，难以继续演进。

初始资金和基础货币属于资金池，而不是账本交易规则。一个账本属于一个资金池，多个账本可以共享资金池；跨币种移动必须作为显式 FX 资金移动建模，不能静默把不同币种加入同一个池。

## 决策

- `engines/native/ledger.py` 只保留 `Ledger`、`LedgerState` 和 `ledger_identity`。
- 未平仓持仓基础类型移动到 `engines/native/position.py`。
- `StrategyConfig`、`LedgerConfig`、`CashPoolConfig` 移动到 `engines/native/config.py`。
- `BacktestRunState` 移动到 `engines/native/state.py`。
- 初始资金、基础货币和 FX 费用属于 `CashPoolConfig`。
- 费用、保证金、会计、结算、可交易性、取整和现金储备策略属于 `LedgerConfig`。
- StrategyBook 描述“策略到账本”和“账本到资金池”的拓扑；CashPoolModule 拥有资金池余额和资金池配置。
- 分组策略业务包保持在一起：分组成员、分组目标生成和多空分组语义是一个业务级包，而不是被拆成许多细小模块。

## 后果

- 运行时导入路径能直接反映状态、配置、持仓和账本身份的所有权。
- 共享资金池会在入金前拒绝冲突的初始资金或基础货币，避免最后写入者覆盖。
- 外部框架翻译从策略/资金池字段读取初始资金，不再从账本交易规则配置读取。
- 将来的 StrategyBook 可以定制账本/资金池拓扑，不必把拓扑塞进 `LedgerConfig`。
