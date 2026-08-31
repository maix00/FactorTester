# ADR-121：回测结果表面与懒加载分析

## 状态

已接受。

## 背景

回测输出过去把一个生成物映射到一个顶层 tab，造成 tab 行不稳定、策略收益
视图重复，并使浏览器提前下载与当前问题无关的数据。QuantConnect、Pyfolio、
FIX ExecutionReport 和 GIPS 的共同要求是：统计、时序、成交、费用、风险和
假设应分层展示，并且费用基础、风险定义和模拟状态不能从图表中猜测。

## 决策

回测 Job 暴露五个稳定表面：

1. **概览**：运行警告、来源和有界摘要；
2. **策略统计**：可比较的策略指标，点击策略标题进入策略局部分析；
3. **时变指标**：净值/当前回撤、收益、滚动风险、现金、保证金利用率、敞口
   和基于成交的换手率，策略和曲线筛选都在本表面内部；
4. **执行与账户**：事件流、订单、成交/结算、持仓、现金、保证金和费用的
   内嵌导航；
5. **收益与风险**：成本比率、回撤区间和期间收益。

每个顶层表面自己保存策略多选状态。执行/账户表面在权威生成物存在时还
提供账户、资金池和币种筛选，并从策略、账户、资金池三个角度展示观察到的
关系。账户余额有自己的币种，资金池以 base currency 作为共同估值单位，
二者不能互相推断。

生成物注册表声明 `result_surface`、`result_view`、`supplemental_bundle` 和
语义 `result_order`；UI 消费这些声明，旧 Job 元数据只使用有界回退投影。
生成物名称是存储身份，不是导航标签。

策略 overlay 只保留需要单个策略身份或其分组成员的分析：分布、稳定性、
容量、可交易性、日历、持有期、贡献、稳健性和排序。重复的策略收益 tab 删除，
因为外部时变表面已经支持策略筛选。

概览和策略统计至少提供总收益/年化收益、波动率、Sharpe、Calmar、当前与
历史最大回撤、胜率、换手率和重要运行警告。图表和表格保留策略身份、时间戳
及其时区、币种、费用基础、数据源和回退警告；缺失值保留为空，不改成零。

## 懒加载与懒计算

- 立即渲染结果壳、tab 和控制项，只请求当前内嵌页面或选中的曲线；
- 新选曲线可以并发加载，并在当前 Job tab 生命周期内缓存不可变规范载荷；
- 表格只创建可见页的 DOM；事件流只加载订单/成交，账户投影在对应页面或图表
  被选中时加载；
- 维度选项从已加载的活动生成物派生，不为填充筛选器发起跨服务器全目录扫描；
- 过期请求可以填充不可变缓存，但不能切换 tab 或重新打开已关闭的控件。

若规范 JSON 超出有界大小，下一版生成物必须提供不可变的时间/行分区和带
`start/end/count` 的能力授权读取；客户端不能通过轮询业务端口模拟范围查询。

主运行在 `post_replay` 通过一个 `ReportDataset` 共同计算选定输出，缓存投影
避免重复扫描。可选输出由一个补充 Job 请求批量生成，注册 bundle 共享
`time_series`、`execution_account` 和 `return_risk` 的重复工作。补充身份由
父 Job、来源哈希、规范请求和当前输出状态决定；相同并发请求复用同一个子任务。

策略分析 tab 共享一个 strategy-analysis bundle，排序仍是独立的配置/产品范围
计算。打开结果不应静默重算；生成物删除后的重建必须是显式补充操作。

## 后果

导航规模稳定，跨服务器只读取当前可见数据，补充计算可审计且去重。不可变
JSON 仍有整文件传输成本；大结果必须升级为带索引的生成物格式，而不是继续
增加客户端分页或全量下载。

## 参考

- https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results
- https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/charts
- https://quantopian.github.io/pyfolio/notebooks/round_trip_tear_sheet_example/
- https://www.fixtrading.org/online-specification/order-state-changes/
- https://www.fixtrading.org/online-specification/trade-appendix/
- https://interactivebrokers.github.io/tws-api/account_summary.html
- https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/
