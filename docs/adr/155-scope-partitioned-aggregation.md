# ADR-155：作用域分区聚合（groupby_scope）

- **日期**：2026-09-17
- **状态**：实施中（Issue #397）
- **关联**：ADR-007、ADR-022、ADR-004

## 行业依据

「先按组分区、再在组内累计」是成熟时序/因子框架的既有语义，与「固定长度滑动窗口」
是两件事：

- DolphinDB 的 `context by` 明确区分两者：`group by` 每组返回一个标量，`context by`
  每组返回与组等长的向量，可与**累计函数**（cumulative functions）配合；其窗口类型里
  另有 session window：
  https://docs.dolphindb.com/en/Database/DatabaseOperations/Queries.html
  https://docs.dolphindb.com/en/Tutorials/Window_Calculations_in_DolphinDB.html
- pandas `DataFrameGroupBy.expanding`／`cumsum`／`cummax`／`cummin` 提供「分组内扩展」
  语义，与 `rolling` 的定长滑动窗口并列：
  https://pandas.pydata.org/docs/reference/groupby.html

本平台现状：`rolling` 已实现按固定根数的滑动窗口（ADR-022 的双后端契约）；
`scope_*` 只服务检索（`scope_bars`/`scope_session`/`scope_trading_day` 用于匹配定位），
**不做聚合**。因此「按当日/会话分区再聚合」在算子层面无法表达。

## 已确认的问题

研报口径的「当日」聚合（当日午前均值、当日 argmax 等）不能用 `rolling('1d')` 表达。
`rolling.py::_resolve_windows` 把 `'1d'` 折算为**固定根数**（天数 × 该频率每日根数）；
1 分钟 255 根/日下，`rolling('1d')` 即「最近 255 根」。实测 `2025-02-20 14:21`
观察点上，其 `truncate(0, 119)` 的 120 根里有 **54 根属于前一交易日**——这不是当日集合。

## 决策

1. 新增算子 `groupby_scope(scope)`。**不沿用 rolling 之名**：它不滑动、不跨组，
   语义是「按作用域分区、组内累计」。
2. 符号：LaTeX 共用 `\mathrm{R}`；rolling 承载**窗口**用**下标**（既有写法不动），
   `groupby_scope` 承载**作用域**用**上标**；截断写进上标：
   `\mathrm{R}^{\text{trading\_day}}`、`\mathrm{R}^{\text{trading\_day},\mathrm{trunc}(a,b)}`。
3. 分区来源：`scope_trading_day()`（交易日）、`scope_session(gap=…)`（会话）、
   `scope_bars(K)`（每 K 根，非重叠）。
4. 语义（**以批量内核为唯一准绳**）：
   - 取值只用「本分区内、截至并含当前根」的观测，禁止使用当前根之后的观测；
   - `truncate(a, b)`：从分区内第 a 个观测起算，到第 b 个观测**含端点**为止；
     `b >= 分区长度` 视为不截断；完整窗口填满后**冻结**为该值；
   - NaN 视为**未观测**：不参与累计，该根输出 NaN（与 ADR-007 的异步面板口径一致）；
   - `argmax`/`argmin` 归一化为 0=最新、1=最早，与 `_rolling_argmaxmin` 同约定；
   - `min_periods` 复用批量内核的同一常量表，不另立一套。
5. 双后端（ADR-022）：作者只写批量语义，编译器编译成有状态 kernel。
   - 批量：分区序号 → 组内扩展聚合；
   - 增量：**每 bar O(1) 状态／每产品**（计数 + 运行和 + Welford 均值与二阶矩 +
     运行极值 + 极值位置 + 分区标记），**不保留 O(K) 窗口缓冲**——内存与分区长度无关；
     250 日这类长窗口不会带来 6.4 万根的缓冲，这是相对 `rolling` 的决定性优势；
   - 宽面板时分派到向量化路径（实测约 8 个产品为切换点）；
   - 不支持的组合（切片无时间戳、`scope_bars` 无法折算为固定根数、非常量 q/截断）
     必须抛 `UnsupportedStreamingFactor`，**禁止静默降级**；
   - median/quantile 需要分区级顺序统计表（O(L) 内存），属顺序统计的固有代价，明示不隐藏；
     其余算子保持 O(1) 状态。
6. 时间来源**不新增协议 seam**：运行时执行器的切片本身已带 `timestamp`/`trading_day`；
   仅为构造裸切片的适配器路径在 `MarketSlice` 上补两个**可选**字段，由
   `StreamingFactorPlan.update` 填充。节点协议与既有节点一行未改。
7. 两后端以**逐点一致断言**绑定（含跨日边界、NaN 缺口、异步面板、截断窗口），
   任何一侧改动都必须重跑该断言。

## 与 rolling 的区别（必须澄清，防误用）

同一分组内，`rolling(K)` 与 `groupby_scope(scope_bars(K))` 取值相同；但 rolling 跨组滑动，
groupby_scope **不跨组**：第 7 根处 `rolling(5)` 覆盖 3–7 根，而
`groupby_scope(scope_bars(5))` 只覆盖 5–7 根。凡「当日/会话」口径必须用后者。

## 取舍与未采纳方案

- **不**把 `rolling` 的窗口改成按交易日对齐：那会改变既有语义与全部历史研究口径；
  新算子与旧算子并存，旧 RunSpec 不受影响。
- **不**为节省内存而把 median/quantile 改成近似或降级；要么给准确值，要么显式拒绝。
- **不**在 batch 与 incremental 之间留两套口径（归一化、截断、min_periods 必须同一套）。

## 迁移与回退

- 新算子无数据迁移；历史 job 与既有 factor 表达式的产出不受影响。
- 回退方式：移除 `groupby_scope` 的注册与编译分派即可；因其未出现在旧 RunSpec 中，
  历史结果仍可读。
