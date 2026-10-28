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


## 后续实施：Category / BarDistance / 真实 Celery Job

固定实现：alpha e6d7b78、7f8bb56；TradeResearch ed0dc6ba4（父提交 b76e09a89，
其中前端由另一执行者提交，本轮没有修改前端）。Nautilus 仍为 1c4c1b83c0，未改动。

### 公开 batch 的统一计算

CategoryBoolRef、CURRENT/CANDIDATE MatchBarDistanceExpr 与旧布尔 BarDistanceExpr
均继承公共 Plan evaluate。PanelPlan.add_kernel 只负责按产品观测 lane 推进同一个
FactorPlanKernel 并散布结果，不新增 Python 数学或第二套匹配算法。稀疏产品不把 union
空行计作 Bar；每个 lane 复用输出和有界窗口。公共 API 的旧 Python Category 行循环、
Match 谓词/窗口扫描及 bar-search 数学 fallback 已删除。

CategoryMembership 定义为完整的生效快照，后一个空集合会移除标签；不能并集累计
所有历史标签。无时间戳快照从最早时刻有效，未来快照不提前应用，同一时刻冲突快照
拒绝。Rust 只维护当前 mask 与前进游标，每个变化消费一次，避免每 Bar 扫历史规则。
时间戳倒退在更新前失败。公开测试覆盖负时间戳、移除、未来规则和所有输入前缀。

CURRENT/CANDIDATE 的 nearest/farthest 是历史匹配；旧布尔 BarDistanceExpr 是事件年龄，
不混成同一公开语义。匹配共用 Rust deque kernel；farthest 的历史匹配不会再被当前
Bar 的零距离覆盖。nearest 当前即命中时直接返回，不额外扫描窗口。非有限谓词结果
不当作真；显式 NaN 默认值用 JSON null 传输。负号谓词序列化为已有减法节点。

这里的完成范围是 alpha 的公开 batch 与其 incremental/bridge 核心。TradeResearch
兼容 DSL 中更宽的 bar_search_eval（外部序列/Where 等）仍有旧 Python fallback，不能
把本节说成全平台所有旧数学路径都已删除。其滚动回看与分段 scope 合同还须分别冻结，
再消除重复实现，不能直接删掉功能使测试通过。日频 SignalAlign 的交易日收盘权威
日历等先前边界也不能由本次 30 分钟 Job 推定已接通。

### SignalAlign 的性能回退

剖析确认有可避免的开销：已排序 asof 仍分配全量(timestamp,index)临时向量；
单产品也走 concat；相同索引再做 isin；Plan 重复遍历图；简单网格元数据构造
dataclass。已分别改为无排序临时向量的原生线性指针、单列视图、同索引快速观测
mask、一次图遍历和轻量 NamedTuple；直接构造 ns DatetimeIndex，不走日期解析器。
所有目标采样/因果规则不变，不恢复旧 Python 采样数学，也不在图外另建缓存。

同上一节机器、dev 扩展、20,000 行/200 曲线的公共入口，新进程各一次，共5次，
不清系统缓存；SignalAlign 为 2.502/2.531/2.415/2.485/2.449 ms，中位 2.485 ms，
峰值 RSS 112.0–113.8 MiB。相比上一轮 3.639 ms 中位约少32%；仍比最初 Python
实现 1.811 ms 多约0.67 ms。样本跨实现批次，宿主非独占，不是严格CPU隔离的提速
承诺；没有宣称完全消除回退或所有规模最优。回执 /tmp/tr-signal-final-after-*-20261027.json。

新扩展下再跑双产品各1M根的共享原生回放：5.243 s、峰值477.3 MiB、一个Actor/
3节点、最大批2048、两消费者各1M次、排序1M次，末尾窗口逐值对账。与前批范围
基本一致；这是单次合成连续时钟容量复核，不是完整真实行情经济回测。
回执 /tmp/tr-shared-remaining-long-final-20261027/measurements.json。

### 真实 RabbitMQ → Celery → Nautilus → CouchDB

新增可显式运行的 tests/benchmarks/verify_native_celery_job.py，限定 localhost
和专属测试实例。使用真实 T2403/TL2406 各10,000分钟Bar、独立 Job SQLite、冻结
RunSpec/执行计划、嵌入且校验身份的家族源码、真实 worker 和默认 NautilusJobExecutor。
没有 eager、mock 策略或替代执行器。原生20分钟mean、内外30分钟SignalAlign共享
4节点；基础执行策略明确为 basic、零手续费及合成合约探针规则，不是原研报收益结论。

实际尝试暴露并修复：

1. GTHT 未声明 Celery，补 environment.yml 的 celery==5.6.3 并在 GTHT 安装验证，
   测试检查真实依赖存在，不再靠 importorskip 掩盖环境缺失。
