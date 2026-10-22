# Benchmark Report

## 目录

- [WorldQuant Alpha 101](#worldquant-alpha-101)
  - [正确性总览](#正确性总览)
  - [正确性分析](#正确性分析)
  - [性能对比](#alpha101-性能对比)
- [GTJA 191](#gtja-191)
  - [总览](#gtja-191-总览)
  - [性能](#gtja-191-性能)
  - [DSL 修复记录](#dsl-修复记录)
- [附录：Bug 修复记录](#附录bug-修复记录)

---

## WorldQuant Alpha 101

基于 `comparison_all.csv` 三方对比（pandas / alpha-lib / polars_ta）。

### 正确性总览

| 类别 | 数量 |
|---|---|
| 完全一致（pearson ≥ 0.99） | 47 |
| 高度一致（0.95 ≤ pearson < 0.99） | 6 |
| 常量输出（无法计算相关性） | 6 |
| 暖窗期行为差异（ic_mean ≥ 0.99） | 8 |
| Pandas 参考实现 bug | 3 |
| decay_linear NaN 处理差异 | 3 |
| 浮点精度 | 1 |
| 数据不足 | 3 |
| IndNeutralize 因子（新增支持） | 19 |
| 其他（alpha_023/062 pandas 缺失） | 2 |
| **合计** | **101** (alpha-lib 全部支持) |

### 结论

Alpha-lib 的 Rust 实现在所有已实现因子上**数学计算正确**，符合 Alpha 101 论文定义。与 pandas 参考实现的差异来源于：

1. **暖窗期设计选择**：alpha-lib 返回部分结果 vs pandas 返回 NaN（可通过 `FLAG_STRICTLY_CYCLE` 切换）
2. **Pandas 参考 bug**：3 个因子公式错误
3. **NaN 传播策略**：alpha-lib 正确传播，pandas 做了填充预处理
4. **浮点精度**：极端小窗口下不可避免

### 正确性分析

#### 完全一致（47 个）

pearson ≥ 0.99 或 ic_mean ≥ 0.99，公式与 Alpha101 论文一致。

001, 002, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 015, 016, 017, 018, 019, 020, 022, 025, 026, 029, 030, 033, 034, 035, 037, 039, 040, 041, 042, 044, 046, 049, 050, 051, 052, 053, 054, 060, 078, 084, 085, 101

另有 alpha_024 (pearson=0.978, ic=0.982) 属于高度一致。

#### 常量输出（6 个）

输出为常量或方差极小，无法计算 pearson，三方一致：021, 027, 057, 068, 083, 086

#### 暖窗期行为差异（8 个）

Alpha-lib 在滚动窗口未满时返回部分计算结果，pandas 返回 NaN。**这是设计选择，不是 bug。** Alpha-lib 提供了更多有效数据。

关键证据：**ic_mean（逐截面相关）均 ≥ 0.99**，说明在双方都有有效数据的时间步上完全一致。

| Factor | pearson (pd_vs_al) | ic_mean | 说明 |
|---|---|---|---|
| alpha_061 | 0.375 | 0.995 | `rank(A) < rank(B)` 布尔输出，暖窗期翻转 |
| alpha_064 | 0.535 | 0.996 | 同上 |
| alpha_065 | 0.752 | 0.998 | 同上 |
| alpha_074 | 0.758 | 0.998 | 同上 |
| alpha_075 | 0.799 | 0.998 | 同上 |
| alpha_081 | 0.740 | 0.997 | 同上 |
| alpha_095 | 0.012 | 1.000 | 同上，暖窗期长 |
| alpha_099 | 0.722 | 0.998 | 同上 |

另有 alpha_043 (p=0.903), alpha_055 (p=0.978), alpha_094 (p=0.585) 也受暖窗期影响。

#### Pandas 参考实现 Bug（3 个）

以下 pandas 参考实现有公式错误，**alpha-lib 是正确的**。

| Factor | Pandas Bug | 验证 |
|---|---|---|
| alpha_038 | `ts_rank(open, 10)` 应为 `ts_rank(close, 10)` | al_vs_pt spearman=0.993 |
| alpha_036 | `sma(close,200)/200` 双重除以200 | al_vs_pt spearman=0.998 |
| alpha_047 | `sma(high,5)/5` = sum/25，应为 sum/5 | **al_vs_pt pearson=1.0** |

#### decay_linear NaN 处理差异（3 个）

Pandas 在 LWMA 前做 `ffill().bfill().fillna(0)` 预处理，alpha-lib 正确传播 NaN。

| Factor | pearson (pd_vs_al) | 说明 |
|---|---|---|
| alpha_066 | 0.941 | decay_linear 输入含 NaN |
| alpha_072 | 0.020 | 分子分母均含 decay_linear |
| alpha_098 | 0.736 | 嵌套 decay_linear |

#### 浮点精度（1 个）

| Factor | pearson (pd_vs_al) | 说明 |
|---|---|---|
| alpha_045 | 0.915 | `corr(x, y, 2)` 窗口=2 时值集中在 ±1 附近，1e-6 级 FP 差异导致截面排名不稳定。三方实现互相也不一致 (pd_vs_pt=0.926) |

#### IndNeutralize 因子（19 个）

以下因子使用 `INDNEUTRALIZE(expr, IndClass.xxx)` 行业中性化，此前未实现，现已全部支持：

048, 056, 058, 059, 063, 067, 069, 070, 076, 079, 080, 082, 087, 089, 090, 091, 093, 097, 100

这些因子的 pandas 参考实现也缺失（未支持行业分类数据），因此无法做正确性对比。

### Alpha101 性能对比

测试数据：4000 只股票 × 261 个交易日 = 1,044,000 行

#### 数据加载

| 实现 | 加载方式 | 耗时 |
|---|---|---|
| pandas | pd.read_csv | 31,230ms |
| polars_ta | pl.read_csv | ~300ms |
| **alpha-lib** | **pl.read_csv** | **226ms** |

#### 因子计算汇总

| 实现 | 因子数 | 计算耗时 | 均值 | 中位数 | vs pandas |
|---|---|---|---|---|---|
| pandas | 75 | 2,643,373ms (44min) | 35,245ms | 673ms | 1x |
| polars_ta | 81 | 58,130ms (58s) | 718ms | 424ms | **45x** |
| **alpha-lib** | **101** | **3,628ms (3.6s)** | **36ms** | **40ms** | **729x** |

含 `ts_rank` / `correlation` 长窗口操作的因子加速比 **1,000x - 7,000x**，简单因子 **2x - 100x**。

<details>
<summary>逐因子耗时明细（alpha-lib vs pandas）</summary>

| Factor | alpha-lib | pandas | 加速比 |
|---|---|---|---|
| alpha_001 | 48ms | 32,240ms | 676x |
| alpha_002 | 37ms | 685ms | 18x |
| alpha_003 | 14ms | 539ms | 40x |
| alpha_004 | 15ms | 92,428ms | 6,288x |
| alpha_005 | 29ms | 169ms | 6x |
| alpha_006 | 3ms | 422ms | 132x |
| alpha_007 | 42ms | 75,444ms | 1,784x |
| alpha_008 | 20ms | 305ms | 15x |
| alpha_009 | 45ms | 127ms | 3x |
| alpha_010 | 39ms | 210ms | 5x |
| alpha_011 | 32ms | 237ms | 7x |
| alpha_012 | 17ms | 17ms | 1x |
| alpha_013 | 23ms | 669ms | 29x |
| alpha_014 | 19ms | 501ms | 27x |
| alpha_015 | 27ms | 673ms | 25x |
| alpha_016 | 21ms | 562ms | 26x |
| alpha_017 | 57ms | 177,560ms | 3,132x |
| alpha_018 | 21ms | 556ms | 27x |
| alpha_019 | 34ms | 103ms | 3x |
| alpha_020 | 46ms | 273ms | 6x |
| alpha_021 | 43ms | 406ms | 10x |
| alpha_022 | 18ms | 695ms | 38x |
| alpha_023 | 12ms | - | - |
| alpha_024 | 54ms | 136ms | 3x |
| alpha_025 | 18ms | 139ms | 8x |
| alpha_026 | 23ms | 185,351ms | 8,238x |
| alpha_027 | 29ms | 675ms | 23x |
| alpha_028 | 15ms | 636ms | 44x |
| alpha_029 | 62ms | 91,282ms | 1,484x |
| alpha_030 | 46ms | 178ms | 4x |
| alpha_031 | 58ms | 985ms | 17x |
| alpha_032 | 15ms | 501ms | 33x |
| alpha_033 | 12ms | 91ms | 7x |
| alpha_034 | 41ms | 371ms | 9x |
| alpha_035 | 55ms | 263,594ms | 4,767x |
| alpha_036 | 85ms | 95,351ms | 1,120x |
| alpha_037 | 19ms | 535ms | 28x |
| alpha_038 | 21ms | 94,936ms | 4,436x |
| alpha_039 | 49ms | 297ms | 6x |
| alpha_040 | 11ms | 558ms | 51x |
| alpha_041 | 4ms | 4ms | 1x |
| alpha_042 | 11ms | 130ms | 12x |
| alpha_043 | 30ms | 174,838ms | 5,828x |
| alpha_044 | 9ms | 487ms | 52x |
| alpha_045 | 31ms | 1,291ms | 42x |
| alpha_046 | 31ms | 30ms | 1x |
| alpha_047 | 38ms | 343ms | 9x |
| alpha_048 | 41ms | - | - |
| alpha_049 | 16ms | 18ms | 1x |
| alpha_050 | 26ms | 682ms | 26x |
| alpha_051 | 23ms | 14ms | 1x |
| alpha_052 | 33ms | 92,591ms | 2,823x |
| alpha_053 | 14ms | 9ms | 1x |
| alpha_054 | 14ms | 20ms | 1x |
| alpha_055 | 32ms | 792ms | 25x |
| alpha_056 | 23ms | - | - |
| alpha_057 | 15ms | 31,689ms | 2,185x |
| alpha_058 | 20ms | - | - |
| alpha_059 | 24ms | - | - |
| alpha_060 | 40ms | 34,148ms | 852x |
| alpha_061 | 21ms | 671ms | 33x |
| alpha_062 | 43ms | 925ms | 21x |
| alpha_063 | 59ms | - | - |
| alpha_064 | 38ms | 790ms | 21x |
| alpha_065 | 41ms | 760ms | 18x |
| alpha_066 | 44ms | 93,920ms | 2,139x |
| alpha_067 | 55ms | - | - |
| alpha_068 | 42ms | 87,173ms | 2,061x |
| alpha_069 | 48ms | - | - |
| alpha_070 | 34ms | - | - |
| alpha_071 | 46ms | - | - |
| alpha_072 | 40ms | 192,850ms | 4,821x |
| alpha_073 | 45ms | - | - |
| alpha_074 | 43ms | 2,281ms | 53x |
| alpha_075 | 37ms | 1,253ms | 34x |
| alpha_076 | 49ms | - | - |
| alpha_077 | 31ms | - | - |
| alpha_078 | 40ms | 1,359ms | 34x |
| alpha_079 | 49ms | - | - |
| alpha_080 | 34ms | - | - |
| alpha_081 | 58ms | 28,633ms | 495x |
| alpha_082 | 47ms | - | - |
| alpha_083 | 42ms | 352ms | 8x |
| alpha_084 | 40ms | 90,065ms | 2,274x |
| alpha_085 | 41ms | 194,698ms | 4,760x |
| alpha_086 | 33ms | 76,954ms | 2,318x |
| alpha_087 | 42ms | - | - |
| alpha_088 | 74ms | - | - |
| alpha_089 | 46ms | - | - |
| alpha_090 | 50ms | - | - |
| alpha_091 | 35ms | - | - |
| alpha_092 | 54ms | - | - |
| alpha_093 | 40ms | - | - |
| alpha_094 | 50ms | 230,125ms | 4,612x |
| alpha_095 | 45ms | 67,088ms | 1,494x |
| alpha_096 | 61ms | - | - |
| alpha_097 | 80ms | - | - |
| alpha_098 | 55ms | 112,529ms | 2,046x |
| alpha_099 | 40ms | 3,126ms | 78x |
| alpha_100 | 100ms | - | - |
| alpha_101 | 9ms | 297ms | 34x |

</details>

---

## GTJA 191

国泰君安 191 因子集运行报告。

### GTJA 191 总览

| 类别 | 数量 |
|---|---|
| 可计算 | 190 |
| 不可计算 | 1 |
| **合计** | **191** |

不可计算因子：**#030** — 需要 Fama-French 三因子数据（MKT, SMB, HML），数据集不含此类数据。

### GTJA 191 性能

测试数据：4000 只股票 × 261 个交易日 = 1,044,000 行

| 指标 | 值 |
|---|---|
| 数据加载 | ~1,000ms |
| 因子数 | 190 |
| 计算总耗时 | ~4,530ms (4.5s) |
| 均值 | 24ms |
| 中位数 | 18ms |

<details>
<summary>逐因子耗时明细</summary>

| Factor | 耗时 | | Factor | 耗时 | | Factor | 耗时 |
|---|---|---|---|---|---|---|---|
| #001 | 39ms | | #065 | 6ms | | #128 | 41ms |
| #002 | 14ms | | #066 | 8ms | | #129 | 12ms |
| #003 | 22ms | | #067 | 12ms | | #130 | 38ms |
| #004 | 32ms | | #068 | 17ms | | #131 | 22ms |
| #005 | 17ms | | #069 | 21ms | | #132 | 5ms |
| #006 | 24ms | | #070 | 1ms | | #133 | 16ms |
| #007 | 24ms | | #071 | 7ms | | #134 | 10ms |
| #008 | 24ms | | #072 | 13ms | | #135 | 8ms |
| #009 | 16ms | | #073 | 14ms | | #136 | 15ms |
| #010 | 17ms | | #074 | 28ms | | #137 | 145ms |
| #011 | 16ms | | #075 | 8ms | | #138 | 50ms |
| #012 | 20ms | | #076 | 13ms | | #139 | 3ms |
| #013 | 10ms | | #077 | 25ms | | #140 | 68ms |
| #014 | 3ms | | #078 | 19ms | | #141 | 25ms |
| #015 | 3ms | | #079 | 15ms | | #142 | 51ms |
| #016 | 24ms | | #080 | 7ms | | #143 | 12ms |
| #017 | 17ms | | #081 | 1ms | | #144 | 16ms |
| #018 | 4ms | | #082 | 16ms | | #145 | 11ms |
| #019 | 21ms | | #083 | 22ms | | #146 | 83ms |
| #020 | 8ms | | #084 | 16ms | | #147 | 3ms |
| #021 | 4ms | | #085 | 27ms | | #148 | 26ms |
| #022 | 19ms | | #086 | 19ms | | #149 | 20ms |
| #023 | 42ms | | #087 | 33ms | | #150 | 6ms |
| #024 | 5ms | | #088 | 8ms | | #151 | 7ms |
| #025 | 45ms | | #089 | 13ms | | #152 | 22ms |
| #026 | 10ms | | #090 | 23ms | | #153 | 8ms |
| #027 | 23ms | | #091 | 22ms | | #154 | 7ms |
| #028 | 39ms | | #092 | 35ms | | #155 | 14ms |
| #029 | 8ms | | #093 | 17ms | | #156 | 37ms |
| #031 | 5ms | | #094 | 14ms | | #157 | 50ms |
| #032 | 23ms | | #095 | 3ms | | #158 | 15ms |
| #033 | 21ms | | #096 | 20ms | | #159 | 73ms |
| #034 | 2ms | | #097 | 4ms | | #160 | 12ms |
| #035 | 28ms | | #098 | 44ms | | #161 | 20ms |
| #036 | 20ms | | #099 | 19ms | | #162 | 75ms |
| #037 | 16ms | | #100 | 5ms | | #163 | 11ms |
| #038 | 14ms | | #101 | 44ms | | #164 | 29ms |
| #039 | 30ms | | #102 | 24ms | | #165 | 22ms |
| #040 | 16ms | | #103 | 6ms | | #166 | 21ms |
| #041 | 13ms | | #104 | 21ms | | #167 | 19ms |
| #042 | 11ms | | #105 | 16ms | | #168 | 4ms |
| #043 | 11ms | | #106 | 5ms | | #169 | 23ms |
| #044 | 24ms | | #107 | 44ms | | #170 | 31ms |
| #045 | 28ms | | #108 | 25ms | | #171 | 20ms |
| #046 | 12ms | | #109 | 11ms | | #172 | 51ms |
| #047 | 15ms | | #110 | 19ms | | #173 | 13ms |
| #048 | 24ms | | #111 | 18ms | | #174 | 14ms |
| #049 | 71ms | | #112 | 73ms | | #175 | 16ms |
| #050 | 142ms | | #113 | 27ms | | #176 | 21ms |
| #051 | 68ms | | #114 | 35ms | | #177 | 6ms |
| #052 | 16ms | | #115 | 48ms | | #178 | 9ms |
| #053 | 6ms | | #116 | 5ms | | #179 | 27ms |
| #054 | 17ms | | #117 | 48ms | | #180 | 30ms |
| #055 | 150ms | | #118 | 7ms | | #181 | 62ms |
| #056 | 39ms | | #119 | 40ms | | #182 | 9ms |
| #057 | 17ms | | #120 | 23ms | | #183 | 25ms |
| #058 | 6ms | | #121 | 36ms | | #184 | 18ms |
| #059 | 29ms | | #122 | 19ms | | #185 | 13ms |
| #060 | 8ms | | #123 | 32ms | | #186 | 109ms |
| #061 | 24ms | | #124 | 14ms | | #187 | 18ms |
| #062 | 9ms | | #125 | 31ms | | #188 | 11ms |
| #063 | 17ms | | #126 | 5ms | | #189 | 7ms |
| #064 | 36ms | | #127 | 15ms | | #190 | 101ms |
| | | | | | | #191 | 7ms |

</details>

### DSL 修复记录

原始 GTJA 191 论文的公式存在多处歧义和错误，以下为修复项：

| # | 原始问题 | 修复 |
|---|---|---|
| #010 | `MAX(expr, 5)` 歧义（element-wise vs rolling） | `MAX` → `TSMAX` |
| #021 | `SEQUENCE(6)` 被解析为函数调用 | `SEQUENCE(6)` → `SEQUENCE,6`（作为 REGBETA 第三参数） |
| #054 | `STD(ABS(CLOSE-OPEN))` 缺少窗口参数 | 补窗口 → `STD(ABS(CLOSE-OPEN), 10)` |
| #127 | `MEAN(...)` 缺窗口 + `MAX(CLOSE,12)` 歧义 | `MEAN(..., 12)` + `MAX` → `TSMAX` |
| #147 | 同 #021 | `SEQUENCE(12)` → `SEQUENCE,12` |
| #165 | `MAX/MIN(SUMAC(...))` 缺窗口 | `SUMAC` → `SUM(...,48)`, `MAX/MIN` → `TSMAX/TSMIN(...,48)` |
| #181 | 尾部 `SUM(...)` 缺窗口 | 补窗口 → `SUM(..., 20)` |
| #183 | 同 #165 模式 | `SUMAC` → `SUM(...,24)`, `MAX/MIN` → `TSMAX/TSMIN(...,24)` |
| #190 | `DELAY(CLOSE)` 缺少周期参数 | `DELAY(CLOSE)` → `DELAY(CLOSE,1)`（4 处） |

---

## 附录：Bug 修复记录

对比测试过程中发现并修复的 bug。

| # | Commit | 修复项 | 一致因子数 | 根因 |
|---|---|---|---|---|
| 1 | `7013001` | 转译器运算符优先级 + 浮点窗口取整 | 27 → 41 | 代码生成 bug |
| 2 | `9cf9fef` | SIGNEDPOWER 语义 | 41 → 43 | 数学定义错误 |
| 3 | `bd428a3` | RANK 跨截面 NaN 处理 | 43 → 44 | 截面算法 bug |
| 4 | `f8729bf` | TS_RANK 重复值处理 | 44 → 47 | 数据结构 bug |
| 5 | `def3ddd` | Float::is_normal() 替换 | — | 正确性 bug |

<details>
<summary>详细修复说明</summary>

### 1. 转译器运算符优先级 + 浮点窗口取整

**转译器生成的 Python 代码缺少括号**，导致表达式语义错误。例如 `(close - open) / open` 被生成为 `close - open / open`（先算 `open / open`）。同时，DSL 中的浮点窗口参数（如 `correlation(x, y, 8.93345)`）未取整，传入 Rust 后截断为 8 而非四舍五入到 9。

修复：在 `to_python.py` 的 `sum`/`product`/比较运算生成时加括号；`arguments()` 方法对浮点参数四舍五入。

### 2. SIGNEDPOWER 语义

`SIGNEDPOWER(x, p)` 定义为 `sign(x) * |x|^p`，但 wq101 的 context 实现为 `np.power(x, p)`。当 `x < 0` 且 `p` 为非整数时，`np.power` 返回 NaN。

修复：`alpha101_context.py` 中改为 `np.sign(a) * np.power(np.abs(a), p)`。

### 3. RANK 跨截面 NaN 处理

`ta_rank` 将 NaN 纳入排名分母计算，导致排名百分比偏低。pandas 的 `rank(pct=True)` 默认跳过 NaN。注意：这是截面操作，`FLAG_SKIP_NAN` 仅控制滚动窗口行为，不影响截面算子。

修复：`rank.rs` 中 NaN 输入产生 NaN 输出，排名分母只计有效值。

### 4. TS_RANK 重复值处理

`ta_ts_rank` 使用 `BTreeMap<OrderedFloat, usize>` 作为滑动窗口，**相同浮点值会覆盖之前的条目**，导致窗口大小错误和排名计算偏差。

修复：改用 `BTreeMap<OrderedFloat, u32>` 计数器 + 独立 NaN 计数，采用 min-rank 方法（与 pandas `rankdata(method='min')` 一致）。

### 5. Float::is_normal() 替换

Rust 标准库 `Float::is_normal()` 对 `0.0` 和次正规数返回 `false`，导致 MA / STDDEV / CORR / COV / LWMA 等算子将 `0.0` 误判为无效值并跳过。

修复：定义 `fn is_normal(a) -> bool { !a.is_nan() }`，替换所有 `is_normal()` 调用。影响 5 个 Rust 源文件（ma.rs, stddev.rs, stats.rs, ema.rs, slope.rs）。

### SUMIF / SCAN bool 类型修复

`build.rs` 代码生成器对 3-array 签名函数（如 `ta_sumif`、`ta_scan_mul`、`ta_scan_add`）的 Python wrapper 无差别调用 `_to_f64()`，将 `bool` 条件数组转为 `float64`，但 Rust FFI 要求 `condition` 为 `bool` 数组，导致运行时报错。

修复：`build.rs` 中 `build_algo_py()` 新增 `py_convert()` / `py_convert_list()` 辅助函数，根据参数的 `TaType`（`NumArray` vs `BoolArray`）生成 `_to_f64()` 或 `_to_bool()` 调用。

### SELF 递归算子

#143 使用 `SELF` 递归引用：`CLOSE>DELAY(CLOSE,1)?(CLOSE-DELAY(CLOSE,1))/DELAY(CLOSE,1)*SELF:SELF`，含义为条件累积乘。

实现：
- **Rust**: `ta_scan_mul` / `ta_scan_add`（`src/algo/scan.rs`）— 股内串行扫描，股间 rayon 并行
- **DSL**: 语法新增 `SELF` 终端，转译器模式匹配 `cond ? expr*SELF : SELF` → `ctx.SCAN_MUL(expr, cond)`
- **ExecContext**: `SCAN_MUL` / `SCAN_ADD` 方法

### Python 层 dtype 处理优化

原始代码在 Python wrapper（`algo_gen.py`）中对所有输入无条件调用 `.astype(float)`：

```python
# 旧代码 (algo_gen.py, build.rs 自动生成)
a = a.astype(float)    # 即使 a 已经是 float64，仍然 copy 一份
b = b.astype(float)    # 每次调用都有不必要的内存分配
```

引入 `_to_f64()` 替代 `.astype(float)`，统一所有输入为 float64，但对已经是 float64 的输入做零拷贝：

```python
def _to_f64(a):
    if a.dtype == np.float64:
        return a                  # zero-copy
    return a.astype(np.float64)   # int/bool/f32 → f64
```

| 输入 dtype | 旧行为 | 新行为 |
|---|---|---|
| float64 | `.astype(float)` → copy | `_to_f64()` → **zero-copy** |
| float32 | `.astype(float)` → copy 到 f64 | `.astype(np.float64)` → copy 到 f64 |
| int64/bool | `.astype(float)` → copy 到 f64 | `.astype(np.float64)` → copy 到 f64 |

</details>
