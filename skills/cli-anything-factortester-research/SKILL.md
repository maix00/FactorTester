---
name: factortester-research-skill
description: 通过 FactorTester 的真实 CLI 创建和管理研究、Profile 绑定、配置、Job、生成物、结构化报告、Research Graph、Evidence 与 obligations。使用当前契约，只作真实研究判断，由 CLI 推导机械字段。
---

# FactorTester 研究

通过已安装的 `factortester` 使用真实后端。不要运行 `python -m tools.cli.app`：它绕过安装入口，可能加载当前 worktree 中的过时代码。
本技能说明工作方法，不保存当前 Graph、研究事实或权限声明。

## 服务器智能体与登录

在 Manager 所有的服务器 Profile Agent 中，Manager 注入短期本地能力及匹配的 API 端点。
已安装 CLI 自动使用该能力，不需要用户登录会话；不要执行 `factortester configure`、`factortester login`，也不要复制浏览器 cookie。
普通客户端和独立终端的登录仍由用户完成。缺少登录仅阻塞相应运行时操作，不阻塞已授权的本地实现与测试。

## 先区分研究目录、报告与 Graph

普通研究及报告不要求创建 Research Graph，也不要求先绑定因子源码 worktree。
先读真实 CLI 帮助，不从显示名称猜测命令、对象 ID 或 JSON 字段：

```bash
factortester research --help
factortester research create --help
factortester research members --help
factortester research report-create --help
factortester research reports --help
factortester run --help
```

按本次任务需要执行：创建研究，绑定当前 Profile，创建报告，撰写章节和小节，提交并绑定测试，读取实际结果，最后关闭或归档研究。
使用每一步返回的精确身份。不要把研究目录、研究工作区、报告、报告载体与 Graph 分支当成同一个对象。

`research report-create` 返回可编辑报告的 `work_package_id`、`branch_id`，后续报告写入使用它们。
已有目录报告缺少可编辑载体时，用 `report-create --report-id <已有报告身份>` 恢复同一报告，不重复创建目录报告。
不要为修复报告转而调用要求因子 worktree 的旧工作区创建流程。
报告内容使用 `research reports` 管理；研究目录状态与 Profile 成员关系使用各自原生命令。
研究归档不等于取消运行中的 Job，需要取消时显式操作对应 Job。

## 页面辅助填写

使用 `factortester assist --help` 发现工作区和目标页面接口。
读取页面发布的 schema、完整结构文档、revision、页面身份及研究归属；根据用户目标选择独立 tab，不把研究文件夹当成可填写页面。
`self` 可访问已授权工作区的所有打开页面；研究 Profile 只能访问其研究文件夹和挂载的独立页面，由服务器再次验证范围。
当前页面只是默认目标，其他已打开页面不需要处于 active 状态。

```bash
factortester assist inspect
factortester assist drafts create --stdin
factortester assist drafts validate <draft-id>
factortester assist drafts apply <draft-id>
```

跨页面操作先看对应命令的 `--help`，指定目标 tab，不能用当前页 schema 替代目标页 schema。
准备完整文档，通过草稿设施校验并原子提交；不逐字段操作 DOM，不在 Profile 根目录或 `/tmp` 自建候选文件链路，不发明 schema 外字段。
IC 和回测配置的草稿至少保留一个配置组或策略组。
遇到 revision 冲突重新读取；后台页面的修改由既有持久草稿与激活导入流程处理，用户切换时加载。
只有收到实际应用结果才称填写成功，queued 不是已应用。

## 命令导航与执行边界

首次使用命令组先读 `--help`，机器处理使用 `--json`，非零退出码保留结构化错误。

| 命令组 | 用途 |
|---|---|
| `plan`、`workspace`、`run-step` | 准备有界研究配置并委托真实客户端 |
| `research graphs` | 下载 Graph、读取本地状态、评估候选 Edge |
| `trial-plan` | 在 Graph 外验证和冻结直接试验计划 |
| `research reports` | 创建、批量写入、修改、绑定、验证与导出报告 |
| `research evidence` | 片段绑定的 Evidence 目录 |
| `strategy` | 查看公开模板并验证 StrategySpec |
| `strategy-library` | 持久策略的新建、版本、共享、归档 |
| `workspace strategy` | 当前配置中的策略绑定与当场策略 |
| `skill-usage` | 记录实际批准并使用的技能 |
| `gap`、`operator`、`service` | 将平台缺口交给对应能力所有者 |

