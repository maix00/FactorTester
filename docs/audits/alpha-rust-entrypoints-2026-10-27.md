# 因子 Rust 入口与性能剩余缺口

审计固定点：2026-10-27（Asia/Taipei），TradeResearch `9379de952`，alpha
`7e99875`，Nautilus `1c4c1b83c0`。共享工作区另有 #444 前端修改；本次未修改。
本节为静态检查加两项极小编译探针，不是公网根因或新性能验收。

## 已完成与仍缺的边界

Rust 的 PanelPlan/FactorPlanKernel 及 Nautilus Actor 已有多数所需节点，
TradeResearch 的已验收家族路径确实可零 Python factor-Bar 回调。但以下
边界仍不能宣称全部迁移或性能最优。

| 优先级 | 可核对缺口 | 影响与下一验收 |
| --- | --- | --- |
| P1 | alpha `factor/signal.py::SignalAlign.evaluate` 直接覆盖 evaluate，使用 Python 日历分组、目标网格、NumPy搜索/索引；部分 asof 索引调用 Rust。`factor/plan.py::_Builder.build` 没有 SignalAlign 分支。 | 独立批量入口没有统一到 Rust signal kernel；必须统一内外频率、include_current、basepoint、scope_anchor、partial、缺失观测和 prefix 无未来语义后删重复路径。不能说数学全在 Python，也不能因为 spec 中有 signal 就说此入口已接通。 |
| P1 | `factor/term.py::_metric/evaluate_term_metric/TermStructureExpr.evaluate` 仍有 Python/NumPy 数学（含 polyfit）、逐时刻挑选期限曲线；`plan.py` 没有 TermStructure 分支，而 `spec.py` 已有 term。 | 仍有与 Rust term kernel 平行的数学实现。把批量/桥接统一到同一核心，冻结期限排名、剩余期限、曲线可用时刻与 NaN 规则，测试静态/变化曲线及任意前缀。 |
| P1 | `factor/spec.py::plan_blockers` 仍固定把 SignalAlign、TermStructureExpr、CategoryBoolRef 记为 blocker；同时 `to_plan_spec` 已能生成部分对应节点。 | “是否有节点”“当前参数/输入可否执行”“批量入口能否编译”混成一个旧清单。应按具体执行入口与配置给出能力报告，禁止靠硬编码清单判断已迁移。 |
| P1 | `strategy_backtest.py::_frozen_shared_plan` 只合并单个 bindings 集合内的 roles；`_build_strategy_family_engine` 明确要求唯一覆盖所有 Venue 的策略路由，`run_strategy_family_run_spec` 读取单个 plan.strategy。 | 多策略构造器的整次运行共享仍有接通缺口，不只是少一个基准。需要一次冻结所有兼容输入/时钟的 factor roots，生成一个共享 Actor/Plan，再挂多个消费者；不同账户/订单状态仍隔离。 |
| P2 | `plan.py::_Builder` 仍在 Python 逐节点编译、reindex、转 contiguous 数组，`plan.grid` 与 bridge各有输入封装。 | 有适配/复制成本；是否重复大矩阵、占峰值多少，须按同一输入测次数、字节、RSS，再优化。静态检查不能证明已出现整份重复驻留。 |
| P2 | 已有批量产品维度并行；streaming 逐 Bar rayon 已因实测退化撤回。 | 不应为“全模式并行”另造调度器。按真实多产品/横截面密度测串行阈值、吞吐与额外内存，再决定微批/常驻线程；保持时间切片 barrier。 |
| P1验收 | 小规模 T/TL、本机原生读取/Actor/策略/报告测试已完成；长窗口、多产品、多策略、实际 Celery Job 与公网最新 wheel 的同口径验收仍未由本次证实。 | 需记录数据规模/窗口、冷暖缓存、版本、重复次数、wall time、峰值RSS与稳态斜率、读取/跨语言调用/Plan执行次数、结果逐点及交易经济账对账。不能用4,000 Bar替代长回测容量验收。 |

`CategoryBoolRef` 的公开 batch/Python 入口及 `BarDistanceExpr` 的旧公开
构造语义也需进入入口对照表；不能仅用 TradeResearch facade 的测试推定
alpha 独立公开 API 的所有分支等价。

## 本次最小实测

GTHT Python3.14，alpha公开API，无行情读取：

- `ColumnRef('CLOSE').signal_align('30min')`：plan_blockers 返回 SignalAlign，
  to_plan_spec 却生成 column/signal。
- `term_spread()`：plan_blockers 返回 TermStructureExpr，to_plan_spec 生成 term。

这验证清单不一致，**没有**验证上述节点在所有数据/参数下数值正确。
未改 alpha 源码或重新执行长性能基准；CLI命名改动不算解决这些缺口。

## 后续顺序

1. 先统一公开batch/spec/bridge的能力合同与因果正确性，特别是 SignalAlign；
   以独立手算/前缀对照约束，不能以旧高收益为正确性判据。
2. 接通公开batch的signal/term/category等分支到共享Rust核心，删除替代数学。
3. 运行级多策略共享：一次读入/共享根/CSE，多消费者；先做真实两策略验证。
4. 最后在相同真实任务上测长历史RSS/吞吐与端到端Job；未测不得声称提速。
