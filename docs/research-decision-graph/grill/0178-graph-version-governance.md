# Grill 178 — 图版本治理与研究分支续接

Status: closed; decisions 178.1–178.17 accepted and consolidated into Grill 179.

本轮审计区分图定义变化、活动版本切换和既有研究的跨版本续接，避免把
Server Maintenance 行为误写成因子研究步骤。讨论以现存 v4–v8 数据库、
v1–v3 Git 历史、既有 continuation trace 和 Grill 146 为事实基线。

## Grill 178.1 — 禁止混用“图升级”

**问题。** 是否继续用“图升级”同时指代创建新图、切换活动版本和迁移
既有研究？

**建议。** 禁止该混合术语，分别使用：

- **图版本发布**：创建并审计一个不可变图版本；
- **图版本激活**：只改变服务器 active pointer；
- **研究分支续接**：把一个受影响分支接到直接子版本中经影响分析确定的
  恢复位置。

研究分支续接只验证版本身份、父子关系、授权、兼容性、影响范围、lineage、
恢复位置和回滚目标。它不得执行数据目录或字段覆盖检查，不得生成 TrialPlan，
不得解释研究结果、创建或解除义务、修改因子或重跑 Job，也不得机械经过能力
解析、数据契约或因子语义节点。

**用户决定。** 接受；三类任务都由服务器 Agent 处理。

**落实语义。** 三类任务均属于 Server Maintenance Agent，但任务归属不代表
自行生效权限。Agent 可以构建版本、执行确定性影响分析并提出激活或续接方案；
需要授权的高风险 effect 仍由对话中的 document-grounded grill 审计约束。

## Grill 178.2 — 独立的 Server Maintenance Skill

**问题。** 是否继续依赖 Research Harness 中零散的维护说明，还是建立一份
专门指导 Server Maintenance Agent 的基础 Skill？

**用户决定。** 需要建立独立 Skill。

**现状核对。** `cli-anything-factortester-research` 只提供
`--role server_maintenance` 恢复入口和面向旧 Job continuation 的命令；
`research-obligation-cycle` 的 `impact` 模式属于 Research Agent，用于提出
图或方法变化造成的 Contract/义务影响。当前不存在完整指导图版本发布、激活、
分支影响分析、恢复节点选择和续接验收的 Server Maintenance Skill。

**落实语义。** 新 Skill 使用渐进加载的发布、激活、影响分析和分支续接
reference；服务器仍只保存 provider-neutral capability 描述、hash、批准状态和
审计引用，不保存 Skill 名称或正文。Skill 不能自行批准 activation 或
continuation effect。

## Grill 178.3 前提 — 生产分支不自动续接

**用户纠正。** 生产环境中正在运行的研究必须继续使用其 pinned Graph；除非
用户主动在 FTClient 选择目标版本，或在 Research Agent 对话中明确要求切换，
否则图版本激活和影响检测都不得移动该分支。切换行为必须由程序规定，不能由
Agent 临场编排。

**控制权纠正。** Server Maintenance Agent 不把分支“送入”它选择的审查
状态。用户授权切换后，目标 Graph 必须保留旧分支的同名 `current_node`，并由
该目标节点自己的重入门直接控制义务审查。Server Agent 只验证和执行图协议，
不能选择、跳过或替换重入门；后续义务路径由 Graph 决定。

**独立节点方案被否决。** 用户指出重入审查总是附属于某个目标节点，不能
成为独立的 `reentry_obligation_review` 节点。采用 **Node Re-entry Gate**：
切换后 `current_node` 不变，目标节点的普通工作和普通出边在重入义务满足前被
门控。若需去其他节点取得证据，专用解决路径最终返回这个目标节点，而不是
返回一个虚构的审查节点。

**用户决定。** 接受修订后的节点重入门模型。

**固定行为。** 每次用户主动切换时，同名目标节点执行重入门检查。未触发
requirement 时由确定性运行器 no-op 放行，不调用 Agent。触发后，Graph 要求
Research Agent 使用获批的义务 impact/discover 能力提出义务，经 adjudication
接受后才进入 Research Cycle。门未满足时统一隐藏普通执行和普通出边，只开放
目标节点声明的 resolution routes；路径完成后回到同一目标节点。门状态从版本
身份、requirement refs 和现有 Research Cycle checkpoint 推导，不增加表或
独立持久化对象，也不在每条普通边重复写相同 guard。