研究技能不负责 Manager 登录、服务器维护或客户端发布。
遇到已证实的平台缺陷，记录缺口并交给 `$factortester-server-maintenance`；仓库来源为 `server/skills/factortester-server-maintenance/`。
涉及部署时按需读其 `references/infrastructure.md`。维护已有脚本就使用脚本，不在本研究技能复制具体连接信息。
`factortester-manager` 属于维护边界，研究 CLI 会话不授予 Manager 或主机权限。

## 因子与策略来源

```bash
factortester factor-library families --scope all --json
factortester factor-library factors --json
factortester factor-library factors --scope mine --json
factortester factor-library factor-sets --scope subordinates --json
```

这些接口复用 Web/Swift 的公共、本人、直接下级权限投影。
不用旧参数配置表或客户端内部 SQLite 读取因子库。复制返回的 v2 ref，不从 alias 推导身份。
Profile 本地源码位于自己的 `factor-worktree`，服务器 Profile 采用同样布局。

Profile 在 `agent/<profile>` Git worktree 编辑、提交源码。发布顺序：
先从数据库库刷新 `download`，将 `download` 合入 `upload`，再将已提交的 `agent/<profile>` 合入 `upload`，最后由既有 upload hook 同步数据库。
任一步冲突先解决；不编辑 `download`，不绕过合并，不用隐藏 bootstrap 创建第二套工作区协议。
只有 `self` 可执行 `factor-library workspace user download|upload` 或将对象提升到用户库；其他 Profile 在自身 worktree 提交提案供审阅。

测试中新建的因子家族、因子、因子集合保存在 ResearchConfiguration 的 `temporary_objects`，连同 RunSpec 与 Job 原子提交。
多层内嵌依赖冻结并去重，不另建 Profile 因子集合 manifest。因子成员不能代表整个集合，保留集合身份及扁平化不可变成员引用。
Profile 源码是显式选择的本次 Run 输入，不自动写入用户因子库；Job 保留不可变源码提交物，直到用户清除该 Job 文件。

持久策略使用固定 `strategy_ref` 与 `revision_ref`，不能静默追随最新版本。
`strategy-library revisions show` 按需取源码，元数据读取不传源码。
`workspace strategy add-inline`、`update-inline` 只操作当前配置，`bind-library` 记录持久身份；最终走同一冻结入口并按源码哈希去重。
`StrategySpec` 仅使用公开模板、固定策略版本或 `profile:<path>` Strategy Actor，不填 Flow、StrategyBook 或内部 policy 实现名。

## 产品定义与运行冻结

产品组持久定义保存分类 Label 引用的正负路径，不保存分类解析后的产品清单。
手选产品记录明确选择的产品路径；选择库中产品组记录其身份，提交时由共享后端读取权威定义并冻结本次涉及的精确产品列表。
当场分类与产品组只属于该配置。不要通过修改共享库完成本次试验的局部选择。
读取 Job 保留的产品范围快照核对实际样本；历史复现不得使用今天的分类成员替换当时产品清单。

产品组对因子/因子集合的适用关系由产品组单独持有，不写入因子 manifest 的 `product_group_refs`：

```bash
factortester product-library groups subjects list product-group:<id> --json
factortester product-library groups subjects add product-group:<id> --factor-ref '<stable-factor-ref>' --factor-set-ref '<stable-factor-set-ref>' --json
factortester product-library groups subjects remove product-group:<id> --factor-ref '<stable-factor-ref>' --factor-set-ref '<stable-factor-set-ref>' --json
```

不同组的关联各自独立，不自动合并成产品并集。只有用户要求长期保留时才更改共享关联；先登记因子或集合，再建立持久关联。
单次 Job 中的临时对象不能冒充库对象。TrialPlan 与 RunSpec 冻结本次选中的明确引用。

## 提交与生成物

Workspace 保存可编辑配置；ResearchRun 保存不可变 RunSpec；Job 持有生命周期、结果和生成物。
按 `job_id` 观察、取消和重试，不用 `page_uuid`。
先 `run preview`，后 `run submit`。以返回的冻结配置为准，远端验证 Job 契约。

```bash
factortester job output-capabilities --json
```

