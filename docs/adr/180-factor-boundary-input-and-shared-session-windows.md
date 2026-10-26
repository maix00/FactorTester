# ADR 180：因子边界输入与共享交易日窗口

状态：部分实施，存在代码偏离。对应 #443；2026-10-26。

## 决策

- `SessionReset` 是事件分段累计的唯一算子状态实现。编译器在 Plan manifest
  声明 `boundaries` 的稳定顺序，边界叶节点从 channel × product 的 `u8` 切片读取。
  `MarketBar` 携带该次已完成切片的边界标记，Rust 内核只借用输入。
- 事件由源适配器提供。`event_line.latest` 的新 occurrence、显式逐产品标记，或
  权威 `trading_day` 可以触发重置；不从系统日期猜测交易日，也不把交易日误作日内 session。
- Nautilus 的 `FactorBoundary` 自定义数据必须先于同时间片 Bar 到达；迟到的边界
  明确失败。Actor 限制待处理边界数量，复用零值缓冲，与不完整行情一起过期清理。
- DataActor 的原生 `on_bar` 与手动切片入口复用同一个截面等待和执行路径。
  每个完整切片只更新一次，只有一个最近输出，不另存一份结果历史。
- batch 与 incremental 都使用 `SessionWindow` 解析接收位置。完整日历的预计
  Bar 容量不能充当实际回放位置；中途开始、缺 Bar、union 空行均须保持正确边界。
  同 session 更新为 O(1)，换 session 二分定位；日历不逐 Bar 克隆。
- `interval_bars` 是逐产品、包含两端、只计已形成原始 Bar 的因果序列。
  batch 用线性前缀计数；streaming 用一个整数，O(1) 状态。NaN 观测仍计数，union 空行不计。
  固定 `window_bars` 保留窗口容量的标量语义，不把异步产品不同容量伪装为同一标量。

## 并行与共享边界

PanelPlan 按拓扑节点完成整批计算：产品 lane → 截面节点 → 后续产品 lane。
这已构成批量屏障，不另建逐 Bar rayon 调度器。在线增量仍使用同一有状态内核。
同一引擎、冻结产品顺序、输入源、时钟、事件语义的一组因子应合并为一个 Plan，
策略只消费发布结果；不能仅凭因子名字共享不同输入语义的 Actor。

## 分段与 timeline 的单向依赖

分段数值运算统一在 alpha-algo：公开 alpha.factor 与 tools 适配器均调用矩阵
`scope:*` 或具有权威日历的 `session_rolling:*`，不再保留 Python 逐 Bar 聚合。
旧标量极值循环仅作为 tests 下的独立 oracle 和基准，不是运行 fallback。
同分区极值并列选择最早观测；截断右端后候选集合冻结，但到当前 Bar 的年龄仍变化。
普通 min/max 继续压缩相等值，避免为修复 arg 极值而增加普通极值的缓存。

Timeline 的唯一实现位于 `alpha.factor.timeline`，不导入 FactorTester。
tools.timeline 只将 DataIndex 的源频率、事件时间和交易日标签传入该实现；
旧构造器是适配类，compact/scatter 直接复用公开函数。同频矩阵 Plan 直接使用
已经形成的 observed/day 数组；不重复 factorize，也不为每个算子建立目录。
稀疏产品取源频率和冻结产品的 union；原始 NaN 仍是观测，union 空行不是观测。
对齐保留已知的夜盘交易日和事件时刻，未知标签明确失败，不能静默改成自然日。

公开 SessionScope 不再使用不存在的 gap_ns；静态 session 直接进入共享 Rust
session-window resolver，作用域身份包含完整冻结日历，防止不同日历被 CSE 合并。

同机 GTHT Python 3.14，5000 行 × 4 产品、scope_bars(250) 的 mean，4 次本地运行
丢弃首次热身：逐 Bar 适配中位 2.142541 ms，矩阵适配中位 0.230667 ms，末行相同。
这是局部合成入口测量，不含真实 Job/I/O，也不是跨规模的最优性结论。

## 验证及性能证据

本机 arm64、Rust 1.99.1、release、已编译且已热身；不含源码编译、数据 I/O 或浏览器。
`bench_panel_barrier`：8 产品 × 100,000 Bar，mean(480) → zscore → mean(20)，
5 次测量；单线程中位 28.494 ms，4 线程中位 11.725 ms，checksum 相同。
macOS `/usr/bin/time -l` 进程峰值 RSS 分别为 34,439,168 与 46,301,184 字节。
四线程约快 2.43 倍，但增加约 11.3 MiB，不能据此宣称所有规模或真实 Job 都更快。
另有逐元素测试同时对账单线程 batch、四线程 batch 和 incremental，非仅 checksum 比较。

## 未完成边界

