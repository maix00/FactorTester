# ADR-041：策略意图策略与可复用选择工具

- **日期**：2026-07-23
- **状态**：已接受；运行时边界与公开入口分别由 ADR-018、ADR-032、ADR-141
  约束
- **相关**：ADR-023、ADR-024、ADR-029、ADR-032、ADR-035、ADR-141

## 背景

`StrategyIntentPolicy` 曾分散在全局 `strategy_kind -> policy` 注册表、执行期
的分组/阈值/多空流程，以及只能替换批量路径的
`strategy_intent_precompute` 回调中。这会让实时和预计算实现漂移，也会把
分组测试误认为回测引擎的前置条件。

Backtrader、Qlib、LEAN 和 Zipline 都把选择、目标配置、再平衡和订单执行
分开：策略产生目标，订单层根据当前持仓交易差额。FactorTester 采用同一
语义。

## 决策

### StrategyBook 拥有策略解析

`StrategyBookPolicies` 是唯一的策略容器，分别保存每个策略的意图策略、
组合级协调策略，以及路由、现金可用性和数量计算等运行时覆盖。只有具有
稳定决策契约和组合语义的插槽才成为可复用工具；需要读取可变账本或订单
状态的能力仍由运行时边界负责。

`StrategyIntentPolicy` 是由 StrategyBook 解析的每策略策略。全局策略类型
注册表在迁移期只保存内置默认值，预计算专用覆盖不拥有策略语义。

### 一个意图接口、两个执行适配器

策略意图从上下文产生 `TradeIntent`，相同语义同时供：

- 回放/逐步检查的事件适配器；
- 只对声明可编译策略开放的向量化适配器。

不支持的自定义 Python 逻辑回退到事件适配器，不能静默换成另一套算法。

### 可复用策略工具

工具分为三类：

- 横截面选择：`screen`、`rank`、`split`、`top`、`bottom`；
- 再平衡：全目标、买入并持有、成员变化、有界替换，以及未来的换手预算；
- 配置：等名义、逆波动、等保证金和登记的未来配置器。

内置分组策略的标准计划是筛选、排序、分组、选择、再平衡和配置；向量化
实现只是同一计划的优化。

### 因子角色属于策略

策略可以绑定 `ranking`、`screen`、`entry`、`exit` 和 `sizing` 角色。分组
策略至少需要 `ranking`；阈值状态策略使用 `entry`/`exit`，二者可以在未
显式绑定时有意绑定主因子。

角色因子由 `FactorSignalModule` 计算，意图策略只消费按时间排列的值。
缺少 entry 值不能开仓，缺少 exit 值不能静默改用排序因子。预计算只能编译
同一因果转换，不能替换有状态的进入/退出转换。

### 分组成员与数量

进入选中桶产生非零目标，离开产生零目标，仍在桶内也可能改变目标权重。
产品掩码是分桶后的交集，不得被重新解释为动态排序全集。订单构造仍是
目标数量减当前数量。

### 用户界面与 CLI

选定策略拥有自己的配置界面；Web 和 CLI 从后端 manifest 获取策略目录、
因子角色和策略字段，不同时暴露全部字段。CLI-Anything 只包装真实
`factortester` HTTP CLI，不能在本地重写策略解析。

### 边界策略的统一决策包络

路由、购买力和待处理订单分别使用 `RouteDecision`、`BuyingPowerDecision`
和 `PendingOrderDecision`，但都遵守同一行为：策略只返回值，不直接修改
账本、订单队列、待处理索引或资金池；拥有者模块负责校验并原子应用。

序列化决策至少包括 `policy_id`、版本、动作、稳定原因码、有效时间、输入
摘要、领域载荷、诊断和实现来源。默认策略和自定义策略走相同校验路径；
逐步输出摘要，显式 CLI 详情命令才输出完整请求、决策与来源。

账本归属必须在目标转换前解析并冻结，目标、现金、费用、成交、结算和持仓
都消费同一账本身份。执行场所路由不能反过来改变会计归属。现金储备、购买力
和保证金资金分别建模；跨账本共享资金池时按资金池而非账本对象聚合。

待处理订单解析迁移到通用 Order Scheduling 模块，先构造不可变订单草稿和
计划时间，再调用策略并原子更新状态、索引、队列和审计。首批动作是
`replace`、`cancel_new`、`merge`、`coexist` 和 `defer`。

## 迁移顺序

1. 先加入决策包络和领域类型，不改变默认行为；
2. 增加紧凑逐步序列化和稳定 JSON；
3. 在目标转换前冻结会计账本，并让旧路由回调最多调用一次；
4. 将通用调度从成员模块移出，无法安全表示副作用的旧 hook 拒绝而不是猜测；
5. 按资金池拆分现金储备、购买力和保证金资金；
6. 只有持久化 RunSpec 带有新策略契约版本后才删除适配器。

迁移不得改变费用、保证金、流动性、DMTM、产品掩码或目标轨迹。

## 后果与验收

分组、阈值和多空是并列的内置意图策略；实时和预计算的目标轨迹以及原因
码必须一致。相同冻结请求和策略版本必须得到相同序列化决策，不受策略迭代
顺序或字典插入顺序影响。

验收还必须覆盖：缺失 entry/exit 值、动态 screen、sizing、单账本与共享资金池、
费用/滑点/流动性/保证金、待处理订单五类动作，以及默认/自定义策略相同的
校验和应用路径。逐步输出每个实质决策一行；完整细节通过显式 CLI JSON 查看。

## 参考

- https://pmorissette.github.io/bt/index.html
- https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst
- https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/portfolio-construction/key-concepts
- https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/buying-power
- https://www.quantconnect.com/docs/v1/algorithm-framework/execution
- https://zipline.ml4trading.io/api-reference.html