## Grill 178.4 — 多版本累计差异由程序一次计算

**初始建议被否决。** 初始建议要求分支逐个 direct-child 续接，以免跳过中间
版本义务。用户指出版本 lineage 和图结构均可由程序固定处理，不需要 Agent
逐版本参与。

**修订决定。** 允许一次显式请求从源版本切换到其任一后代版本。确定性运行器
验证唯一 parent lineage，并一次计算 source-to-target 的累计节点、边、能力描述、
政策和协议变化；不创建中间 incarnation，也不调用 Agent。目标节点不存在或
版本/状态协议不兼容时直接拒绝。累计 diff 一次触发目标节点的 re-entry
requirements；只有由此产生非机器化义务发现任务后，Research Agent 才参与。

## Grill 178.5 — 可累计的 Change Manifest

**决定：接受。** 每个新 Graph 版本除确定性结构 diff 外，必须携带经过独立
review 和 grill 的机器可执行 Change Manifest。Manifest 只可引用真实 changed
refs、目标图现存 affected nodes 和 requirement refs，并声明 semantic category、
preserve/invalidate 范围及显式 supersede/remove 关系。它与 Graph content hash
一同不可变。跨多个后代版本时，运行器沿 parent lineage 累计 manifest 并应用
后续 supersession；LLM 不重新解释历史版本。

**义务语义纠正。** “重新审查已有因子语义”属于正常的既有 Verification
Obligation 重开，不创建迁移专用义务或副本。重开保留原义务身份、此前状态、
证据和裁决历史；只有当前 Research Cycle 没有能表达该实质问题的既有义务时，
目标节点的重入门才触发 obligation discovery 提出新义务。

## Grill 178.6 — 义务大类、入口细则与具体义务

**用户纠正并接受的方向。** Graph 不维护数量庞大的“通用具体义务”，而维护
少量、稳定的 **Verification Obligation Category**。Research Agent 创建的具体
Verification Obligation 注册在大类下，而不直接绑定图中每一条细要求。

Graph 版本可以在某一大类下，为具体节点的 entry gate 新增或修改版本化的
**Entry Requirement**。它由小类标识和语义描述组成，表达进入该节点时需要重新
考虑的具体方面，但不替 Research Agent 生成因子专属义务，也不预先规定结论。

显式切换 Graph 时，程序先确定性计算目标节点新增或改变了哪些 Entry
Requirements，并按大类取回当前分支已有义务。Research Agent 逐项判断：

- 是否已有语义相似且证据范围完整的义务；
- 若相似但新要求覆盖了尚未处理的范围，则重开或修订既有义务；
- 若没有相似义务，则新建具体义务；
- 若确实不适用，则提交带范围理由的 `not_applicable` 裁决。

程序只负责 lineage、diff、大类过滤、身份、状态和证据引用检查，不用关键词或
向量相似度替 Research Agent 作语义裁决。Research Agent 的匹配、重开、新建或
不适用结论必须留下依据并进入既有 adjudication/audit 链路。

若 Research Agent 发现现有大类不足，可以提出新的大类候选；若大类存在但缺少
可复用的入口细则，可以提出新的 Entry Requirement 候选。两类候选都不能由
Research Agent 直接写入 Graph、推广到其他分支或改变入口门，必须经 Server
Maintenance、独立 review、document-grounded grill 与人工审计，并只进入未来
Graph 版本。

## Grill 178.7 — 覆盖审计、兜底大类与迁移重分类

**决定：接受。** 每个节点可记录一条轻量的 Entry Requirement Coverage
Decision：该节点的某个小类要求由哪些本地具体义务 revision 覆盖。只要小类、
义务、证据范围和相关 hash 未改变，正常运行直接复用；复杂语义匹配不在每次
进节点时重复，只在显式 Graph continuation 或相关输入改变时发生。

Graph 提供稳定的 `other`/未分类大类。Research Agent 找不到合适大类时，可将
具体义务暂时注册到该大类；这不会使它自动满足任何专门小类。目标 Graph 若新增
大类或在大类下新增/细化小类，continuation diff 必须把相关分类变化交给
Research Agent，检查 `other` 中的义务是否应重新注册。重新注册只改变义务的
分类投影，不改变义务身份，也不丢失既有证据和裁决历史。