- 实际策略构造器的所有 role 已合并到一个共享 Plan，使用 RunSpec 冻结 ref，
  不再生成 role 名称伪 ref。订阅者引用同一发布，保留最近两个值并独立累计计数。
  跨不同策略构造器的运行级合并仍需核对，不能据单策略多 role 的测试声称全部完成。
- Cython Nautilus 策略入口仍可能经 Python 逐 Bar 适配；Rust Actor 注册与回调测试
  不等于真实 RunSpec/Job 已全程无 Python 回调。
- `StreamingFactorPlan`、`compile_streaming_factor`、`RustIntervalNode` 及旧 bar-search
  状态机已删除；测试改走真实 Rust 编译入口并覆盖跨交易日扩展与淘汰。
  `streaming/incremental.py` 仅保留编译适配、单输出视图与窗口/事件元数据解析。
- 完整日频 SignalAlign close、稀疏产品增量观测掩码等不得凭节点存在声称验收。

没有执行全仓测试、公网负载、推送或部署。

## 固定窗口树节点内存修复

`OrderStatisticTree` 删除最后一个相同值时回收节点槽位，插入优先复用空闲槽位。
节点存储随历史最大活跃窗口增长，而不再随回测长度增长；计数重复值仍共用一个节点。
quantile、rank、MAD 共用此树，无第二套回收实现，也无逐 Bar 全树扫描。

本机 release、固定窗口 480、100 万个不同值、5 次运行，`bench_window_memory quantile`：
修复前耗时中位 149.397 ms，峰值 RSS 364,380,160 字节；修复后中位 149.401 ms，
峰值 RSS 1,884,160 字节。RSS 是包含五次运行及分配器行为的进程峰值，并非单树大小；
此实验说明该输入下内存增长消失，不代表整个 Job 的内存或所有算子的耗时。
回归同时验证 quantile/rank/MAD 的数值、窗口 480 的长期节点上界、重复值删除后复用。

## 行情加载前限制与分批回放

probe 和策略复用 `iter_catalog_bar_batches`。先读取已经校验文件哈希的目录收据，
检查总行数上限，再按 `first_available_ns`/`last_available_ns` 及固定时间批查询。
Nautilus 的 Parquet 查询过滤 `ts_init`，不能把 `ts_event` 当作可用时间边界。
策略复用原生 `streaming=True` 回放，加载一个批次后释放 Python 批次，执行后
`clear_data`；失败也清理当前原生输入。两产品真实小窗口回放验证跨批次策略状态持续。

时间批不是任意数据频率下的固定条数上限；总体条数上限来自冻结收据，任务资源限制
仍是独立保护。不能把该改动宣称为零复制或无需控制 Nautilus Cache/报告大小。

## 2026-10-27 正确性复核（第一批）

固定截断快路径必须先确认 `trunc_start <= trunc_end`，再转换无符号宽度；
反向区间走空区间结果，不能溢出。独立测试 oracle 改为直接枚举候选集合，
不调用生产实现，覆盖 `[NaN, 1, 2].truncate(0, 0)` 和反向截断。

scope 极值合同：候选集合为 `[start, min(end, current)]`；有效值不足
`min_periods` 或传播模式下候选中含 NaN 时输出 NaN。忽略模式下当前 NaN
不额外清空结果，候选区间外的 NaN 不影响结果；正负无穷参与极值排序。
并列保留最早位置。归一化为 `(current - winner) / (current - start)`，
单点输出 0，缺失值不压缩 Bar 距离。raw 与 rolling/truncate 的坐标对齐
仍须单独验证，不能由本批 scope 测试推导已完成所有入口一致性。

Actor 完整切片直接从现有槽位填充复用的数值缓冲，删除临时 `Vec<Bar>`。
到齐计数只在空槽第一次填充时增加，覆盖重复品种、过期和未来切片路径；
每根 Bar 不再扫描所有槽位。尚未测端到端分配次数或真实 Job 峰值 RSS，
不据此宣称整条回测零分配。

## raw 坐标与移动截断窗口（第二批）

raw 返回父窗口左端开始的 Bar 偏移，可以直接作为同一窗口下一层 truncate
的端点；不是距当前时点的年龄。归一化极值仍使用上述年龄/位置跨度公式。
固定截断的延迟队列保存候选获胜位置，输出时再转换坐标，避免延迟后的
归一化比例被错误冻结。动态结束点为负表示空候选，不再被误当作“未指定”。

batch 的截断 rolling 原先把不断移动、但落在当前 Bar 之前的结束点传给
区间状态机，可能冻结旧候选。现在该分支复用 FactorPlanKernel 的 rolling
路径；不新增第二套窗口算法。未截断窗口仍直接使用 IntervalKernel。
独立标量扫描对所有输入前缀逐点验证 min/max 的位置与均值，包括重复极值、
NaN、正负无穷、反向与单元素候选。bridge 回归验证 raw 输出再次用作
truncate 端点时选回同一原始值。该验收不等同于原研报真实 Job 验收。

