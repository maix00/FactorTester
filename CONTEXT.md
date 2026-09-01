# FactorTester — 上下文

> 领域语言、架构概览、开发约定。供 Agent 和开发者参考。  
> 架构决策记录见 `docs/adr/`。

---

## 这是什么

FactorTester 是一个量化因子研究与回测平台，面向期货及多资产类别。目前已支持中国期货市场，架构预留了多品种、多频率、多数据源的扩展能力。提供：

- **因子测试** — 多因子 IC 分析 + 分组收益回测
- **多因子分析** — 相关性矩阵、因子合成、IC 热力图、分层回测
- **自定义因子编辑器** — 可视化 DAG 编辑器 + 代码编辑器
- **价格查看器** — 原始 OHLCV / 价格序列可视化
- **因子引擎** — 40+ 内置因子，表达式树 DSL，自定义因子持久化

开发环境约定见 `docs/development-environment.md`；当前标准环境为 Conda `ft`。

---

## 领域概念

### Research Workspace / Run / Job

异步研究不归浏览器页面所有。`session_uuid` 只负责认证，`page_uuid`/`view_uuid` 只用于
当前 UI/runtime 隔离；`workspace_id` 只标识稳定的研究工作上下文，不声明因子家族、
具体因子或因子集合。可编辑的试验草稿配置可以归档在该上下文中，但它不是研究对象
范围，也不能成为 Research Graph 推进门禁。一次冻结配置属于 `run_id`，具体
回测、IC、因子评估或类型分析属于独立 `job_id`。关闭页面不会取消任务，取消只能显式
发生。worker 只接收可序列化 RunSpec 和 planning 后冻结的 ExecutionPlan，不读取页面
FactorTester 或 `page_factors`。Web 与 CLI 统一通过 `/api/test-authoring/workspaces`、`/api/runs`、
`/api/jobs` 管理生命周期。SQLite 只保存低频权威事实；实时 progress/SSE 和行情缓存
属于单机 job daemon 内存，完整曲线/明细属于显式保留的文件 artifact。完整决策见
ADR-037、ADR-038、ADR-039。

Workspace、Work Package 与 Branch 正交：Workspace 是可变执行配置环境，
Work Package 是一项研究，Branch 是其中一条决策路径。研究对象与每次执行分别由
冻结的 factor/factor-set、configuration snapshot、RunSpec 和 TrialPlan 声明；任何
Workspace 等值关系都不得成为 Graph、Evidence、报告或 Job 的门禁。完整决策见
ADR-047。

### Agent Assistance Document

需要智能体协助填写的页面注册一个版本化结构文档及其 schema、导出、校验和原子导入
Adapter。Profile Agent 通过短期页面通道一次读取或替换完整文档，不逐字段操作 DOM。
测试页面文档中的 `configuration` 与随后 RunSpec 冻结的 `configuration` 使用同一结构；
RunSpec 只额外增加不可变身份、解析结果和执行元数据。其他页面分别使用因子家族、因子或
辅助分析草稿文档。导入必须携带页面 revision，冲突时不得覆盖用户的新修改。

### IC 核心测试与附加分析

IC 的一个核心测试单元由产品范围、冻结因子、前瞻收益期、入场 Delay、IC
方法和收益定义共同确定。批量选择会显式展开为核心测试矩阵并按内容地址去重；
产品范围仍是 Job 边界，矩阵单元不是 Job。滚动统计、分期诊断、重采样、
分组组合与持有期半衰期属于消费核心结果的附加分析，权威表示是后端注册的
类型化无环图，界面树只负责展示。图像、表格和保留策略属于输出请求，不是分析
节点。RunSpec 在界面统一显示为“运行配置”，冻结上述执行语义而不冻结界面
排序、聚合和折叠状态。完整决策见 ADR-132、ADR-133。

### 查看因子序列

`factor_evaluation` 是与 IC、回测平行的测试类型，不属于“单因子测试”或“单因子
家族测试”容器。它冻结一个因子引用、一个产品范围及数据源/时间配置，生成可保留的
因子序列 Job 结果。测试台、因子详情入口、智能体辅助文档和 CLI 均使用同一个测试
类型与 RunSpec；结果实现位于 `test-modules/factor-evaluation/results/`。完整决策见
ADR-143。

### 因子 (Factor)

从市场数据（价格、成交量、持仓量）计算出的量化信号。用于预测未来收益或对品种排序。每个因子是 `FactorFamily` 的子类。

因子名前缀对应类别：

