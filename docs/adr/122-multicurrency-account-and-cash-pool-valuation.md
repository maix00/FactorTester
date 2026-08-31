# ADR-122：多币种账户与资金池估值

## 状态

已接受。

## 背景

资金池过去只保存一个 `DataMoney`，池内所有账本都读取并替换它，导致账户
币种和资金池 base currency 无法区分，也无法表达混合币种资金池。经纪商模型
通常把币种现金余额和 base-currency 汇总分开；FactorTester 的购买力边界也
必须保留两个事实，并在因果时间点估值。

## 决策

- `LedgerConfig.account_currency` 是单个账户的注册币种；
  `CashPoolConfig.base_currency` 是资金池的共同估值币种；
- `CashPoolStore` 为每个账本拥有独立不可变 `DataMoney` 余额，即使共享资金池也
  不共享余额对象；
- 初始资金只记录一次：存在 base-currency 账户时分配给它，否则保留为资金池
  未分配的 base-currency 储备；
- 资金池现金、权益、保证金和利用率在事件时刻使用 FX 观察统一转换到池的
  base currency；
- FX 按资金池、币种对、时间戳和提供方缓存，同一因果事件的所有消费者使用
  同一汇率；
- 缺失或非正汇率直接报错，不能改成 1 或当前的非因果汇率；
- 被动估值不收假设的换汇费；购买力和执行投影对外币现金按注册换汇费净值，
  实际未来换汇必须作为结算事件记账；
- 成交、结算和审计投影分别保留账户 ID、资金池 ID、账户币种和资金池 base
  currency。

`LedgerState.base_currency` 暂时仍是账户币种槽位的内部名称；新的配置和结果
契约使用 `account_currency`。有明确账户币种时，不能用资金池 base currency
覆盖它。

## 后果

同币种私有资金池保持原有算术；共享资金池不再重复计算初始资金，也不依赖先
访问哪个账户。混合币种运行要求每个观察到的币种对和时间戳都有历史 FX 提供
方；现金约束、保证金预算、净值和保证金风险检查共用同一资金池估值边界。

## 参考

- https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/portfolio-summary
- https://interactivebrokers.github.io/tws-api/account_summary.html
