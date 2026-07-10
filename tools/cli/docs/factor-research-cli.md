# FactorTester CLI 接入量化因子研究流程

FactorTester CLI 是远程 HTTP 客户端，不假设用户机器上有服务端源码。量化研究方法本身应使用已有 agent skill，例如 `longbridge-quant` 与 `quantitative-research`；本文件只说明如何把这些研究步骤映射到 FactorTester CLI。

## 推荐研究顺序

1. 定义研究上下文：因子家族、因子参数、产品路径候选、时间范围、模板。
2. 检查因子序列：用 `factor_evaluation run` 查看覆盖、缺失、异常值和数据对齐。
3. 预筛选预测力：用 `ic_test grid` 或 `ic_test config --run` 查看 RankIC、ICIR、滚动 IC、IC 衰减。
4. 做类型诊断：用 `factor_type_analysis grid/run` 判断趋势、波动率等类型相关性和产品组内相关性来源。
5. 只对通过诊断的候选做回测：用 `backtest compare factor-grid` 与 `backtest --run`，显式纳入费率、成交量容量、保证金和换手。
6. 审计结果：用 `backtest results summary/equity/order-flow/snapshot/attribution` 导出统计、净值、订单流和快照。

## 常用命令

```bash
factortester doctor
factortester factor-plan --factor-family SgCCS --template '2026-06-02 07:20:47' --product-group 中国期货日盘 --n 2m --f 1m
factortester factor_evaluation run --factor-family SgCCS --product-group 中国期货日盘 --factor --alias 'SgCCS|N:2m'
factortester ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m
factortester factor_type_analysis grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m
factortester backtest compare factor-grid --factor-family SgCCS --product-group 中国期货日盘 --n 2m --f 1m --volume-capacity-mode infinite
factortester backtest --run --verbose
factortester backtest results summary
factortester backtest results order-flow --group-name A1 --output orders.csv
```

## 验证清单

- 因子定义：写清因子家族、参数、方向、产品域和时间范围。
- 样本域：产品路径候选必须点时一致；grid 可以同时扫参数和产品组。
- 无未来函数：信号使用可见数据；默认下一 bar open 成交；close 信号不得同 bar 成交。
- IC/IR：至少检查 RankIC、ICIR、样本数、滚动稳定性和 IC 衰减。
- 类型分析：检查趋势/波动率等参照类型相关性，以及产品组内相关性来源。
- 多重检验：参数/产品组网格越大，越要报告候选数量和样本外验证。
- 交易成本：费率、滑点、成交量容量和换手率必须进入回测解释。
- 容量：成交量容量限制与不限制至少做一次对照。
- 结果核查：保存统计、净值、订单流、snapshot；异常跳变要定位到 flow 或数据。