| 前缀 | 类别 | 示例 |
|------|------|------|
| **Mm** | 动量/趋势 | `MmRet`、`MmRSI`、`MmMACD`、`MmTrend`、`MmDMI`、`MmMABreak` |
| **Oi** | 持仓量 | `OiChgRat`、`OiChgRatio`、`OiHedgePressure`、`OiNetBuild`、`OiPriceDiv` |
| **Vl** | 波动率 | `VlATR`、`VlCV`、`VlRetStd`、`VlVolRatio`、`VlYZ`、`VlGK` |
| **Vp** | 量价关系 | `VpAmihud`、`VpLiquidity`、`VpTurnoverAccel`、`VpVolPriceCorr` |

### 品种 (Product)

可交易的期货合约（如某个商品期货品种）。定义在 `sources/LocalCNFutures/CNFutures.py`。品种被组织为 `CategoryTree`（板块 × 夜盘时段）。每个品种对每种可用 `DataFreq` 有一个 `DataMeta` 实例（如 `product.MIN1`、`product.DAY1`）。

### 冻结产品范围 (Frozen Product Scope)

一次 Run 使用的产品选择属于 configuration 的共享不可变对象。分析与策略只引用
selection ID；`shared.product_selections` 保存唯一的规范路径，现场产品分类保存完整
定义，已有分类保存稳定元数据与定义哈希。数据源由配置中的稳定 ID 引用；字段映射、
命名方案、能力声明和在线状态属于执行版本的数据源注册表，不复制进 RunSpec。完整决策见 ADR-116。

### 行情数据源声明 (Market Data Source Declaration)

每个 `sources/<Source>` 模块负责声明自己的可见运行位置、支持产品、数据形态、采样方式、频率、市场深度、交付方式、当前可用性和执行适配器。Manager、客户端目录、可用性审计与测试配置只投影这份声明，不按数据源名称猜测能力，也不在界面或服务层为某个供应商硬编码 MIN1、DAY1、L2 或实时/历史语义。历史 K 线 provider 与实时 connector 可以属于同一声明，但只有具备历史执行适配器的成员才能进入历史 IC/回测数据源选择器。

### 因子族 (FactorFamily)

含参数的表达式模板。两种使用方式：

1. **声明式（推荐）** — 子类重写 `factor_expr()` 静态方法，返回 `FactorExpr` 表达式树。参数从 `ParamRef` 节点自动收集。
2. **命令式** — 直接传入 `expr=` 和 `extra_params=`。

核心方法：`get_factor(**params)` → 已解析的 `Factor`；`test(products, time_range)` → IC + 分组回测。

### 已解析因子 (Factor)

参数全部解析后的 `FactorFamily` — 不再含有 `ParamRef`。由 `FactorFamily.get_factor()` 创建。其表达式树被剥离外层 SignalAlign/Neg 后分为：
- `_func_expr`：含取反的纯因子逻辑
- `_source_expr`：不含取反的因子逻辑

计算结果缓存在 `_source_data`（原始高频数据，未对齐）和 `_data`（信号对齐后）。继承 `UniqueObject` — 相同 structural key = 同一实例。

### 表达式树 (FactorExpr)

DSL 核心。三层结构：

1. **叶子节点**（`ColumnRef`、`ConstExpr`、`ParamRef`）— 引用数据列或持有常量
2. **算子节点**（`RollingOp`、`ShiftOp`、`CrossSectionalOp`）— 时序 & 横截面变换
3. **复合表达式** — 算术（`+`、`-`、`*`、`/`）、比较（`>`、`<`）、逻辑（`&`、`|`）

求值流程：DAG → 拓扑排序 → 从 `product.{freq}` 求值每个节点 → 缓存 → 返回 "品种 × 时间" DataFrame。

### 因子执行后端 (Factor Execution Backend)

FactorExpr 是唯一作者接口，执行方式属于编译器后端：

- **Batch backend**：`evaluate(ctx)` 对完整时间区间做向量化研究计算。
- **Incremental backend**：编译为有状态 kernel，随行情或完整横截面逐 bar 更新，
  直接在回测框架生命周期内产生同一种 `FactorSignal`。

逐点、固定 Shift、有限 Rolling 和横截面算子可以拥有两种等价 Implementation；
不支持增量 kernel 的算子必须在编译阶段报错，不得静默调用 batch backend。依赖
Order、Fill、Position 或 Ledger 的路径状态不是市场 FactorExpr，应实现为策略状态、
Risk Module 或 Analyzer。`NextReturns` 是事后评价 label，不得进入因果回测信号图。
完整决策见 ADR-022。

### 信号对齐 (SignalAlign)

原始因子值在数据源频率（如 1 分钟）下计算，然后对齐到信号频率（如日频）。`SignalAlign` 在可配置的 `basepoint`（last / first tick）采样，并可跳过盘间间隔（`end_session_skip`）。

### 策略意图 Policy (Strategy Intent Policy)

StrategyBook 为每个 strategy 解析一个 Strategy Intent Policy。Policy 把已对齐因子和
当前策略状态转换为目标权重或显式订单增量意图；分组、阈值状态和多空组合是平行的
内置 Policy。选择、入场或退出状态不直接表示下单数量，默认订单管线始终用目标仓位
减当前仓位得到交易增量。实时回放与预计算 Adapter 必须执行同一种 Policy 语义。