提交前读取服务器生成物目录，使用可重复的 `run submit --output <name>` 选择适用输出，不凭记忆编造选项。
IC 的报告用序列和统计为 `ic_series`、`ic_statistics`；因子序列输出按当前目录选择。
已完成 Job 仅在保留的输入支持时用 `job generate <job-id> --output <name>` 补算。
从 Job 下载实际生成物，不以终端摘要或智能体编写的表格替代真实结果。

报告绑定的试验携带 `--profile`、`--work-package-id`、`--branch-id`。
CLI 冻结报告 HEAD、generation、root、hash 与 parent，默认等待完成并创建 `test_result` special。
后续分析挂在返回的 `report_collections[].report_follow_up.parent_id` 下。
CLI 从报告 HEAD 读取 `report_id`；智能体不能为 Run 手写或猜测它。
不能冻结完整报告身份时修复 scope，不声称自动挂载成功；只有故意不属于报告的任务才用 `--without-report`。

策略配置、数据映射、说明等有界文本依赖通过 preview 和 submit 的可重复 `--run-input [purpose=]path` 提交。
用途枚举看 `--help`，例如 `--run-input strategy_configuration=cost-model.yaml`。
这些文件作为 Job 输入保留到用户清理。普通 `.py` 附件是数据，不授予执行权限；自定义策略仍需校验后的 Actor 源码与 StrategySpec。

## 不依赖 Graph 的直接试验

直接试验不移动 Graph，也不满足 Graph obligation 或 Entry Requirement：

1. `run preview` 获取冻结 RunSpec hash。
2. TrialPlan 的比较角色引用该确切 RunSpec。
3. 用 `trial-plan create --trial-plan-file <plan.json> --run-spec-hash <hash> --trial-role <role> --comparison-id <id> --output <binding.json> --json` 冻结。
4. 用 `run submit --trial-binding-file <binding.json>` 提交。

需要挂报告时再提供 Profile、Work Package、branch 和明确存在的 `--report-parent-id`。
结果保留 Evidence、TrialPlan、RunSpec 引用；将这些 Evidence 纳入 Graph 是另一个显式动作。

## 报告撰写与修改

写入作用域始终为 Profile、Work Package、branch，不存在任意 `--file` 报告路径。
每批相关修改后验证。章节和小节结构使用 `chapter`、`section`、`subsection`、`special`，必须有具体主题标题；不能用“正文”“表格”“列表”或 `Body`、`Table`、`List` 占位。
内容使用 `entry`、`list`、`table`、`image`、`code`、`math`、`result`，这些组件不带 `--title`；需要标题时增加结构容器。

```bash
factortester research reports add --profile <profile> --work-package-id <package> --branch-id <branch> --component-id findings --kind section --parent-id <chapter-id> --title '研究发现' --json
factortester research reports add --profile <profile> --work-package-id <package> --branch-id <branch> --component-id finding --kind entry --parent-id findings --body-file finding.md --json
factortester research reports validate --profile <profile> --work-package-id <package> --branch-id <branch> --json
factortester research reports mutation-guide --operation move --json
factortester research reports mutation-guide --operation replace --json
```

报告更新由已有报告树索引和页面刷新链路显示，不直接写 Web 缓存。
每次嵌套写入显式指定真实 `--parent-id`。没有 parent 或 target chapter 时 CLI 写入最后一章，不根据上一次写入猜测父级。
换章使用确切 `--target-chapter-id`；相邻插入只能选一个 `--before-component-id` 或 `--after-component-id`，锚点必须在同一父级。
移动或替换先读 mutation-guide 的 `inspect_command` 与 `operations_file_template`，再用返回的 `submit_command`。
替换提交全部作者字段，不提交 `bindings`；CLI 重建类型引用绑定并保留流程绑定。

智能体必须自己创建 special 容器：Grill 决议使用 `--kind special --display-kind grill_resolution`，外部审阅使用 `--kind special --display-kind external_review`。不能将该容器发布为普通 section、subsection 或 entry，可以按语义嵌套。
义务分类分析用 `special` / `obligation_requirement` 和 `--obligation-requirement-id`。
Graph 原始 push、resolve、resume、abandon 事件只在时间线，不把其 JSON 粘进报告。

