## 这份“合规”文档的含义 {#scope}

本页把合规理解为可复现、可解释、可追责的工程控制：用户能够知道一个测试字段是什么类型、默认值从哪里来、提交时实际采用了什么值，以及结果能否回到对应的输入、代码、数据和权限边界。它不是法律意见、监管认证或对任何司法辖区的合规声明；组织仍需把这些控制映射到自身适用的制度、保留期限和审批政策。

结构参考 NIST SSDF、NIST CSF、OWASP ASVS、NIST 对 provenance 的定义，以及算法交易规则中关于测试、变更记录和可监督记录的要求。参考规范列在本页末尾，实际采用的控制以当前代码和测试为准。

## 字段契约是核心控制 {#field-contract}

每个可提交的测试字段至少要能回答下表问题。字段清单由后端注册协议提供，UI 只能选择和编辑注册过的字段；未挂载的 UI tab 不应导致字段偷偷改变，未适用的字段也不能用一个看起来像默认值的假值代替。

| 控制项 | 必须说明的内容 | 验证或证据 |
| --- | --- | --- |
| 标识与语义 | 稳定字段名、业务含义、单位、适用测试类型和适用范围 | 注册 schema、配置页说明、服务端校验 |
| 类型与约束 | JSON 类型、枚举、范围、精度、是否允许空值或引用对象 | 字段注册和 preview 错误 |
| 默认值 | 默认值、默认值来源、注册版本、为何是中性或安全值 | 规范化配置与版本记录 |
| 输入来源 | 用户显式输入、模板、因子/产品引用、派生值或系统环境 | RunSpec 输入来源标记 |
| 实际生效值 | 提交后解析出的最终值；包括 auto 模式、条件默认和单位换算 | 冻结 RunSpec、任务详情、策略运行摘要 |
| 适用性 | 何时省略、何时必须填写、何时需要数据能力或历史事件 | 条件校验、失败原因和适用性标记 |
| 版本与完整性 | schema/configuration revision、RunSpec hash、源码和数据引用 hash | 提交收据、Job、Artifact 元数据 |

字段文档不应只抄 UI 标签。例如“自动”不是一个足够的生效值；若运行时根据产品或数据能力选择了 DMTM、费率、频率或价格基准，详情必须显示解析后的实际值和选择原因。

## 默认值、显式值与生效值 {#default-effective}

平台需要区分四种状态：用户明确填写的值、注册默认值、根据其他字段推导的值，以及因不适用而省略的值。显式 `null` 也不能随意等同于“没有填写”，除非字段契约明确规定。

预览和真实执行必须经过同一套规范化和解析逻辑，形成相同的 effective configuration；UI 展示的候选默认值不能代替 worker 实际读取的值。对于会在运行时按产品、数据源或模式改变的字段，默认值应保持中性，并在 RunSpec 和摘要中记录最终解析值。若某种 auto 行为允许回退到零手续费或其他保守路径，必须在摘要中以高显著性标识“回退及原因”，不能让用户把它看成真实历史费率。

## 条件字段与测试规则 {#conditional-fields}

条件字段要同时由 UI 注册、服务端校验和执行前检查约束。典型判断顺序是：先确定测试类型和核心对象，再判断字段适用性，然后解析默认和引用，最后校验数据能力、历史覆盖、时间区间和跨字段关系。

遇到缺少历史费率、数据字段、产品路径或因子源码时，系统要根据模式选择明确失败或明确的中性回退；不能在运行时悄悄采用一个与运行配置不一致的值。失败任务也应保留已经形成的配置和失败原因，便于区分配置错误、数据错误、执行错误和展示错误。

## 从草稿到证据的不可变链 {#immutable-chain}

```text
页面草稿
  → 配置规范化 / configuration revision
  → 提交时冻结的 RunSpec
  → Job 与 Attempt
  → 结构化 Artifact、日志和结果摘要
  → Research / Report / Evidence 的正式绑定
```

草稿可编辑；RunSpec 是提交时的历史事实；Job 是用户可见任务身份；Attempt 是一次执行；Artifact 是可验证的输出。重试可以产生新的 Attempt，但不能改写旧 RunSpec。任何会改变因子源码、产品范围、数据源、字段默认、时间语义、策略逻辑或输出定义的 material change，都应形成新 revision、新 RunSpec，并保留旧记录供比较。

## 研究输入与时间语义 {#provenance-time}

一条可复现记录至少要关联：因子或因子集合的稳定 ref 与版本、产品路径或产品组、数据源与字段能力、源码/策略代码 hash、配置 schema 和 RunSpec hash、Job/Attempt、输出 Artifact、执行身份以及创建和完成时间。

