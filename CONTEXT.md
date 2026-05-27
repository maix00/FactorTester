# FactorTester — 上下文

> 领域语言、架构概览、开发约定。供 Agent 和开发者参考。  
> 架构决策记录见 `docs/adr/`。

---

## 这是什么

FactorTester 是一个量化因子研究与回测平台，面向期货及多资产类别。目前已支持中国期货市场，架构预留了多品种、多频率、多数据源的扩展能力。提供：

- **单因子测试** — 单因子的 IC 分析 + 分组收益回测
- **多因子分析** — 相关性矩阵、因子合成、IC 热力图、分层回测
- **自定义因子编辑器** — 可视化 DAG 编辑器 + 代码编辑器
- **价格查看器** — 原始 OHLCV / 价格序列可视化
- **因子引擎** — 40+ 内置因子，表达式树 DSL，自定义因子持久化

开发环境约定见 `docs/development-environment.md`；当前标准环境为 Conda `GTHT`。

---

## 领域概念

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

### 信号对齐 (SignalAlign)

原始因子值在数据源频率（如 1 分钟）下计算，然后对齐到信号频率（如日频）。`SignalAlign` 在可配置的 `basepoint`（last / first tick）采样，并可跳过盘间间隔（`end_session_skip`）。

### 异步产品窗口 (Session-aware Window)

产品组中的品种可能拥有不同日夜盘时段；统一面板因此会包含某些品种原始数据不存在的填充位置。当前没有权威计划时段来源，因此窗口语义以原始观测为准：

- `observed_mask` / `data_present_mask`：原始数据在该产品、该时点确实存在 bar；默认交易位置判断只依赖该 mask。
- 同 `observed_mask` 的产品组沿用普通固定 bars 的 `shift` / `rolling` 快路径。
- 不同 `observed_mask` 的产品组把各列已观测位置压紧后，按各产品换算出的 bars 分组矩阵计算，再将结果散回原索引。

`DataMeta.day_periods` 继续用于将日倍数与盘中余量解析为每个产品的窗口 bars。真实缺失 bar 与非交易位置在缺少计划时段数据契约时均视为未观测位置。完整决策见 ADR-007。

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
│  ├─ core.py            ← 页面路由（/ , /price_viewer, /docs/*）
│  ├─ auth.py            ← 登录/登出/会话
│  ├─ admin.py           ← 用户与机构管理
│  ├─ modules/
│  │  ├─ single_factor_test/  ← IC + 分组回测 API 与页面
│  │  ├─ custom_factors/      ← 编辑器、CRUD、目录、参数配置
│  │  ├─ products/cn_futures/ ← 品种树 + 价格数据 API
│  │  ├─ shared/              ← 共享工具
│  │  └─ templates/           ← 模板渲染辅助
│  └─ services/          ← 业务逻辑（无 Flask 依赖）
│     ├─ factor_registry.py   ← FactorFamily 加载 + 三级缓存
│     ├─ product_tree.py      ← CategoryTree → Fancytree JSON
│     ├─ data_dictionary.py   ← 全量字段清单（SOE 合规审计）
│     ├─ accounts.py          ← 用户账号 CRUD
│     ├─ user_storage.py      ← 用户级文件存储
│     ├─ runtime_state.py     ← 当前用户上下文
│     ├─ api_response.py      ← 统一响应格式
│     ├─ http_auth.py         ← HTTP 认证中间件
│     └─ tool_docs.py         ← 源码文档生成器
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
├─ Factors/              ← 40+ 内置 FactorFamily 子类（每个文件一个因子）
├─ sources/              ← 数据源实现
│  └─ LocalCNFutures/    ← 本地中国期货数据管线
├─ templates/            ← Jinja2 HTML 模板
├─ static/               ← CSS/JS 前端资源
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

### 命名约定

- `UniqueObject.name`：`{user_prefix}:{alias}:{uuid}` — 全局唯一
- `UniqueObject.alias`：纯类名（如 `MmRet`）— 用于查找
- `user_prefix`：公共因子用 `$COMMON`，自定义因子用 `用户名@序号`

---

> 任务跟踪以 [GitHub Issues](https://github.com/maix00/FactorTester/issues) 为准。