2. 冻结家族解析后的 RollingOp 会直接持有 ConstExpr('20m')，旧编译器只接受整数
   或 WindowBarsExpr。现复用已有 _resolve_windows/交易日分支处理直接时长常量，
   不改变单位、不增加另一套窗口计算。
3. Group-1 与 Threshold-1 名称不同但 Nautilus 的 order_id_tag 均为1。alpha bridge
   只对冲突尾号追加确定的、避开冻结尾号的 factor 序号，输出 logical→native 映射
   供报告归属核查，不改 Nautilus 或撮合/账户规则。跨独立既有策略集仍遵循原生冲突
   检查，不擅自改名。真实混合策略回归覆盖了此路径。

独立 worker 的三次完整验收（耗时包括 worker 启动、执行、CouchDB及轮询，不含staging）：

| Job | 模式 | Bar | 订单 | 终态 | 耗时 | 采样worker最大RSS |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| acceptance-c4a4628ec7f9-native | 两分组+阈值，共3消费者 | 20,000 | 8 | succeeded | 1.736s | 391.9MiB |
| acceptance-f005b07a3f87-native | 分组第1/2组 | 20,000 | 6 | succeeded | 1.552s | 383.1MiB |
| acceptance-37b48ee779e2-native | 阈值 | 20,000 | 2 | succeeded | 1.558s | 381.9MiB |

RSS 由父进程约每0.2秒读取 ps，是采样最大值而非精确峰值。每个 Job 均有独立task ID、
不同于提交进程的 worker PID、持久终态、非空 report_ref，5份 CouchDB 附件逐份SHA256
校验；阈值不需要排序，rank_passes=0，分组及混合各10,000而非按消费者重复排序。
三个原始回执及导出的 Couch 文档保存在 /tmp/tr-real-celery-{mixed,group}-final-20261027/
和 /tmp/tr-real-celery-threshold-final2-20261027/。本地Job DB/HTML/CSV保留供检查。

运行方式见 runbook。专属测试 RabbitMQ/CouchDB 与 worker 结束后关闭；不触及其他
服务器/队列。本次是实际冻结计划执行和报告存储验收，未验证 HTTP authoring/planning、
生产调度、Linux release wheel、研报收益、实盘或所有参数组合，也没有公网部署。

验证：Rust core219、原生adapter28+Catalog1通过；公开入口聚焦112通过；Job相关68通过；
本次实现提交钩子343通过/1跳过。计数有交集。唯一跳过仍为已退役进程内sink测试。
未执行全仓测试。回退可在授权任务分支 revert ed0dc6ba4 并重建此前 alpha gitlink/组合扩展；
不能 reset 共享工作区或覆盖另一执行者的前端改动。


## Search 路径真实 Job 与长回测验收（2026-10-27，台北）

起点主仓库 `29cc222f4`、alpha `b2d46b3`、Nautilus `1c4c1b83c0`。
共享 worktree 的前端改动由另一执行者负责，本轮未编辑或提交前端。
实现/测试提交：主仓库 `60bd5716d`、`90dabe5de`；alpha `6664463`、
`83054f0`。Nautilus core 未修改。仅本机隔离验收，无推送、部署、生产任务。

### 验收发现并修复的实际错误

长回测不是只看 kernel。10,000 根真实价格循环的合成压力输入，两个分组
策略在 HEDGING 下不断调仓时，FamilyStrategy 未向 submit_order 传已有
position_id。本应平仓的订单创建反向持仓；200万 Bar 后798条持仓全部仍开着，
400万 Bar 后1598条全部仍开着。5秒 macOS sample 的主要热点为
FamilyStrategy → positions_open_refs → get_positions_for_ids 排序。
这也说明此前“Job成功且报告存在”的回执不足以证明持仓语义正确。

修复只在 alpha adapter 的 family.rs：从策略/品种过滤后的原生持仓取得 ID，
调仓订单绑定该 ID，让 Nautilus 原生执行器处理平仓、部分成交和反转。
不增加平行持仓账本、Python逐Bar回调或Nautilus core补丁。新增真实双策略
HEDGING 反转测试：修复前失败，修复后每个策略只剩一笔单位持仓，已有持仓
正常关闭。单策略 NETTING 及共享策略回归也通过。旧错误结果只作诊断证据，
不作为正确的持仓/收益验收。

### 实际 Celery/RabbitMQ/策略/CouchDB

使用独立 localhost RabbitMQ/CouchDB、真实非 eager worker、默认 Job executor、
冻结 RunSpec/ExecutionPlan/内嵌 FactorFamily，T2403/TL2406 各10,000根未改动
分钟行情和时钟。Instrument 规则为明确的测试 probe/basic 配置，不能解释为
交易所官方历史费用或研报复现。家族的外层信号30m；内层滚动均值2 Bar并以3m
SignalAlign形成；Where(CURRENT/CANDIDATE/当前内层信号)搜索使用120 Bar分区和
独立60 Bar回看。全部计算在同一个Rust计划中。

