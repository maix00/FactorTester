# groupby_scope 实现交接（Issue #397）

## 环境
- worktree: `/Users/maxdeux/Documents/GTHT/Codes/.workspace/codex/groupby-scope`（分支 `codex/groupby-scope`，基于 origin/feat）
- Python: `/opt/homebrew/Caskroom/miniconda/base/envs/GTHT/bin/python`
- 测试: `python -m pytest tests/factors -q`
- Issue: https://github.com/maix00/FactorTester/issues/397（Write scope + 实现地图在评论里）

## 待写文件
1. `tools/factors/expr/groupby_scope.py`（新增）
2. `tools/factors/expr/groupby_scope_eval.py`（新增）
3. `tools/factors/expr/__init__.py`（仅导出）
4. `tools/factors/expr/visual_groups.py`（注册 groupby_scope + 可读语义）
5. `tests/factors/test_groupby_scope.py`（新增）
6. `tests/factors/test_latex_operator_semantics.py`（扩展：R 上标）
7. `docs/adr/<编号>-scope-partitioned-aggregation.md`（新增）

## 已核实的集成点
- `rolling.py:41` `RollingExpr._AGG_OPS` = {mean,std,var,min,max,sum,ema,skew,median,quantile,argmax,argmin}
- `rolling.py:286` `RollingOp(op, window, *data_and_trunc)` —— op 为字符串名；truncate 为末两个 operands
- `rolling.py:207` `RollingExpr._to_latex` → `\mathrm{R}_{window}` / `\mathrm{R}_{window,\mathrm{trunc}(a,b)}`
- `bar_search_eval.py`：`_observed_mask(frame, ctx)`、`_segment_keys(index, observed_rows, scope, ctx)`（TradingDayScope → `panel_timeline.trading_days` 的 factorize；SessionScope → 按 gap 切；BarCountScope → 单段）
- `lookback_scope.py`：`scope_bars(K)` / `scope_session(gap)` / `scope_trading_day()`
- 注册表：`visual_groups.py:36` `VISUAL_OPERATOR_GROUPS`（+ `get_visual_operator_groups()`），服务端经 `server/modules/custom_factors/editor_routes.py`，CLI 命令 `factortester factor-library operators`

## 语义定稿
- 按作用域分区；聚合窗口 = [分区首根, 当前根]；truncate(a,b) 用**组内序号**
- 因果性：只读 ≤ 当前根；不跨分区回溯
- 组内不足：默认按已有观测计算（开关可切缺失）
- LaTeX：`\mathrm{R}^{\text{trading\_day}}`（上标），带截断 `\mathrm{R}^{\text{trading\_day},\mathrm{trunc}(a,b)}`
- 与 rolling 的区别：rolling=重叠滑动；groupby_scope=不重叠分区（第 7 根、K=5 时取值不同）

## 上次已验证的事故（写进 ADR 与注册表说明）
1 分钟、每日 255 根下，`rolling('1d')` 在 2025-02-20 14:21 覆盖 02-19 14:22→02-20 14:21；其 `truncate(0,119)` 的 120 根里有 54 根属于前一交易日。

## 尚未核实（动手前必读）
`core.py` 中 `RollingOp` 的求值分发路径（op 名 → 求值器），确认新算子如何挂进同一分发。

## 完成后的收尾（需用户明确授权）
聚焦测试 → 提交任务分支 → （授权后）推分支/合 feat → 用新算子重建 VR/VMT/DFP 实例 → 公网 1× 各跑一次 → 报告 4.6 定稿。

## 增量后端（未完成，按此契约机械实现）

ADR-022：作者不写第二个 evaluate_event；compiler 把同一表达式图编译成**有状态 kernel**；不支持必须抛 UnsupportedStreamingFactor，禁止静默预计算或降级。

- 编译器：`tools/testers/backtest/engines/factors/incremental.py`
  - 节点协议：`StreamingNode.update(self, market: MarketSlice, cache: dict[int, np.ndarray]) -> np.ndarray`（全文件 931 行，节点类集中在 65–470 行）
  - 构造点：**第 713 行附近**在把表达式图转节点时构造 `RollingWindowNode(...)`；新节点应在同一分派处按 `GroupByScopeOp` 构造
  - 既有范式：`RollingWindowNode`（167 行起，带 `_update_fast` / `_aggregate`）与 `ExpandingEwmNode`（347 行起）——`groupby_scope` 更接近后者（累计型）
- 要新增：`GroupScopeNode`
  - 状态：每产品一份「当前分区已见观测」的累加结构（均值/求和用 count+sum；min/max 用当前极值；argmax/argmin 记录极值位置与分区起点；median/quantile 保留分区内数组）
  - 边界检测：按 scope 判定——交易日/会话取 market slice 的交易日或时间戳（gap 判定与 `bar_search_eval._segment_keys` 一致）；`scope_bars(K)` 用分区内已见计数 == K 时切分
  - 边界处：先把上一分区的最终值产出（对 truncate 情形即固定子区间值），再重置累加器
  - 归一化：argmax/argmin 必须与 `rolling.py::_rolling_argmaxmin` 相同（0=最新、1=最早）
- 一致性验收（Issue #397 第 9–11 条）：同一表达式在 batch 与 incremental 上**逐点一致**，覆盖跨交易日边界、日初不足、NaN 位置三类；暂不支持的作用域抛 `UnsupportedStreamingFactor` 而不是降级
- 回归入口：`tests/factors/` 与既有 backtest engine 测试目录；先跑 `python -m pytest tests/factors -q`
