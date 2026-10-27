# ADR-184：数据源自行维护适配器的类型化 Bundle

状态：部分实施；P0 现状对齐与消费者契约审计已完成，P1 尚未开始。
用户确定目标边界；运行时代码仍存在具体来源依赖和未冻结输入。
关联：[#447](https://github.com/maix00/FactorTester/issues/447)、[#445](https://github.com/maix00/FactorTester/issues/445)。
P0 审计基线：[source-bundle-p0-2026-10-27.md](../audits/source-bundle-p0-2026-10-27.md)
（checkout `945ddc5b7`）。该审计不表示验收完成。

## 依赖边界

产品与数据源属于平台中立领域，不是 Nautilus Instrument 或 DataClient 的子类。
Bundle 是可独立安装和发布的插件包，每个 Bundle 管理自己的接入代码仓库，成员不各建一套仓库：只依赖可单独分发的最小公共数据契约，不依赖 Manager、
平台产品类、全局 DataHub 或其他数据源。其 Nautilus 集成放在同一插件的可选适配模块；
只有执行侧显式请求时才导入 Nautilus。平台目录不导入 Nautilus，不访问数据文件。

```text
数据源包 ──声明──> 中立 Bundle / Member / Product / 字段契约
   └──可选 Nautilus 适配模块──> Nautilus 数据加载与转换接口
平台目录、UI、CLI ──读取──> 中立注册契约及可选集成能力元数据
执行层 ──按冻结引用解析并调用──> 所选数据源的适配模块
```

只收敛现有注册表，不增设另一套并行 registry。共同的转换算法可以复用，但具体格式、
产品标识解析、字段映射、交易日与文件位置属于数据源。平台不得按来源名称、路径或
中国期货专用函数选择加载分支。

## Bundle 与成员

Bundle 是一个供应包身份，内部显式列出不同类型的成员，而不是按 `Local*` 名字前缀归组。

| 成员类型 | 内容 | 时钟 |
|---|---|---|
| market_data | Bar、Tick、L2/L3 等行情 | ts_event/ts_init、明确区间端点 |
| instrument_definitions | 静态产品/Instrument 定义与标识关系 | 适用期、来源版本 |
| historical_rules | 费率、保证金、限额等历史规则 | 生效时间、知悉时间、交易日归属 |
| settlement_data | 官方结算价或结算所需独立观测 | 交易日、结算/发布时刻 |

只登记真实提供的类型，不补造空成员。成员拥有独立稳定引用、schema/mapping 版本和可用性；
Bundle 内行情与规则成员通过明确关系绑定，不在每个行情成员上重复挂同一个历史提供器。
规则成员的 frequency 可以不适用，不能冒充 MIN1/DAY1；行情筛选只列行情成员。

同包不意味着同版本或相同数据生命周期。RunSpec 冻结 Bundle、所选成员、映射版本与关系，
不展开复制整个目录，也不把同一历史表按每个行情频率再装载一次。

## 平台来源与用户客户端来源

来源提供方、数据所在地和可见范围是三个独立维度，不把 provider_kind、文件路径或
“Local”名称当作所有权/执行权限。

| 维度 | 契约含义 |
|---|---|
| 提供方 | platform：平台发布/管理的来源定义；user：用户自行添加的来源定义 |
| 执行所在地 | server 或 client；client 使用明确设备身份，不是任意 localhost URL |
| 访问范围 | 定义所有者、允许查看者、数据读取权限和授权 revision；默认不共享用户客户端源 |

例如，平台提供的适配器也可能读取用户电脑上的数据：适配器代码来自平台，不代表数据归平台
或可被服务器读取。用户自定义来源未来也可能显式部署到服务器，不能因此变成平台公共来源。

服务端声明注册表与客户端来源 manifest 保持各自的权威边界；平台只读取同一通用契约的投影，
不把客户端插件导入 Manager，不运行上传源码，不扫描用户目录。Bundle/member 引用带来源
authority 与 owner/device 作用域；同名不同来源不合并、不互相回退。

客户端源的路径、凭据、数据字节和本地缓存默认留在客户端。前端明确展示提供方、执行设备、
访问性及当前在线状态；“设备离线/不可达”不同于“数据为空/没有数据”。客户端元数据的跨端
同步沿用已有权限/对象同步基础设施，不能顺带同步凭据、绝对路径或数据文件。

RunSpec 固定来源身份、成员版本与执行位置；本机任务调用本机源适配器。服务器任务必须有
服务器可读成员，或用户明确授权后通过现有受控数据面物化输入，保留内容身份、接收权限与
来源记录。缺少条件时给出具体原因，不能把服务器同名源当作替代，也不自动把电脑数据上传。
本决策不新增常驻代理、端口、远程访问或源码执行能力。

验收需覆盖：同名平台/用户源、不同账户/设备、访客与下级用户权限、客户端离线、授权撤回、
乱序元数据、原设备缺失、显式传输前后冻结引用以及服务器拒绝未授权客户端数据。

## 属性逐项对应

“逐项对应”是显式、可审计且不丢信息的语义对应，不要求平台依赖 Nautilus 的类定义。
属性名、类型和单位相同的直接对应；转换只在数据源适配层实现一份。

映射条目至少声明：来源字段、中立属性、Nautilus 目标字段/模型/事件、类型、精度、单位、
时间语义、必需性、转换版本，以及不可表示原因。覆盖全部公开属性并校验未消费字段；
不得用笼统 extra 字典掩盖未映射项。额外来源属性可命名空间保留，但必须列明执行适用性。

| 语义 | 对应位置 |
|---|---|
| 标识、币种、乘数、价格/数量步长等静态定义 | Nautilus Instrument 字段 |
| 不同时间的保证金/可更新属性 | Instrument 更新及必要的账务重估路径 |
| Maker/Taker、平今/平昨、按手/按金额费用 | FeeModel/历史规则，不强塞单个 Instrument 常量 |
| 结算价、每日结束、规则生效 | 对应数据/事件及已有结算机制 |
| 起始余额、杠杆、撮合策略 | Venue/Account/运行配置，不属于产品来源属性 |

多空保证金、平今/平昨费率等不能压缩成一个数。原生字段不足时明确使用已实现的扩展模型，
或报告未支持；禁止静默平均、选择较大值、用最新值覆盖历史，或把缺失值补成零。

## 加载、内存与性能

目录只读取声明；解析成员不加载数据。请求携带冻结产品引用、时间范围、所需列及批大小。
源适配器通过 Nautilus 支持的目录/数据客户端接口供数；不在平台中另建撮合或缓存权威。

数据按列投影、有界批次与背压读取。缓存所有者和有效期显式，账户/策略共享同一只读输入，
规则按生效事件推进，不逐 Bar 重扫历史。避免 Python DataFrame 与 Rust 全量数组同时驻留。
零拷贝只在接口确实支持时声明；跨格式转换的副本与峰值 RSS 必须实测，不以“Rust”推定性能。

## 当前偏离与切换顺序

P0 审计在 `945ddc5b7` 上确认以下偏离，按影响排序：

1. **多合约返回被压缩**：`sources/LocalCNFutures/nautilus_catalog.py` 会 stage 每个请求
   合约，但返回 `catalogs.setdefault(product_key, ...)`，同一品种只保留第一个。
   当前执行消费者只接受 `product -> ReplayInput`，不能据此声称完整换月/全合约回放。
   切到多合约前必须先与执行消费者约定显式多 catalog 引用。
2. **历史规则有损**：`build_contract_spec` 仍取 `max(long_margin, short_margin)`，
   initial/maintenance 相同，缺失补零。`FuturesContractSpec` 只有单一 margin 字段，
   没有多空/保证时间语义；必须接入无损规则路径或明确 fail-closed，不得保留 max 当完成。
3. **DAY1 走分钟 loader**：`LocalCNFuturesContractDAY1` 与 MIN1 共用
   `stage_contract_minute_catalog`，后者固定读取 `iter_minute_bars` 并创建
   `1-MINUTE-LAST-EXTERNAL` BarType；DAY1 的 `TRADING_DAY`、结算列、交易日标签语义
   尚未执行验证。
4. **中央代码仍持有具体来源选择**：`nautilus_catalog.py` 仍调用
   `price_services`、`catalog_staging`、`source_registry` 的产品/路径/生命周期函数，
   不是可脱离平台独立安装的 Bundle。
5. **规则绑定仍为特定 provider**：`trading_fields.py` 仍限定
   `FieldHistory:market_rules:exchange` 与具体 FieldHistoryProvider；行情成员声明了
   `related_members`，但执行侧尚未按关系只加载一次。
6. **产品绑定/分类未迁移**：`Local` 的 `product_bindings` 为空；既有产品与用户分类
   记录尚未映射到 `source_product_ref`。
7. **目录 API 未切纯元数据**：`product_source_descriptors()`、联邦能力快照和旧目录
   路径仍会激活接入代码/检查可用性；客户端 `source.json` 仍是旧契约。
8. **RunSpec 未冻结输入身份**：尚未固定 Bundle、成员、接入包、映射版本和关系；
   清单版本不等于行情内容 revision。

先建立带验收的协议与类型化注册，再将现有真实来源接入；每个切换批次同时替换消费者并删除
其旧分支，不长期双写两套接口。静态字段、历史规则和行情保持可追溯，禁止迁移数据文件或
重写数据库来达到表面一致。源脚本与数据资产不能因“解耦”被批量删除。

验收包括：独立来源包和非中国/非 Parquet 合成来源；目录零数据 I/O；所有字段映射覆盖；
时钟/夜盘/无未来函数；历史规则和结算实际路径；同输入结果、加载耗时与峰值 RSS。
必须先记录可复现性能基线，使用聚焦测试；不在公网压测，不因 ADR 落盘声称实现完成。

## 已落地的第一批 JSON 发现接口（#447）

- 标准库公共包 `traderesearch_data`（独立 wheel 名称 traderesearch-data）负责 Bundle JSON
  校验与类型，隔离 wheel 验证无需导入 sources/tools/server/Nautilus。
- 平台 `sources.registry` 用清单替代硬编码模块表，源激活保持显式；客户端成员不在服务器
  激活。`sources/Local/bundle.json` 显式列出四个行情和一个历史规则成员。
- `installed_bundles` 首次发现后复用不可变快照；显式刷新先完整验证，再原子替换。
  无效更新报错但不破坏上一份有效快照。数据字节不进入该缓存。
- 清单大小限单文件 1 MiB、总计 16 MiB、最多 256 个 Bundle；拒绝重复键/ID、未知类型、
  失效关系、越界符号链接和错误更新策略，不静默回退。盘点输出分页且不会实例化接入代码。
- update_policy 区分 mutable_history/immutable_snapshot/live_stream；版本依据与回放声明独立。
  本批仅校验声明，不据此声称底层历史数据已冻结或实时记录已实现。
- 提供可选 Docker Bundle 只读清单/包挂载；没有执行停机、迁移、发布或数据传输。
- 中立 ProductBinding 将平台 product_ref 对应到 Bundle 成员的 source_product_ref；分类仍引用
  平台产品身份。既有产品和用户分类记录尚未迁移，不按同名产品自动合并。

### 聚焦验证与性能边界

GTHT Python3.14.0/macOS arm64，热 OS 缓存：旧模块表 5×10000 次约 0.229–0.248ms，
JSON 不可变快照热读取同规模约 0.285–0.300ms；单次额外约 5ns，不能解释为端到端提速。
1 Bundle/5 成员的 100 次元数据重新发现约 11.2–13.9ms（约 0.11–0.14ms/次）。
进程峰值 RSS 为约 13.4MB → 16.8MB，包含标准库 JSON/dataclass 导入，不是行情驻留内存。
这些是隔离元数据实验，未测公网、真实行情加载 p95 或并发任务内存；当前不改实际数据读取。

现有来源声明/精确适配选择、合约 catalog staging 和新 JSON 规则聚焦测试通过；真实服务器
安装/发现集合、客户端入口、规则数据加载与产品分类迁移仍需后续验收。

### Public optional adapter declaration

`traderesearch_data.nautilus.NautilusAdapterContract` is now the single definition
used by source declarations and bridge admission. It contains metadata only and
has no Nautilus runtime or platform-domain imports. LocalCNFutures path constants
resolve on first access rather than during package import, so importing its feed
contract no longer initializes artifact paths or NumPy. Exact path resolver
outputs and current source admission/staging remain covered by focused tests.
This does not yet externalize the complete source implementation or replace the
federated catalog's runtime availability/count projection.

### P1 progress：规则提供者与失败关闭（2026-10-27）

第一批 P1 只完成两个可独立验证的边界，不声称源侧已独立：

- 历史规则提供者不再由中央硬编码为 `FieldHistory:market_rules:exchange`。源成员声明
  `trading_field_provider_ref` 与 `trading_field_related_members`，执行侧只验证关系
  并调用源提供的 loader；`TradingFieldProvider` 只要求 `resolve_at` 协议，
  `TradingFieldValue` 只要求字段，不再以具体 `FieldHistoryProvider`/
  `HistoricalFieldValue` 类作为准入条件，也不再导入规则 fallback 枚举/异常类。
  协议现位于公共 `traderesearch_data.rules`。`ResolvedSource` 携带选定 Bundle 成员的
  `related_members`，规则绑定要求 provider_ref 必须在该冻结关系中；空关系不再放行。
  中央不再导入 FieldHistory 模块或 OpenCTP latest 常量；源成员声明
  `trading_field_latest_provider` / `trading_field_latest_source_prefix`，证据校验只使用
  冻结源字段。源 loader 仍返回现有 FieldHistory 实现，完整规则数据协议迁移尚未完成。
- 多合约目录显式失败。`stage_catalogs` 在写任何 catalog 前检查同一品种的多个合约
  并拒绝；这是防止错误结果的 fail-closed，不是多合约已完成。
- DAY1 的 `settlement_price` 已写入 catalog receipt 的 `settlement_records`（合约、交易日、
  事件时刻、价格），不再只停留在输入 `MarketBar`；`load_catalog_settlement_records`
  提供只读访问。DAY1 staging 同时通过 `to_nautilus_daily_settlement` 写入原生
  `InstrumentClose(DAILY_SETTLEMENT)` 表。replay 已增加 InstrumentClose data config，
  合成两日 DAY1 测试确认原生回放消费 2 个 Bar + 2 个结算事件（native_iterations=4）。
  六日含持仓测试验证 3 次 DAILY_SETTLEMENT PositionAdjusted、PnL 400/1000/1000、
  realized_pnl 3000 CNY、账户 total 1003000，以及 maintenance margin
  2062.00→2066.80；这仍是合成夹具，不是真实规则/异常日历验收。
- DAY1 不再静默复用 MIN1 `stage_contract_minute_catalog`。源 loader 使用
  `stage_contract_daily_catalog`，由 `iter_daily_bars` 读取 `TRADING_DAY`/结算列，
  由源声明的 `session_for_day` 把日期标签转换为交易所收盘时钟，并写入
  `1-DAY-LAST-EXTERNAL`。当前可用前一交易日夜盘起点：从 term-structure 的唯一
  `TRADING_DAY` 序列取前一个标签，若源声明 night session 则起点为前一日夜盘开盘，
  终点为当日日盘收盘；这比“当天日盘拼接”覆盖了周末/长假后的前一交易日夜盘。
  它仍使用当前产品时段字段，没有历史时段变更/版本化异常日历，不能据此声称 DAY1
  已完成。一次本机只读检查使用真实
  `term_structure-listed_contracts.parquet` 的 `A1001`，写入 10 根 DAY1 Bar，
  Nautilus readback 数量/OHLC/事件时刻一致；首个事件为 2010-01-04 15:00
  Asia/Shanghai。该检查是合成/真实小窗口的局部证据，不是完整验收，也没有
  作为常驻慢测试加入聚焦套件。另一次真实 MIN1 检查用 `build_contract_spec` 生成
  `T2403`，写入 3 根 `T2403.CFFEX-1-MINUTE-LAST-EXTERNAL` 并 readback；确认大写
  合约身份与现有源一致。该检查同样不代替完整回放验收。
- 源 loader 的输入改为不可变 `CatalogLoadRequest` / `CatalogStagingRequest`，包含成员、
  频率、Bundle `related_members`、请求路径、窗口和输出根；中央只在调用时构造，
  源 loader 不再接收可变的 `staging_requests: list[dict]`。`NautilusCatalogLoader`
  只接受这个请求。LocalCNFutures 在 staging 前拒绝未声明历史规则成员的请求；
  规则成员的实际加载/单次缓存仍未切换。规则表新增 O(1) `historical_field_revision`
  （写事务 trigger 递增）；LocalCNFutures 在调用方 SQLite 连接上建立 savepoint，
  同一快照内只读一个 revision 值、读取 frame、构造 provider；缓存键为数据库路径 +
  revision。命中检查不执行 `COUNT(*)`/全表扫描，provider 装载在 single-flight 锁内。
  本机 10 万行热缓存实验：revision 读取中位约 0.000666ms，旧 `COUNT(*)+MAX(rowid)`
  约 2.1155ms；这是修订键步骤，不是整个任务耗时。并发首次装载测试确认只调用一次
  loader。
- 保证金不再取 `max(long, short)` 或把缺失补零。源 loader 要求多空两侧都存在且相等；
  不相等或缺一侧时报告“single-margin Instrument contract”不可表示。按用户明确的简化
  边界，由 Bundle 直接设置 Nautilus `margin_init` / `margin_maint`。本 Bundle 对统一
  交易保证金率将两者设置为同一值，不要求原始数据增加两条不存在的字段；bridge 不再
  做保证金语义映射。仍检查有限值和非负值，不把多空差异压成最大值。此修正不代表
  当前快照已成为历史规则，也不代表完整保证金/强平已验收。

多合约的显式引用形状与消费者迁移条件见
[ADR-186](186-multi-contract-catalog-references.md)；在消费者契约确认前保持
fail-closed。

仍规则/日历/结算现有字段与缺口见
[source-rule-calendar-settlement-2026-10-27.md](../audits/source-rule-calendar-settlement-2026-10-27.md)；
旧→新消费者迁移状态见
[source-migration-matrix-2026-10-27.md](../audits/source-migration-matrix-2026-10-27.md)。

未完成：显式多 catalog 消费者契约、真实 DAY1 异常日历/结算验证、无损保证金、
非 CN/非 Parquet 独立 Bundle、RunSpec 输入身份冻结。

### Source-owned catalog staging entrypoint

The installed market member's `integrations.nautilus_catalog` now selects the
loader using `NautilusCatalogLoader`. Central staging validates a unique
server-installed Bar member, exact frequency and explicit entrypoint before
importing plugin code. LocalCNFutures owns its former contract UID parsing,
lifecycle selection, trading-spec mapping and source-path selection in
`nautilus_catalog.py`; the predecessor implementation is removed from central
staging. Repeated requests for one contract reuse its staged result within the
call, rather than reading/writing the source again. A separate synthetic
non-CN loader verifies the dispatch does not interpret Chinese UIDs or parquet
paths. Calendar summaries remain receipt-based with no source reread.

Remaining boundaries are explicit: this Bundle loader still calls existing
platform price/catalog and native conversion utilities; it is not yet a fully
external installable source package. The source registry's execution-admission
checks and historical-rule binding still need neutral/source-owned ports.
Current RunSpec records do not yet freeze the Bundle manifest/package revision.
The existing product-keyed catalog return contract is unchanged; this tranche
does not establish full multi-contract roll/replay acceptance.

### P2 输入身份骨架（2026-10-27）

新增 `FrozenBundleInput`/`freeze_bundle_input`：固定 authority、owner、device、Bundle
版本与 metadata fingerprint、mapping_version、成员和 related_members，并生成紧凑
`source-input:<sha256>` 引用。CatalogLoadRequest 现携带 bundle_id/version/fingerprint/
member_id，staged catalog receipt 和 replay receipt 的 `source_inputs` 都记录同一
身份；这已进入实际 staging/replay receipt，但尚未写入 RunSpec。实时/可变数据源
每轮可以有不同数据 revision：FrozenBundleInput 固定的是来源选择、Bundle/member
代码与映射身份，不是本轮行情字节；不得因为本轮数据与上次不同而拒绝运行。每轮
receipt 只记录本次观察作为 provenance，不跨运行比较内容。

### P3 元数据只读描述（2026-10-27）

新增 `installed_bundle_descriptors()`：只读取 `installed_bundles()` 的 JSON 清单，
返回 Bundle/member/频率/关系/更新策略/product_bindings，`availability` 显式为
`unknown`、`product_count=None`，并带 canonical metadata fingerprint。该函数不调用
`load_all_sources`、不实例化 Nautilus、不读行情。fingerprint 是清单元数据身份，
不是行情内容 revision。已增加只读路由 `/api/product-library/installed-bundles`，返回
`metadata_only=true` 与同一描述；它尚未替换现有 `product_source_descriptors()`/目录
UI；运行时可用性与权限投影仍需后续切换。


### 用户确认的直接执行字段边界（2026-10-27）

Bundle 的可选 Nautilus 集成直接提供 Nautilus 字段和数据类型；平台的展示字段据此补全，
不另建执行字段翻译表。JSON 目录、权限和产品说明属于平台控制面；历史回放与在线交易的
行情/事件属于执行数据面。保留现有 `engine.run_catalogs` Rust 原生读取/合并回放，
不能为了目录展示把行情转成 Python 行列表或增加一份缓存。源格式必要的转换归 Bundle，
只在数据确实尚非 Nautilus 可读格式时发生一次；实时连接仍由对应 DataClient/适配器负责。

此次只修复 Bundle 保证金初始化的错误原始字段要求；平台产品字段补全和完整源包外置
仍需继续接入，不能将本次提交称为所有字段已对齐。研究依据和下一步范围见
[source-bundle-takeover-2026-10-27.md](../audits/source-bundle-takeover-2026-10-27.md)。


### 前后端同名字段的首批接线（2026-10-27）

LocalCNFutures 的 `instrument_fields.py` 现在拥有唯一字段生产实现；其产品对象通过
`get_instrument_fields()` 提供这些值，执行准备也调用同一实现。原平台
`cn_futures_trading_spec_fields` 及其中国期货字段转换已删除。Bundle 对原始供应格式的
必要处理留在 Bundle 内；对外提供 `price_increment`、`multiplier`、`margin_init`、
`margin_maint`、`min_quantity`、`max_quantity` 等 Nautilus 名称，平台不重算。

平台产品详情仅调用提供器并保留同名字段，Decimal 以字符串无损 JSON 传输；React 产品页
用公共分页表格显示相同键和值，中文/英文仅翻译标签，未知新字段也直接展示。
多空/按手规则尚不能表达为当前单一比例时，Bundle 不伪造比例，保留原规则数据供审计。
这仍是当前快照信息，不得当作历史交易规则冻结的完成证明；其余 Instrument 属性仍需逐项核对实际执行消费，不能因页面能显示就声称全部 Nautilus
能力接通。Bundle 的 min_quantity/max_quantity 已同名传入 Nautilus FuturesContract；
不另建数量限制模型，缺失时沿用 Nautilus 默认值。有限、正整数及上下界校验发生在
初始化，不进入逐 Bar 热路径。
原生行情回放 `run_catalogs` 未改变，没有新增 Python 行情物化或逐 Bar 字段查询。


### Product 的目标边界

平台只保留轻量产品目录记录（稳定引用、名称、分类/产品组关系和来源引用），不维护另一份
可交易合约/保证金/行情/持仓计算模型。Bundle 的 Nautilus Instrument 与原生数据接口是
执行入口。当前旧 Product 子类上的 get_instrument_fields 只用于迁移现有消费者；本批不
扩充旧 Product 的计算职责。待目录、分类、因子产品维度及来源查找切到轻量引用后，删除
对应旧 Product 执行/加载实现，不再增加一套平行的 Product→Instrument 字段转换。

### 平台规划不再实例化 Product（2026-10-27）

catalog_plan 仅收集 RunSpec 已选产品/合约引用，不导入 settings、平台 Product 或数据源。
删除了平台的 _expand_product_paths 及未按数据修订失效的全局展开缓存。解析引用属于已选
Bundle 的执行入口，使用实际 CatalogLoadRequest 起止区间；不再从旧 start_date 字段猜测
区间或默认展开 1900–2100 的合约列表。重复产品引用只在同次调用内解析一次，不跨运行
缓存可变来源的合约结果；直接物理合约入口保持可用。

LocalCNFutures 内部仍暂用其原有产品元数据读取合约生命周期；这不代表厚 Product 已从
整个仓库删除，也不代表多合约回放已接通。平台对该源的实例化依赖已从此规划入口移除，
后续需将源内部读取器替换为本 Bundle 的轻量目录实现，并将实际输入身份记录到运行结果。