该过程属于 Research Agent 的 continuation/re-entry skill：从原节点出发，处理
分类重审、入口小类覆盖、必要的义务重开/修订/新建，再回到同一节点。它不创建
独立迁移节点，也不让 Server Agent 代替 Research Agent 作语义判断。其具体边
表示方式仍待 Grill 178.8 决定。

## Grill 178.8 — 派生自环、证据资格与报告投影

**决定：接受。** Continuation/re-entry 是协议统一定义、运行时实例化并写入
trace 的系统自环边，不在每个节点人工复制普通边。它在同名目标节点重新执行
目标图版本的 entry gate。

若新要求产生尚未满足的义务，Research Agent 应先尝试补足。能够补足时，旧证据
在 provenance、scope 和时序仍有效的范围内继续保留并与新增证据共同使用；不得
仅因 Graph 版本变化而重跑或丢弃。暂时无法补足时，旧证据仍不可变地保留，但对
依赖该未满足要求的主张只能作为参考，并必须标注“未通过目标图版本的入口义务
要求”；它不能授权通过受门控的 outward transition。

报告必须按时间顺序记录这条自环的实际处理：切换原因和版本、累计语义变化、
义务重分类、重开/修订/新建、各 Entry Requirement 的覆盖关系、保留或降为参考
的证据、尚未满足的要求及下一步。任何非 continuation 的普通节点 entrypoint
处理也必须进入中文研究报告。报告内容由 trace 确定性投影；未变化的缓存命中可
简洁记录并按需展开，不重新调用 LLM，也不把原始 trace JSON 塞入正文。

## Grill 178.9 — 证据资格按主张与要求限定

**决定：接受。** 新增小类要求未满足时，不得把该节点产生的全部历史证据整体
降级。限制必须落在“Evidence 所支持的具体 Research Claim × 未满足 Entry
Requirement”关系上：依赖该要求的主张只能引用旧证据作为带警示的参考，不能据
此通过入口门；与该要求无关、且 provenance、scope、时序均未变化的主张与证据
保留原资格。报告必须说明受影响的主张和原因，不能只显示笼统的“节点证据失效”。

## Grill 178.10 — 测试节点受阻与当前报告/CLI 审计

**决定：接受。** 测试节点被未满足的 Entry Requirement 阻塞时，Research
Agent 必须开始准备下一项能够改变相关义务或主张状态的 TrialPlan；若无法提出
仍有决策价值的 TrialPlan，则进入有证据边界的研究结束流程，不得静默通过测试
节点。受影响的 requirement、具体义务、Research Claim、Evidence 资格和待补
Trial 必须逐条投影到报告，不能合并成一句笼统结论。

**现状审计。** 生产 Graph 已由 `factortester research-graph` CLI 管理，现有命令
覆盖 publish、versions、active、validate、propose、review、audit、activate、
start、context、next、continuation-preview、continue 和 advance 等生命周期。
CLI-Anything harness 中另有本地 observed/draft/capabilities/replay 命令；它不是
服务器 canonical Graph 管理面的替代品。

报告链路已有简体中文结构化 narrative、schema/大小/引用校验、checkpoint
fragment、连续 journal 和确定性 Markdown renderer。但是当前 `research-graph
advance` 的 `--narrative-file` 仍是可选项：服务器 transition 可以先成功，CLI
随后只返回 `local_narrative_required` 或 `local_report_sync required`。因此现在的
实现只能保证“提供 narrative 时格式受控”，尚未保证“每个 Graph entry/edge 都
先形成合格报告贡献再被 Agent 视为完整完成”。Entry Requirement coverage 和
逐条 evidence qualification 也尚未进入现有 carrier/report schema。

## Grill 178.11 — Graph 强制通用报告方法

**决定：接受。** 每个 entrypoint、节点处理和边都必须声明一个或多个版本化、
可复用的 **Report Method**。Graph 只规定何时报告、必须回答哪些通用语义问题、
必须绑定哪些种类的 canonical refs；不得写因子专属正文、Markdown 排版或 FTClient
布局。CLI 负责方法 schema、执行前校验、中文要求、引用完整性和确定性渲染；
Research Agent 只提供方法要求的分析内容。

每个方法产生有顺序的 **Report Items**，受影响对象必须逐条报告，不能揉成一段。
一条 Item 可是一句话、列表、表格或内容寻址图像，并可绑定它实际分析的新增
Evidence、TrialPlan 项、Verification Obligation 变化、Research Claim、Job/Run
或其他 delta。FTClient 在对应行旁投影带中文 alias/摘要的 Chip，点击后按需读取
审计详情；正文不显示裸 UUID，也不复制完整 trace 或大型 artifact。

