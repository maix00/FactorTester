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


## 实施复核：公开 batch、共享策略与长回放（2026-10-27）

以下状态取代上文同名缺口的旧结论；保留原审计便于追溯。父仓库实现提交
`ce76f1c2d`，alpha `58a2e24`、`898bb15`，Nautilus `1c4c1b83c0`。
仅本机实现/测试，没有推送、部署、生产压测或前端修改。

### 入口及因果合同

- SignalAlign 不再覆盖 Python evaluate。目标网格、逐产品观测采样及作用域
  asof 映射交给 Rust PanelPlan；数值节点由同一个 FactorPlanKernel 执行。
  Python 只冻结日历和适配矩阵，不保留另一套采样数学。
- 嵌套频率只向前填充已经可用的内层值；不会拿稍后到达的 Bar 回填过去目标。
  gap、first/last、include_current、稀疏观测、冻结 end anchor 和任意输入前缀
  均有独立标量/真实 incremental 入口对照。跨 session 不延续上一段采样值。
  原先目标 150 误用时刻 200 的测试断言已修正；测试不以旧收益为正确性依据。
- TermStructure 的 Python 逐时刻扫描和 NumPy polyfit 删除。曲线按实际
  available_at 映射，Rust pair/fit kernel 统一 spread/slope/curvature；多个指标
  共享打包曲线。负/非法排名拒绝；超大但合法排名按实际曲线深度分配并返回 NaN。
- plan_blockers 按 batch/incremental/bridge 及具体配置报告，不再一概阻挡 signal/term。
  这不代表 Category 公开 batch、旧 BarDistance 构造等其他边界均已迁完。

### 运行级共享及隔离

规划保存全部 strategy_families；同一冻结 ref 只解析一次。同输入/时钟的 roots
合成一个 CSE Plan、一个 Actor、一次 Catalog 回放，多原生消费者订阅同一发布。
不生成每策略行情面板、不自动保存完整因子历史；最终检查仅查询最近一份输出。

产品局部祖先跨策略共享；横截面计算必须尊重每个策略的产品集合，因此在横截面
barrier 注入产品掩码并分别形成必要输出。排序结果可以按输出共享，消费者只筛选
自身产品。真实双策略测试验证 singleton rank 均为 0.5，而非误用全市场排名。
同一 Instrument 的独立目标在 Nautilus NETTING 下不能逐策略归属，重叠时明确要求
HEDGING，不虚构第二套账户/行情。空产品集合和规范化后重名均在加载前拒绝。

### 内存诊断与修复

初版百万 Bar 峰值约 661–681 MiB，两百万约 1046 MiB。关闭因子/策略的原生引擎
仍复现；Cache 各产品仅 10,000 根。主要问题是调用方沿用 BacktestDataConfig 的
optimize_file_loading=False：每个文件独立建立查询及预取，内存随文件数放大。

TradeResearch 调用原生 optimize_file_loading=True，将同精度 Catalog 目录作为
流式表；不新增读取器、不修改 Nautilus 算法、不关闭 Cache/报告来掩盖占用。
读取前冻结数量预检、查询预算、时间戳组硬上限及逐来源数量核验仍保留。
不同精度目录可能走原生按文件回退；本次同精度输入的结果不能替代该路径容量验收。
DataFusion 预算不涵盖所有分配，不能宣称进程具有绝对内存硬上限。

### 基准条件与测量

Mac16,12 arm64，24 GiB，macOS 26.5，GTHT Python 3.14.0。公开 alpha 扩展 dev
opt-level=0；组合 Nautilus 扩展 dev（workspace=0，依赖=1）。未清系统文件缓存，
每个样本启动新进程，不与本次其他构建/测试并跑；共享宿主仍可能有外部负载。
以下耗时不含 staging/编译，长回放包含原生报告导出；RSS 为整个新进程峰值。
扩展 SHA256：alpha 48b67f8186c38c70a2d2bc92cfe05f696579440a58eb70bdc949f71dbfd37021；
Nautilus d64d343f52353a1aab7dccc57e5cf40c5b5a08234a50ce1120a78f79553449a1。