## 2026-10-27 原生流式查询接线与目标边界

Nautilus 的 `query_batch_session` 已有 typed pages 和时间戳对齐，本次只补
Python `query_bar_batches` 的薄绑定；`next_batch`、关闭和错误清理均由原生
session 持有。可独立指定软批大小及同时间戳组硬上限；跨数据源仍需检查
合并后的整组数量。查询按冻结收据的 ts_init 可用时刻限定范围，不改写
Bar 的 ts_event。转换后的 Catalog 读回验证也应使用可用时刻。

DataFusion 查询内存池预算与 spill 上限独立于回放批大小。清理查询表时
只复用 memory_pool 和 disk_manager，必须重建文件列表与元数据缓存；
保留整个 RuntimeEnv 会使新增的 Catalog 批次不可见。真实追加批次读回测试
已覆盖该回归。DataFusion 并非所有分配都受内存池约束，仍需 worker 的
进程级资源限制；本次不宣称整进程内存上界已完成验收。

目标是 Rust 数据面与 FactorTester 控制面：注册、权限、冻结身份及 RunSpec
留在 FactorTester；扫描、排序、跨品种合并、共享 Cache 和回放分发归 Nautilus。
因子 bridge 必须进入同一个 runtime，不能另起数据管理器重新读一份行情。
相同输入/时钟的因子共享计划，订单与账户状态保持各自归属。首次转换生成的
日历、范围与摘要应冻结复用；实时适配器与历史回放遵守相同的事件/可用时刻
合同，但不共享可变回放缓存。

当前 Python 绑定、逐 Bar 迭代及 heap 合并是明确的过渡实现，不是目标架构，
不得把本次读取改进称为零 Python per-Bar 或完整 Rust Job。后续切换必须以
Nautilus 原生 BacktestNode/DataIterator 分发给 FactorActor 与执行系统，完成
同一真实任务的读取次数、跨语言调用、耗时、峰值 RSS 及结果逐点对账后，
再删除过渡读取/合并与 Python 因子事件适配器。

聚焦验证：真实 T/TL Catalog、真实阈值/分组 Strategy、原生 batch 绑定及
合成清理/多源时间戳组测试共 18 项通过；原生 session 9 项、查询预算重置
1 项通过。均非全仓测试，也未在公网运行负载。

容量样本（仅一次、缓存未清空）：macOS arm64、GTHT Python 3.14、Nautilus
本机 dev opt-level=1；T/TL 各 500 根真实分钟 Bar、共享 CLOSE rolling(20)
计划和原生分组 Strategy。1000 根回放分 25 批，最大 40 根，发布 500 次、
计划 2 节点。转换 Catalog 后的进程峰值已达 282,312,704 字节，回放/报告后
峰值 386,826,240 字节；回放与报告耗时 0.159604 秒。耗时不含前面的转换，
峰值包含转换且是高水位；该样本不是泄漏证明、端到端 Job 基准或提速比例。

## 原生 BacktestNode 与 FactorActor 接线（2026-10-27）

`nautilus_factor_bridge::replay::attach_factor_plan` 在调用方已经冻结的
BacktestRunConfig 上注册一个共享 Actor。调用方继续运行同一个 Nautilus
BacktestNode；Catalog 扫描、跨文件归并、分批回放及 DataEngine 分发均使用
Nautilus 的实现。bridge 不另建读取器或 Cache，不使 Nautilus core 依赖 alpha。
调用者必须在 node.run 后检查返回的 FactorReplayHandle；Nautilus 默认仅记录
Actor 回调错误，因此因子首次错误另行保存并请求系统停止，不能据 node.run
返回成功就发布结果。结束时未到齐的产品切片同样失败。

Actor 启动时订阅冻结的 BarType。产品次序保留 Plan 给定次序，不再字典排序；
Bar 的 InstrumentId 映射到对应产品槽位。OHLCV 字段一次解析为枚举，以 kernel
既有的 product-major 输入布局填充复用缓冲；未知字段（如 Bar 没有的持仓量）
明确拒绝，不能代替为收盘价。字段数在读取 Catalog 前对齐 Plan 的冻结输入需求。
输入时钟 timestamp_ns 表示 Bar 时刻，available_at_ns 表示该切片全部输入实际
可用的最晚时刻；FactorUpdate 同时保留两者。正常路径不锁共享错误状态，也不再
每次逐个比较冻结的产品字符串；错误锁仅在失败或结束检查时使用。