同一个通用 Report Method 可被多个节点和边复用。方法目录与 Graph 引用均参与
版本/hash 审计；新增具体研究内容不允许导致不断新增报告方法。

## Grill 178.12 — 报告覆盖门、UI 与既有历史补全

**决定：接受。** Active Graph 可在 entry、节点处理和边上登记 required Report
Methods 及逐项要求。Research Agent 提交的 Report Items 必须完整覆盖后才允许
继续；缺失时 Graph/CLI 返回逐条 `missing_report_requirements`，明确缺少哪个
method、哪个对象项或哪类 binding，不能只报“报告不完整”。本地正文不上传；
每条 Item 直接携带 Graph 声明的 `report_requirement_id`；要求逐对象报告时还携带
`subject_ref`。CLI 对期望 ID/subject 与实际 Item 做确定性集合、基数和 binding
校验。transition evidence 只携带由这些已校验 Item 派生并绑定 Graph/节点/边/
内容 hash 的紧凑 coverage 投影，复用既有 trace/evidence envelope，不新增
receipt 对象或报告数据库。

**UI 要求。** FTClient 的正文改为逐条 Report Item 时间流。每项可使用一句话、
列表、表格或图像，并在相邻位置展示有中文 alias 的 Evidence、TrialPlan、义务
变化、Claim、Job/Run 等 Chip。Graph continuation/re-entry 必须使用明显不同的
视觉和交互语义，逐条展示图版本变化、分类重审、入口要求覆盖、证据资格变化和
未满足项；它仍属于同一连续研究报告，不能伪装成普通研究阶段。

**迁移顺序约束。** 只有包含上述 Report Method contract 的新 Graph 版本完成
发布、独立审查、grill、人工审计并可用后，用户明确选择的既有研究分支才可通过
continuation 切换。切换首先形成逐条升级审计，再补充旧格式报告缺失的逐项内容。
旧 checkpoint、Evidence 和原始 narrative hash 不得被删除或伪造成由新图产生；
具体补全的不可变表达方式留待 Grill 178.13 决定。

## Grill 178.13 — v8 一次性迁移与未来按需补报

**用户纠正。** 当前 v8 的既有升级记录不再要求 Research Agent 逐项补充。它由
一次性维护迁移完成：只根据已有 checkpoint、trace、Evidence、TrialPlan 和已
接受 narrative 确定性重建能够证明的 Report Items，并迁移到新格式；不能从旧
材料推出的分析不得编造，应显示为历史迁移缺口。该迁移不重跑研究、不新增因子
结论，也不改变原始 hash。

后续 Graph 版本若给既有节点或边增加 Report Requirements，continuation 当下只
确定性识别并在对应 node/edge anchor 显示缺失项；不创建独立的报告覆盖义务，
也不立即启动 Research Agent 补写全部历史。研究随后触达该节点、准备
经过该边，或该缺失内容成为当前决策所必需时，才把紧凑要求交给 Research Agent
补充。Research Agent 根据该须报告条目绑定的真实义务小类，查找并重开/修订
未充分处理的具体义务，或在确无对应义务时创建该小类下的实质性具体义务；验证
通过的 Report Item 解除报告门控。未触达的无关位置不消耗 token。

**UI 语义。** 节点报告显示为该研究阶段的内容；边报告显示为连接 source/target
阶段的独立过渡卡片。Graph continuation 进一步显示源/目标 Graph 版本和自环
语义。缺失报告在准确的节点或边位置显示待补占位、要求摘要和状态，不能显示成
已完成正文，也不能只放在一个全局缺口列表中。节点、普通边、Graph 升级边三者
必须具有不同但连续的视觉层级，并与版本树/报告滚动定位一一对应。

## Grill 178.14 — 须报告条目绑定义务小类

**用户纠正：必须绑定，撤销 Report Coverage Obligation。** Active Graph 中的
每个 report requirement 必须用版本化的 `entry_requirement_ref` 绑定图已定义
的某个真实义务小类。该关系说明“这一条为什么
必须报告”，并允许 CLI/FTClient 从小类找到本地具体 Verification Obligations、
Entry Requirement Coverage Decisions、相关 Evidence 和义务变化，形成有中文
alias 的逐条内容与 Chip。