### 横截面选择计划 (Cross-sectional Selection Plan)

可编译的策略选择计划由 `screen`、`rank`、`split`、`top`、`bottom` 等通用工具组成。
事件 Adapter 用于逐步审计，向量化 Adapter 用于批量加速；两者必须输出相同 membership。
分组 Policy 是标准选择计划加调仓和分配工具的内置组合。`product_mask` 始终在完整分桶后
取交集，不参与 screen 或重新排名。

### 异步产品窗口 (Session-aware Window)

产品组中的品种可能拥有不同日夜盘时段；统一面板因此会包含某些品种原始数据不存在的填充位置。当前没有权威计划时段来源，因此窗口语义以原始观测为准：

- `observed_mask` / `data_present_mask`：原始数据在该产品、该时点确实存在 bar；默认交易位置判断只依赖该 mask。
- 同 `observed_mask` 的产品组沿用普通固定 bars 的 `shift` / `rolling` 快路径。
- 不同 `observed_mask` 的产品组把各列已观测位置压紧后，按各产品换算出的 bars 分组矩阵计算，再将结果散回原索引。

`DataMeta.day_periods` 继续用于将日倍数与盘中余量解析为每个产品的窗口 bars。真实缺失 bar 与非交易位置在缺少计划时段数据契约时均视为未观测位置。完整决策见 ADR-007。

### 派生市场数据产物 (Derived Market Artifact)

主力展期、复权连续、次主连和期限结构由数据源注册为
`(provider, artifact_name, variant)`。核心 coordinator 统一负责跨平台锁、
staging 原子发布、依赖顺序、后台 ensure，以及 SQLite 状态/覆盖元数据；
大型时序事实继续存 Parquet。`roller_info` 表达连续合约选择与复权，
`term_structure:listed_contracts` 表达每日真实合约到期曲线，二者不可混用。
数据源拥有独立 source/artifact storage root。完整决策见 ADR-016。
LocalCNFutures 已完成迁移；运行时只读 provider-scoped canonical path，不再探测
旧全局目录、旧文件名，也不保留一次性迁移脚本。

### 因子数据缓存

去重层：相同表达式树（按 `structural_key`）产生相同结果 — 只算一次，全局复用。
- `Factor._source_data`：表达式求值的原始结果（高频，未对齐）
- `Factor._data`：信号对齐后的结果
- `Factor._intermediate_factor_data`：中间因子缓存，按 structural_key 索引
- `FactorTester.results`：仅持有当前可交互的 `FactorRunResult`；IC scratch 因子及被同 alias 新结果替换的旧因子必须及时释放

### 中间因子 (Intermediate Factor)

因子树中的命名子表达式。`as_intermediate(name)` 标记节点 — 其结果存入 `Factor._intermediate_factor_data`，可在不同品种 / 时间范围间复用。规则：相同 `as_intermediate(name)` 必须映射到相同 `structural_key`；冲突直接报错（不自动加后缀）。

### 参数空间 (Parameter Space)

一个因子族的所有可调参数的取值域。由 `ordered_param_deps`（含 `$F`、`$Rev`、`$P` 等）定义维度，每个维度有默认值和取值范围。参数空间的每一点对应一个具体的因子配置（一组参数值），通过 `get_factor(**params)` 实例化。

### 向量化批量计算 (Vectorized Batch Evaluate)

不将参数配置逐个 `resolve → Factor → evaluate`，而是在表达式层面将 `ParamRef` 替换为 `ConstExpr(np.array([...]))`，使 `evaluate()` 的返回 DataFrame 天然携带参数维度（shape: 参数数 × 品种 × 时间）。算子层（RollingOp、ShiftOp）通过广播机制支持数组 window/periods。详见 ADR-004。

---

## 架构总览