三项以上并列内容优先 `list`。解释用短段落。
Markdown 支持行内代码、公式、代码块和表格；独立或绑定内容使用对应 typed component。
`finding.md` 是正文，不是 JSON 传输；有来源绑定的表格使用 `table`，不把 columns/rows JSON 放进正文。

`reports remove` 仅纠正智能体撰写的普通内容。非空普通容器要求 `--include-children`；章节、special 及任意深度含 special 的子树不能删除。
先移动应保留的普通子组件。删除只改变当前投影，Git 历史仍保留。
`reports export` 验证并在内存渲染后导出 markdown/pdf，不修改源码或物化报告。
PDF 使用冻结客户端随附的签名原生 renderer，UI 不另建渲染器。

写入被拒时读取结构化诊断及 pending sequence，修复同一逻辑组件或批次，携带 `--submission-sequence <sequence>` 重试，不插入另一项修改。
拒绝不改变 HEAD；sequence 是下一目标 generation，不是另一版本计数。
中断后先 `reports show --json` 恢复 `pending_submission.submission_sequence`。
故意放弃尚未发布的 reserved/rejected 修改使用 `reports abandon-pending`；不删除 pending 文件、不直接改 sidecar。
published 修改使用 `reports finalize-pending`。

## 报告中的对象、公式与代码

所有 Markdown 字段（包括标题、列表、表格、caption 和嵌套内容）都遵循：

1. 领域对象用 `[中文短标题](factortester://kind/<percent-encoded-target_ref>)`。
2. 数学变量、关系和公式用 `\(...\)` 或 `\[...\]`。
3. 字段、函数、参数、枚举、可执行语法用行内代码或代码块。
4. 普通文字保持普通文字，不用反引号作强调。

对象身份规则优先于代码格式。智能体决定文字是否指向对象，并从对象所有者复制精确 ref；CLI 只验证显式链接，不从上下文猜测或重写链接。
包含下划线的字面标识符，如 `cs_rank`、`cs_ordinal_rank(mask, ascending)`，使用代码格式。
不在正文或行内代码裸露稳定 ref、Git blob、40/64 位 hash；将完整身份放在链接目标中。
只有真实执行代码或协议输出中的 hash 才可保留在代码块。
身份不明先查询，不能用 alias、短 hash、旧 revision 或行内代码代替。

```markdown
[工业硅](factortester://product/Product%2FFutures%2FCNFutures%2F_products%2FSI.GFE)
[MaxA](factortester://profile/profile%3Amaxa)
[回测任务](factortester://job/job%3A123)
[研究方法](research-methods/references/per-period-fee-attribution.md)
[SgCPS](factortester://factor/factor-family%3Av1%3Aprofile-maxa%3AY3VzdG9tX2ZhY3RvcnMvU2dDUFMucHk%3AU2dDUFM%3Abf7ae6d94a7c35d2280107d332dbaf04c4f50b07%3A1aa9a9908b8f1f034973ebfe5819115e13c16cde)
[冻结运行配置](factortester://run_spec/runspec%3Asha256%3A0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef)
[试验计划](factortester://trial_plan/trial-plan%3Asha256%3A0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef)

```

具体 factor scope 使用冻结 `factor_ref`；家族导航引用不能替代具体因子。
factor 链接绑定提交和 blob，集合还绑定完整成员 manifest hash。
`profile_revision` 是冻结配置，`profile` 是长久身份；用 `client profile revision freeze <profile-id> --json` 获取版本。
产品、合约、连续合约使用确切目录路径与不同 kind。
Job、Evidence、obligation、Claim、Task、requirement 使用当前对象 API 返回的 ID。
RunSpec 为 `runspec:sha256:<run_spec_hash>`；TrialPlan 复制时间线的 `trial-plan:` 身份。
按需通过 `research workspaces timeline` 或 checkpoint 绑定的 `research graphs cycle-object` 查询，不从正文推导。

Work Package 文件用描述性相对 Markdown 链接，不能绝对路径或 `..` 逃逸；发布前确认文件在当前包内且 Git 跟踪。
外部网站用描述性 http/https 链接，不裸写 URL。
不要自证服务器 guard；能力缺失、时序错误、生命周期损坏是平台缺口，不是因子结论。

## Evidence 与研究方法记忆