缺失 Report Item 只是确定性的报告门控错误，不形成新的义务类型。Research
Agent 必须沿绑定小类寻找具体义务：已有但处理不完整则重开/修订；确无对应义务
则创建该真实小类下的实质性 Verification Obligation。若义务已有 accepted
adjudication、只是展示项缺失，则补齐 Report Item，不得伪造重复义务。

仍保持两个正交状态：`verification_status` 表示真实研究义务是否被证据满足，
`report_coverage_status` 表示该事实是否已按 Graph 要求形成 Report Item。写完报告
不能解除研究义务；研究义务已有充分证据也不能自动表示报告完整。

## Grill 178.15 — `data` 大类与现有 Data Contract 合并职责

**用户再次纠正：接受。** 稳定义务大类 ID 是 `data`，不是 `data_contract` 或
`data_fitness`。现有 Graph 节点 `data_contract` 作为 `data.*` 小类的主要定义和
处理位置：在该节点声明数据范围、来源、字段历史、point-in-time 可得性、样本最
新程度及其对 TrialPlan 的约束。这样复用现有架构，不再创建一套平行的 Data
Contract 对象。其他节点和边仍可引用同一批 `data.*` 小类；大类 ID 与工作流节点
ID 不被误认为同一个身份。

## Grill 178.16 — 像 Skill 一样可理解、可选择的 Requirement Catalog

**用户纠正：接受。** 只给 Research Agent 一组抽象 category/requirement IDs 不足
以支持可靠研究。每个 Graph 版本必须包含人类可读、机器可引用的 Requirement
Catalog。每个大类和小类至少声明：中文名称、它要回答的研究问题、何时选择、所需
证据、哪些事实不算满足、适用节点/边以及对应须报告内容。Research Agent Skill
负责指导如何选择、重分类和提出候选；Graph 负责提供当前版本的行业语义，不把
Skill 身份或正文存入服务器对象。

Catalog 使用渐进加载：常规 `context/next` 只返回当前节点/边相关的大类名称、
一句话摘要和小类 IDs；Agent 需要选择或裁决时才按 ID 读取完整说明。新增/修改
大类、小类或描述必须进入新 Graph 版本和维护审计，不能在运行分支中静默改义。

## Grill 178.17 — 「研究」中的 Graph 版本浏览

**决定：接受。** FTClient 的「研究」模块增加 Active Graph 浏览入口，读取同一
不可变 Graph version store，展示版本 parent lineage、Active pointer、hash、
发布时间/激活状态、节点/边拓扑、Requirement Catalog、Report Requirements、
Change Manifest 和既有审计结果。Graph governance 审批仍在 Agent 对话中完成；
该界面不成为第二个审批系统。

当前数据库只保留 `factor-research` v4–v8，Active pointer 指向 v8；v4 的
`parent_version=3`，但 v1–v3 缺失。UI 必须把缺失祖先显示为明确占位，不得补造
Graph。历史恢复只接受能从 Git 历史、备份或已发布 artifact 重建并验证 exact
canonical JSON/content hash 的版本。未来版本继续写入现有
`research_graph_versions`，不新增历史图表。

**用户追加要求。** v1–v3 不能永久保留为缺失占位，必须从原始历史来源全部恢复
并存入现有版本表。已定位 v1/v2 原始 builder 提交 `689e141e…` 与 v3 builder
提交 `f1ac3d3b…`。恢复前必须在隔离历史 checkout 中重建 canonical JSON/hash，
确认 v1 Observed Graph 使用的固定计划投影，备份并 integrity-check 当前数据库；
恢复后验证 v1→v2→v3→v4 parent lineage 连续、v4–v8 bytes/hash 不变且 Active
pointer 仍为 v8。恢复记录使用明确的 history-recovery actor，不伪装成当年的发布。

隔离历史代码验证结果：v1 为 13 nodes/13 edges，hash
`d8d76b80fbca0342d3b8477e1594bfd7da1dab2924c7d2d078bf64e8ba44d64e`，且更换
factor family/configuration 不改变 Observed Graph；v2 为 14 nodes/19 edges，hash
`95a82ea250f1502b7ce7706f85a663738afc08f5ec7f8bcebc71d7082f6bf689`；v3 为
14 nodes/21 edges，hash
`ae7bbc1ad50b22e75c6f781ced3510cd05de250f966bbb402e7bba999421c3b2`。