| 模式 | Job | 订单 | 已关闭持仓 |
|---|---|---:|---:|
| 混合2个分组+阈值 | acceptance-870e645292d7-native | 975 | 466 |
| 分组第1/2组 | acceptance-fcd92a65bac6-native | 660 | 313 |
| 阈值 | acceptance-42bd895ab7ea-native | 315 | 153 |

三者均终态SUCCEEDED，1个Actor/5节点、各策略共享signal输出槽0，
每策略10,000次发布；分组排序10,000次（不按消费者重复），阈值单独运行排序0次。
Python因子Bar回调0，最大回放批40 Bar。成交发生在首个已形成30m信号之后，
期末未关闭持仓数受策略×品种数约束，完整报告的5种HTML/CSV附件经CouchDB
读回并校验SHA256。worker采样最大RSS分别403.3/405.0/373.8 MiB；是200ms采样，
不是精确峰值。Celery时间包含启动、网络和轮询，部分与构建并行，不能作吞吐基准。

回执：`/tmp/tr-search-celery-{mixed,group,threshold}-final-20261027/receipt.json`。
同目录保留Job SQLite、Couch报告JSON与本地HTML/CSV。验收完成后仅本轮worker、
唯一队列和专属RabbitMQ/CouchDB容器已关闭清理；无常驻测试服务。

### 长回测性能与内存

macOS26.5 arm64，物理CPU10核、RAM24GiB；GTHT Python3.14，Nautilus2.0.0rc8，
原生组合扩展dev opt=1。各次独立进程，OS文件缓存未清；性能测量期间不并行运行
本轮测试、构建或其他基准。准备Catalog在另一进程，时间/RSS排除staging，包含
真实Nautilus引擎、撮合和报告生成。128MiB总查询预算，最大回放批2048 Bar。
两个策略共享1Actor/5节点、相同signal/confirm输出槽，各源数据由原生Catalog
扫描和分发，不复制完整Python行情面板。

使用同一个10,000 Bar价格循环、合成连续分钟时钟。不能当作真实交易日历、
交易所规则或收益证据。200万/400万表示两个产品的Bar总量：

| 总Bar | 订单 | 修复前秒（1次） | 修复后秒（3次） | 中位秒 | 最大RSS MiB |
|---:|---:|---:|---|---:|---:|
| 2,000,000 | 798 | 37.8429 | 5.4178 / 5.4571 / 5.4175 | 5.4178 | 510.5 |
| 4,000,000 | 1598 | 149.8668 | 10.9130 / 10.8315 / 10.5983 | 10.8315 | 573.2 |

修复前后最新因子输出逐项相等、订单数相等；修复后的期末开仓均2条，分别有
398/798条已关闭持仓。当前机器上两规模均满足本次预算：耗时<20秒、RSS<768MiB。
样本少且前后重复数不同，不能当作总体统计显著性。只能说这一高换手输入消除了
已证实的持仓累积与超线性热点，不能宣称所有策略性能最优。

先前2,000 Bar价格循环几乎不换手（只2订单），2百万Bar约5.1秒；
不能把它和10,000 Bar循环直接比较或宣称400万Bar需要150秒属于正常线性增长。

Rust Search状态另外以10万次更新检查预热后的容量恒定：history<=60、
events<=61，分区清空复用容量。两个产品各持有自己的窗口状态，共享节点不按
策略重复。此为计算状态预算，不等于整个进程RSS恒定：Catalog文件元数据、
Nautilus成交/持仓历史与报告仍会增长。4百万Bar的最大RSS高于2百万，尚无证据
可声称整个运行内存仅取决于窗口；这里验证的是给定规模下的实际资源预算。

固定回执 `/tmp/tr-search-acceptance-20261027.json` 包含样本、来源提交及Celery
回执哈希。长回测完整输出：`/tmp/tr-search-final-{1m,2m}-{0,1,2}-20261027/`。

### 正确性与覆盖边界

嵌套3m/1m Where匹配有独立手算oracle，完整及缺失Bar的多个输入形状均逐前缀
对账batch/增量Rust；另测夜盘冻结交易日、bar_since/bar_distance分区与回看
反例。未因缺失Bar而提前看到未来信号。核心219项、adapter28项+Catalog集成1项
通过；主仓提交聚焦检查343通过/1项退役sink跳过（不是缺少扩展），未跑全量测试。

仍不涵盖公网/Linux发布、HTTP authoring/planning、所有日线结束时间/任意日历、
官方历史交易规则、原研报收益、所有跨品种及任意自定义谓词。一般复杂匹配仍可能
最坏O(T×lookback)，同一Rust核心与CSE不意味着任意谓词都可O(1)。

回退仅需在获授权的任务工作区反向提交主仓90dabe5de（恢复此前alpha gitlink）并
重建原生扩展；不得reset共享worktree或覆盖并行前端改动。回退会恢复已知错误，
所以不能把旧HEDGING结果重新当作正确验收。