```
start_server.py          ← 入口：Flask + Waitress + 热插拔重载
│
├─ server/               ← HTTP 层（Flask Blueprints）
│  ├─ auth.py            ← 登录/登出/会话
│  ├─ admin.py           ← 用户与机构管理
│  ├─ modules/
│  │  ├─ single_factor_test/  ← IC、分组回测与研究任务执行 API
│  │  ├─ custom_factors/      ← 因子领域内部实现（公开入口见 /api/factor-library）
│  │  ├─ products/cn_futures/ ← 期货领域内部实现（公开入口见 /api/product-library）
│  │  ├─ shared/              ← 共享工具
│  │  └─ templates/           ← 运行配置模板 API
│  └─ services/          ← 业务逻辑（无 Flask 依赖）
│     ├─ factor_registry.py   ← FactorFamily 加载 + 三级缓存
│     ├─ product_tree.py      ← CategoryTree → Fancytree JSON
│     ├─ data_dictionary.py   ← 全量字段清单（SOE 合规审计）
│     ├─ accounts.py          ← 用户账号 CRUD
│     ├─ user_storage.py      ← 用户级文件存储
│     ├─ runtime_state.py     ← 当前用户上下文
│     ├─ api_response.py      ← 统一响应格式
│     ├─ http_auth.py         ← HTTP 认证中间件
│     └─ manager/services/technical_docs.py ← Manager 7998 的公开技术文档编译器
│
├─ tools/                ← 核心引擎（无 Flask，无 HTTP）
│  ├─ factors/
│  │  ├─ FactorExpr.py       ← 表达式树 DSL（1-3 层）
│  │  ├─ FactorFamily.py     ← 含参数因子模板
│  │  ├─ Factors.py (Factor) ← 已解析因子 + 缓存
│  │  ├─ FactorTester.py     ← IC/分组回测驱动
│  │  ├─ Parameters.py       ← 因子专用参数类型
│  │  └─ tests/              ← 单元测试（ic.py、group.py）
│  ├─ data/
│  │  ├─ DataColumn.py       ← 枚举：O/H/L/C/V/TO/OI/…（含 DataColumnMeta）
│  │  ├─ DataFreq.py         ← 频率枚举（1m、5m、1h、1d、…）
│  │  ├─ DataMeta.py         ← Product×Freq DataFrame 封装 + IdleResourceManager 缓存
│  │  └─ DataSource.py       ← 数据源注册表
│  ├─ products/
│  │  ├─ Product.py          ← 品种基类
│  │  ├─ Futures.py          ← 期货扩展
│  │  ├─ AdjustableTermStructure.py ← 期限结构支持
│  │  ├─ product_utils.py    ← 品种辅助工具
│  │  └─ categories/         ← 分类树基础设施
│  ├─ parameters/            ← 通用参数系统
│  └─ base/
│     ├─ UniqueObject.py     ← 按 alias 全局单例
│     ├─ IdleResourceManager.py ← TTL DataFrame 缓存（5 分钟闲置 → 回收）
│     └─ User.py             ← 用户模型
│
├─ factor_family_sources ← 公共 FactorFamily 源码的 SQLite 注册表
├─ sources/              ← 数据源实现
│  └─ LocalCNFutures/    ← 本地中国期货数据管线
├─ static/               ← Manager 共享图标、配置与第三方资源
├─ Settings.py           ← 全局配置（日期、路径、比例等）
└─ docs/
   ├─ adr/               ← 架构决策记录
   └─ agents/            ← Agent 技能配置（issue 跟踪器、triage、领域文档）
```

---

## 因子引擎约定

### 表达式树模式

- **声明式因子**：`factor_expr()` 返回 `FactorExpr`，参数自动收集
- **ParamRef**（`$F`、`$Rev`、`$P`）由 `FactorFamily._resolve_expr_params()` 解析为 `ConstExpr` / `ColumnRef`
- **SignalAlign** 在信号频率上包裹已解析表达式，反转因子再包裹 `Neg()`
- **Factor.__new__** 剥离外层 SignalAlign/Neg 得到 `_func_expr`（含取反）和 `_source_expr`（不含取反）

### 缓存策略

1. `_factor_family_cache` — 公共因子全局单例（线程安全）
2. `_custom_factor_cache` — 自定义因子按用户缓存，键为 `(username, id)`
3. `_chinese_names_cache` — 因子描述一次性加载
4. `Factor._source_data` / `_intermediate_factor_data` — 表达式结果按 `structural_key` 去重
5. `IdleResourceManager` — DataFrame 缓存，5 分钟 TTL，namespace=`datameta`

IC / 分组测试结果的保留边界见 ADR-008：保留最新图表与分组详情所需结果，不保留内部 scratch 或重跑后被替换的大表；页面暂时未显示不等于可删除提交。

单因子页面中的产品提交运行时状态以 `page_uuid` 隔离；提交增删改排与列表同步不得跨页返回或修改 `FactorTester`。完整决策见 ADR-009。

### 命名约定

- 冻结对象使用带版本的 `factor:v2`、`factor-family:v2` 或 `factor-set:v2` 引用；alias 只是展示和解析输入，
  不是持久身份。
- 尚未冻结的运行时因子/因子族使用 `runtime-factor:*` 或 `runtime-factor-family:*` 名称，具体 owner 由显式
  `owner_ref` 或运行时上下文决定。
- 内部运行时上下文仍接受 `$COMMON` 作为公共 owner 的历史别名，但新的冻结引用和公共对象登记统一使用
  `public`；不能从对象名称反推 owner。

---

> 任务跟踪以 [GitHub Issues](https://github.com/maix00/FactorTester/issues) 为准。