验证入口：`native/nautilus_factor_bridge/tests/catalog_runtime.rs`。纯 Rust 创建
真实 Nautilus Catalog，分两文件写入 8 根测试 Bar，以 chunk_size=2 原生回放，
不经过 Python，也不手动调用 Actor 的 Bar 回调。逐点校验 rolling(2) 均值、HIGH、
Bar/可用时刻；Cache bar_capacity=1，因子仍保持跨批次状态。未知字段和字段数
错误在读取前失败。另有双产品字段布局与产品次序回归，测试 Actor 完成切片的
可用时刻为各输入 ts_init 最大值。该测试不是原研报、真实 T/TL Job 或策略收益验收。

BacktestNode 支持由 feature `nautilus-backtest` 隔离，默认 bridge 不拉入回放后端。
新增 Catalog 后端依赖由独立 bridge Cargo.lock 固定；与 wheel 的锁文件不同会
使首次构建编译部分不同小版本依赖。不能把首次冷构建耗时当作增量部署耗时。

## 原生输出与真实分钟数据校验（2026-10-27）

`FactorOutputSink` 在原生 Actor 内借用当前输出，允许 write/finish 返回错误。
首次错误进入 FactorReplayHandle，Nautilus 停止后必须检查；空输出、未到齐切片、
写入失败与结束刷新失败不能被当成成功。该接口本身不保证调用方有界，验收工具
使用 64 KiB BufWriter 逐行写入，不保存输出历史。正常写入路径不使用共享锁。

冻结 JSON 的 columns 在读取前与 Bar 字段顺序对齐；允许未被计算节点使用的
时钟来源列，但不得缺少节点引用列。期限曲线尚未接入该 Bar runtime 时明确拒绝；
需要 boundary 的计划必须同时声明冻结的 FactorBoundary CustomData 输入，并在
原生读取前注册其 codec。不能向这些通道静默传空值。这些是 bridge 接线校验，
不是新建行情读取器、Cache 或撮合器。

真实 T/TL 数据逐点核验暴露两项计算错误，并在共享 alpha-algo 核心修复：

- SignalAlign last：源时钟跨过多个目标网格点（如休市）时，原实现取了发现缺口的
  较晚 Bar。现在以最后已到达的目标网格点作 as-of，严格模式排除该点本身；
  O(1) 跳过缺失网格，不逐个扫描。小型手算输入和每个前缀覆盖 inclusive/strict，
  bridge 覆盖内层 signal 连接外层 Where。first、其他 anchor/partial 的全组合
  尚未完成同等级验证，不能由本次结果推定全部通过。
- Sum/Mean：增删窗口值的浮点误差可翻转相等阈值的比较。例：20 根周期价格
  经 5,000 次更新后原结果为 101.65000000000002；真实样本也出现均值
  101.64999999999999 与信号 101.65 导致 Where 翻转。共享补偿求和用于
  session 窗口和截断扫描，增删仍为 O(1)，每状态多一个 f64；不引入 Decimal、
  窗口重扫或比较容差。独立参考使用 math.fsum，另测大数消去的小残差。

可复现入口：`tests/benchmarks/bench_native_factor_replay.py` 与独立 Rust 示例
`catalog_replay`（feature nautilus-backtest）。Python 仅冻结输入并作独立对账；
被计时的原生进程由 Nautilus BacktestNode 读取、归并、分发，再计算和写出。
该示例没有交易策略、订单或报告，不是生产 Job runner。

测量环境：macOS arm64，GTHT Python 3.14，原生 dev opt-level=1；没有清空系统
文件缓存，每规模一次预热后 3 个独立进程样本。T/TL 共用 4 输出计划：rolling20
均值、5 分钟 last 信号、Where、shift；chunk_size=40、Cache 每 BarType 只存
1 根。各 500 根的原生读/算/写中位数 0.115 秒，峰值 62,128,128 字节；
各 2,000 根约 0.45 秒、约 90 MB（约 86 MiB）。全部输出、产品、事件时刻、
可用时刻逐点校验。记录 source/binary SHA256 与逐样本耗时/RSS；输入收据冻结
数据来源。夹具每 3 根写一个 Parquet 文件，大量文件元数据也影响 RSS；两种
规模不能证明内存恒定。计时不含 Python 初次转换和参考面板，不能与此前 Python
整进程高水位比较成提速或内存下降比例，也不是原研报收益、公网或 CouchDB 验收。

聚焦验证：native bridge 26 项与真实 Catalog 集成 1 项；公开 API/测试选择器
82 项；session window 26 项；Plan 26 项。正确性提交 hook 额外选择 138 项通过。
没有执行全仓测试。原生接线和离线工具已验证，不代表 Celery 的 Python 过渡
读取/合并/因子事件路径已被替换；切换仍须同一真实策略 Job 端到端验收。