公开 batch：20,000 行、200 份变化曲线，修复前源代码固定 f195155，使用同一已安装
扩展，前/后各 3 个新进程。每个完整输出与独立公式对账：

| 项目 | 修复前中位 | 修复后中位 | 限制 |
| --- | ---: | ---: | --- |
| SignalAlign | 1.811 ms | 3.639 ms | 简单小输入增加约 1.83 ms 的 Plan/网格准备开销，不能称该项提速 |
| Term spread | 1833.382 ms | 16.376 ms | 此曲线规模约 112 倍；不是所有 term/真实 Job 的通用比例 |
| 进程峰值 RSS（最大样本） | 112.22 MiB | 114.63 MiB | 公开 batch 按请求保留完整输出，非流式常量内存 |

共享长回放：2 产品、2 分组策略、mean(20)+median(4096)，3 个节点。合成周期 OHLC
使用连续分钟时钟，**不代表真实交易日、真实收益或研报复现**。每个规模 3 次：

| 每产品 Bar 数 | 总 Bar 数 | 耗时中位 | 峰值 RSS 范围 |
| ---: | ---: | ---: | ---: |
| 10,000 | 20,000 | 0.199 s | 310.9–314.8 MiB |
| 100,000 | 200,000 | 0.649 s | 377.0–383.3 MiB |
| 500,000 | 1,000,000 | 2.664 s | 436.0–462.2 MiB |
| 1,000,000 | 2,000,000 | 5.186 s | 463.5–476.6 MiB |

每次均验证 1 Actor、3 节点、最大回放批 2048、每消费者恰好收到每个切片、每切片
只排序一次、0 Python factor-Bar 回调；末尾两个窗口的值与独立 NumPy oracle 对账。
较大两个规模没有再出现原来的近线性 RSS 放大；不同规模预取、线程分配器及文件
元数据仍有成本，此结果不是任意数据规模/机器的“性能最优”证明。

另以本机真实 T2403/TL2406 各 10,000 分钟 Bar（原始价格/时间戳不改写）跑原生
多策略，耗时 0.200 s、峰值 320.1 MiB，产生 6 笔订单及 HTML/CSV 报告；元数据为
明确标记的合成合约探针规则。验证共享链路与数值，不作为手续费/研报经济收益验收。

复现入口：

```sh
python -m tests.benchmarks.bench_public_batch_signal_term --output /tmp/public-after.json
python -m tests.benchmarks.bench_public_batch_signal_term --baseline-ref f195155 --output /tmp/public-before.json
python -m tests.benchmarks.bench_shared_strategy_long_replay --stage-real --root /tmp/real-t-tl --rows 10000
python -m tests.benchmarks.bench_shared_strategy_long_replay --root /tmp/real-t-tl --output /tmp/real-t-tl-result
python -m tests.benchmarks.bench_shared_strategy_long_replay --stage-base /tmp/real-t-tl/manifest.json --root /tmp/stress --rows 1000000
python -m tests.benchmarks.bench_shared_strategy_long_replay --root /tmp/stress --output /tmp/stress-result
```

本机回执位于 /tmp/tr-public-batch-*-20261027.json、
/tmp/tr-shared-directory-summary-20261027.json、
/tmp/tr-shared-real-10000-result0-20261027/measurements.json；临时文件不是长期权威存储。
聚焦提交钩子 328 passed、1 skipped；后续同入口复核 320 passed、1 skipped，新增消费者
边界 14 passed。跳过项为已退役的进程内 _factor_series_sink 测试，不是缺 Nautilus 扩展。
Rust alpha 217、原生 adapter 28、Catalog runtime 1 项通过。未跑全仓测试。

仍需另行验收：Linux release wheel、Celery/RabbitMQ/公网实际 Job、异步/缺观测增量
产品的原生截面合并，以及异精度 Catalog 的资源预算；本轮未用小测试替代这些结论。
