# ADR-050：BAR 的代表时间与可见时间分离

- **日期**：2026-08-10
- **状态**：已采纳（第一阶段）
- **相关**：ADR-018、ADR-044

## 背景

BAR 事件的调度时间是“策略可以看到它的时间”，而 BAR 本身还代表一段
行情的结束时间。两者在以下场景不同：

- bar-end 字段带有可见延迟；
- next-bar OPEN 在上一根 bar 结束后已经可见，但目标 bar 尚未结束；
- 同一回测中存在不同数据源或不同可见策略。

如果把 `EventDraft.timestamp` 同时当作这两个时间，因子历史会被平移，
并且后续代码很容易通过行位置误读尚未可见的数据。

## 决策

每个 BAR 值必须显式携带：

```text
bar_end       = 该值所代表的 bar 时间
available_at  = 该值允许被读取的模拟时间
values        = 该 BAR 的不可变值映射
```

可见性判断只使用 `available_at <= decision_time`。不得用 `bar_end <=
decision_time` 替代它，因为 next-bar OPEN 合法地可能在 bar_end 之前可见。

`EventDraft.timestamp` 继续表示事件调度/可见时间；BAR payload 同时登记
`bar_end` 和 `available_at`。FactorExpr 增量执行器按 `bar_end` 更新序列，
legacy 因子只有在 SIGNAL 阶段才把已可见的 BAR 适配成 DataFrame。策略
hook 保留原来的 payload 兼容层，同时通过 `StrategyContext.data["bar"]`
取得不可变的 `CausalBar` 视图。

## 迁移边界

第一阶段只改变 BAR 元数据和 legacy live-factor 的缓冲表示，不改变旧的
因子数值、信号调度或订单成交语义。后续将把 `BarSnapshot`/`MarketSlice`
作为增量执行器和策略 hook 的正式输入，并把 DataFrame 适配器标记为兼容层。

## 验收

- 延迟可见的 BAR 在 `available_at` 之前不会进入因子历史；
- next-bar OPEN 可以在 `bar_end` 之前可见，但不会被误判为未来数据；
- 同一时间戳的最后一条 BAR 保持旧的 keep-last 语义；
- legacy 与增量因子在无延迟配置下结果一致；
- BAR 热路径不再对完整历史 DataFrame 做逐行拼接。