主 Research Agent 起草并冻结正式 obligation 后，再读取 requirement 子类和复用 Evidence；隔离审阅者可以批评草稿，不能代建正式 obligation。
Job、文件、网页、终端运行本身不是 Evidence。固定关系为：

```text
SourceCapture -> SourceFragment -> Evidence -> EvidenceUse
```

Evidence 绑定精确片段；EvidenceUse 绑定 obligation 与一个或多个 requirement 子类，说明理由并冻结已校验的 scope 和 qualification。
Agent tag 只帮助检索，不改变身份、范围或 Graph 准入。
具体因子引用从真实 Job/RunSpec、可见库或本次原子提交对象复制，不能回退到另一个 commit 寻找缺失因子。

```bash
factortester research evidence guide --json
factortester research evidence guide search --json
factortester research evidence guide capture --json
```

先按产品、提交版本、样本与时间检索，再用 facets/tags。优先复用兼容 Evidence；没有时捕获不可变来源、选择片段、组成 Evidence，再通过 obligation change 绑定。
优先外部 Web/API 证据，再是真实 Terminal/Job capture。
本地文件只有在冻结权威下载及公开获取路径，或绑定 Git 仓库/commit/blob 的实现时才可作为来源。
下载脚本、请求清单和缓存只是 provenance。智能体报告、审计 Markdown、复制命令输出是报告资产，不是主 Evidence。

新增 tag 前列出现有 tag，再 `tag propose`，用返回的 revision-bound token 创建；相似 tag 说明区别。
排除 Evidence 用原生命周期命令，携带 Graph branch、Agent、明确 report parent。
同一 Git 事务移除当前分支 EvidenceUse、重算覆盖并记录裁决；旧链接仍可读，但普通检索不可见，不能重新准入。
恢复检索不恢复已删除的 EvidenceUse。显式审计才用 `search --include-excluded`。

每个 Work Package 创建或复用 Git 跟踪的 `research-methods/SKILL.md`，简短导航到 `research-methods/references/<method-slug>.md`。
不全局注册、不复制进 Profile registry、不作为其他研究权限。
方法记录包括建议者、来源、适用对象与样本、收益、限制/失效条件、采纳状态及相关 typed 引用。
保留拒绝或退休理由，不复制大量输出。每次采用先独立判断，在报告链接方法文件并说明当前理由与范围。
方法记忆不是 Evidence、义务回执或绕过契约的许可，事实判断另引底层片段证据。

## Graph 本地状态与研究循环

Manager 不持有新研究的 Graph 权威状态或决定转移。下载 YAML 后用本地会话和 `research graphs next-local` 评估候选 Edge，即使 Manager 离线也可继续本地研究。
服务器 instance/branch 命令仅用于既有共享状态和远端 Job 的兼容导入，不作为新离线会话权威。
共享报告仍本地编辑；`research reports publication publish` 把无源码投影和对象写本地 outbox，`publication sync` 联机后发送。未共享事实不入 outbox。

```bash
cli-anything-factortester-research --session /path/to/research-session.json doctor --json
factortester research graphs next-local --graph-file /path/to/graph.yaml --current-node entry --json
```

Graph 与本地 session 持有当前节点、候选边、blockers、obligations、report tasks。
只读取当前节点需要的契约和事实；仅当节点返回精确动作时使用有界 `research step inspect`，它不是离线导航别名。
先确认用户尚未明确的重大产品/来源选择；既有授权与委托决定不重复询问。
完成节点必要报告与研究，验证并提交声明的不可变输入，观察真实 Job，捕获证据，再比较当前候选 Edge 并记录理由、补足覆盖、推进。
本地 CLI 校验边、Evidence、报告绑定后记录转移；远端 Job 单独提交，本地只保留不可变引用。
不调用服务器推进新研究 Graph，不复制服务端 `next_actions` 命令。

智能体只提供真实判断：有歧义的 Edge 及理由、未决 Entry assessment、Evidence/Job 选择及理由、`no_material_issue` 或有歧义的能力绑定。
`expected_base_hash`、`obligation_coverage_submission`、`coverage_hash`、`data_availability_request`、冻结 availability hash 等由 CLI 推导。
服务器若要求手抄这些动作或字段，应报告契约缺陷。

## Graph 覆盖与退出契约