时间字段必须说明时区、精度、日历和边界含义。存储和排序可使用标准化时间，但面向用户显示要保留声明的时区；同一时间点的订单、成交、费用和持仓事件应有稳定排序规则。图表横轴的显示时区不能改变原始事件时间或收益计算。

## 权限、公开与数据边界 {#access-boundary}

技术文档可以公开读取，但 Job、RunSpec、策略源码、研究工作区和生成物仍按对象权限判断。报告公开只扩大报告及其允许的证据摘要可见性；Research 共享或公开才决定授权读者能否下载相应文件和生成物。客户端、服务器 Profile Agent 和 Manager 的登录/能力凭证属于不同边界，不能因为 Agent 在服务器上运行就跳过服务端授权。

跨服务器读取应通过统一的 Manager 业务 helper 和明确的对象引用完成；不能让每个表格各自扫描文件系统或猜端口。数据传输的大小、缓存时间、下载范围和撤销行为都应记录在接口和访问控制测试中。

## 代码架构中的控制落点 {#code-mapping}

- 测试字段注册、配置规范化和执行上下文：`server/manager/services/test_authoring.py`
- 公共/私有入口、会话和传输边界：`server/manager/http/request_security.py`
- 用户、设备和公开访问策略管理：`server/manager/http/access_control_routes.py`、`server/manager/http/account_admin_routes.py`
- 任务列表、聚合和跨服务投影：`server/manager/http/job_list_routes.py`、`server/manager/http/job_transfer_routes.py`、`server/manager/storage/job_index.py`
- Job、Attempt、RunSpec hash、Artifact 和自定义分析的持久化：`server/jobs/repository/`
- 公开技术文档的清单编译和安全渲染：`server/manager/services/technical_docs.py`
- 公开访问和渲染安全的回归证据：由发布流水线中的公开访问、文档编译和容器打包测试持续验证；测试源码不作为生产镜像的公开运行入口。
- 架构决策、迁移和废弃入口的登记：`docs/adr`

这些路径是职责定位，不表示路径下所有文件都是公开 API。对外接口仍以 API/CLI schema 为准。

## 变更、审批与发布证据 {#change-release}

工程上至少应记录变更何时发生、由谁提交、改了什么、为何改变、由谁批准（若组织政策要求）、影响哪些字段/测试/报告、是否重新测试以及发布到哪个 revision。重要的默认值或计算公式变化要附带回归样例和旧新 RunSpec 对照。

部署验收要覆盖三条链：文档和接口能读、任务能以冻结配置运行、运行后的结果和生成物能按权限读取。仅“服务启动成功”不能证明配置契约或计算结果正确。

## 保留、失败与恢复 {#retention-recovery}

成功和失败任务都要保留足以解释执行的冻结输入、状态转换、错误摘要和已有生成物；清理只能按明确的保留策略和授权执行。索引是 Manager 的投影，不应被误当成远端 Job 详情的唯一权威；同步中断后要能重新投影而不重复创建任务。

当数据源、工作端口或网络暂时不可用时，应返回可区分的依赖错误并保留请求身份，恢复后从原始 Job/RunSpec 继续读取。不能通过运行时“补默认”或修改历史数据库来掩盖版本迁移问题。

## 已知边界与审查触发器 {#limitations-review}

当前文档不宣称完成某个司法辖区的全部监管义务。以下事件应触发重新审查：新增测试类型或字段；改变默认值、auto 解析、手续费/保证金/时间规则；改变因子、产品或数据源的权威来源；增加新的公开或共享路径；更换存储、队列、执行容器或第三方依赖；改变保留和删除策略。

## 参考规范 {#reference-standards}

- [NIST Secure Software Development Framework（SP 800-218）](https://csrc.nist.gov/pubs/sp/800/218/final)：用于组织安全开发活动、供应链和发布证据。
- [NIST Cybersecurity Framework 2.0](https://www.nist.gov/publications/nist-cybersecurity-framework-csf-20)：用于按 Govern、Identify、Protect、Detect、Respond、Recover 组织控制目标。
- [OWASP Application Security Verification Standard](https://owasp.org/www-project-application-security-verification-standard/)：用于把安全要求写成可测试的技术条目，而不是笼统承诺。
- [NIST Provenance glossary](https://csrc.nist.gov/glossary/term/provenance)：用于定义来源、演进、所有权、位置和变化的时间线。
- [MiFID II RTS 6](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32017R0589)：用于参考算法交易测试、重大变更和记录完整性的监管语境；不等同于 FactorTester 的法律适用结论。
