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
- 仍存在旧 Python 状态机。必须先完成参数和时间语义的严格对照，再移除其生产入口。
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