- `category_id` 是粗粒度 Verification Obligation 分类。
- `requirement_id` 是其中的版本化 Entry Requirement 子类，按需读取当前活跃子类。
- 分支 obligation 是经 Research Cycle 接受的具体研究状态，选择一个既有 category，无法匹配才用 `other`。
- `from_requirement_refs`、`to_requirement_refs` 是独立、可变的多对多覆盖关系。
- Entry assessment 覆盖每个活跃子类的适用性、兼容 obligation 或事实绑定的非重大判断、resolution route 与 entry effect。
- eligible/limited receipt 必须由实际校验产生；requirement revision/hash、obligations、scope、Research Contract、Methodology、checkpoint 任一变化都要重新验证。
- Report Requirement 是独立输出契约，不等于 Entry Requirement 或 obligation。

外向 Edge 同时验证语义覆盖与报告要求，Edge obligation category 可额外增加要求，不从标题、正文或完成状态推断覆盖。
顺序为 `obligation status` 读 change_contract，`obligation change` 提交，退出阶段再 `edge choose`。
进入实质研究节点不能提前选边，即使只有一个候选。只有契约明确 pure routing 才可自动提前选择。

重大能力阻塞允许立即走声明的 failure/detour Edge；记录阻塞与 obligation，不假装原节点完成。
正常退出报告要求不适用于中断，但 failure Edge 和 detour entry 要求仍适用。
保留一个 resume_node，恢复时经明确 resume Edge 返回后继续。

change 文件必须有非空 `reason_markdown` 与显式 `evidence_use_delta`；每项 EvidenceUse 有精确 Evidence ref、中文短标题、obligation、覆盖 requirement、中文理由、qualification 与 scope snapshot。
真的没有支持变更才用空数组。外层 `research_cycle` 固定 schema 1，绑定返回的 parent_trace_ref；内部提案可以独立为 schema 2，不能混用。
信封错误先修复同一提交，再写报告或选边。
接受的变更与 obligation special 同一 Git 提交，包含变化表、理由、默认收起的当前义务和节点/边来源并集表；不手写第二张覆盖表。

每次变更提交完整多对多 refs。推进时重新验证当前未 superseded Claim、分支准入与每个 EvidenceUse 的范围。
具体因子/产品 EvidenceUse 不能支持未绑定该对象的 obligation。
对象变化先 supersede/rescope Claim 和 obligation，再重建支持；旧 bounded/serviced/discharged 状态不能替代校验。
人类可授权缺失覆盖债务，但过时、错配、无身份的范围不能绕过。

`edge choose` 写富文本理由和路径选择 special；`node advance` 从账本注入 refs 与 hash-bound coverage。
只有已登录人类可授权某节点/checkpoint 容忍缺失覆盖，智能体不能自行开启。
即便获准仍保留债务表，并用返回的 `coverage_remediation --target-chapter-id` 修复源章节。
结构、身份、hash、引用与 special 格式门槛仍强制；指定旧章节不授权移动或替换历史内容。

更新 Graph 版本前显式下载并查看本地拓扑，在 session 记录版本与 continuation；不要求 Manager 制造迁移计划、下一边或报告 parent。
未解决 detour 留在本地 session。

## 方向与反向修饰

TrialPlan 的 `expected_sign` 针对最终解析表达式：+1 预期正 IC，-1 预期负 IC。
有效观察的诊断为 `direction_rate = mean(expected_sign * IC_t > 0)`，零 IC 不命中。
`$Rev` 改变因子值并反转同一收益标签下的 IC；`expected_sign` 只声明假设，不改变值或半衰期输入。
先解析完整 factor_ref，不从 alias 子串推断最终方向。历史 alias 映射只能标为诊断。
结合 signed mean_ic、HAC 不确定性和 raw/$Rev 配对审计，不把方向命中率设为所有首次试验的硬门槛。
半衰期拟合独立于 expected_sign，使用观察基准方向。
运行或 TrialPlan 明确冻结信号可用性、前瞻期、next-bar 执行、费用、容量、保证金、费率模式、universe/mask、样本角色及选择历史。

## 按需使用其他技能

Graph 提供能力描述与 descriptor hash，不直接指定具体技能。
先匹配已加载且指纹有效的技能，再按需发现元数据、获取当前会话实际要求的批准、加载选中技能并记录 `skill-usage record`。
历史使用记录不授权变更后的内容；遵循用户当前授权，不能因技能自行增加无根据的确认门槛。
