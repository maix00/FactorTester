# ADR-084：研究图的 YAML 发布下载与网络节点视图

> 已被 ADR-156 取代。Graph YAML/catalog/network view 属于退役设施，历史 Graph 内容无需保留；本文仅作为实现历史记录。

## 状态

已接受

## 背景

研究图版本已经由 Manager 的 SQLite `research_graph_versions` 保存，并由现有协议校验和内容 hash 保证不可变。原 Web 页面把节点和边分别列成卡片，无法表达图的拓扑关系；同时，用户需要下载某个精确版本作为审阅、备份和离线处理材料。

## 决策

1. SQLite 中经过协议校验的 canonical Graph JSON 仍是运行时唯一权威。YAML 是从指定的 `graph_id/version` 即时生成的只读发布表示，不建立第二份可编辑版本源。
2. YAML 导出先移除 SQLite 行级的 `created_by`、`created_at` 元数据，再重新执行同一 Graph 校验；下载文件不接受客户端提交的 Graph 内容。canonical 文件名只包含 graph id 与版本号；canonical Graph 自身仍保留协议要求的 `content_hash`，但不把 hash 重复塞进文件名。
3. `GET /api/catalog/research-graphs/<graph_id>/versions/<version>/yaml` 是只读下载端点，返回 `application/yaml`、ETag、不可变缓存策略和版本/hash 响应头。公共 Graph 网关只放行该端点以及既有的版本列表和 Active 读取端点。
4. 研究图选项卡使用随项目发布的 Cytoscape.js（MIT）在 Canvas 上绘制可缩放、拖动、选择和重新布局的网络图。节点/边语义在右侧详情面板显示；这不是节点列表，也不把研究图强制排成流程图。Web 与嵌入 Swift 的页面共用该渲染模块。
5. Cytoscape 资源不从 CDN 加载；版本、许可证、文件大小和 SHA-256 保存在 `static/vendor/cytoscape/` 的许可及校验清单中，并由静态资源 manifest 声明。
6. 研究图的语言版本是 canonical Graph 之外的 display overlay。`research_graph_presentations` 每个 `graph_id + version + locale` 只保存当前文本，不建立翻译 revision/hash 历史；翻译文本不能写回 Graph JSON，也不能改变 Graph `content_hash`。节点、边和能力文本允许是部分覆盖，未覆盖处回退到 canonical Graph。
7. Presentation 仍必须通过服务端合约校验 Graph 身份、版本、locale 和文本结构；只有 canonical Graph 的 `content_hash` 是执行语义身份。升级、激活、回滚与 continuation 继续使用现有 Graph 生命周期与 hash，不新增翻译 hash 门禁。
8. 版本列表、Active 读取和 YAML 下载接受 `locale` 查询参数。没有已发布 presentation 时，API 明确返回 `presentation_status=missing`；语言 YAML 不伪装成 canonical Graph，而下载为包含 `graph` 与 `presentation` 的 `factor-tester.research-graph-presentation.v1` bundle。未带 locale 的旧 YAML 接口继续返回原 canonical Graph，保持兼容。

## 影响

- 旧 Graph 版本、Active 指针、分支固定版本和 hash 语义不改变。
- YAML 下载可用于外部审阅和恢复材料，但重新导入仍必须经过现有 Graph 注册/校验流程。
- 小型研究图使用内置 CoSE 力导向布局；未来若图规模显著增加，应单独评估 WebGL 渲染和布局性能，不在本决策中隐式引入新 CDN 或图形依赖。
- 语言切换只切换服务端返回的 presentation；前端不维护 node/edge 翻译表。这样 Swift 嵌入页面、Web 页面和 YAML 下载使用同一份服务器发布文本，翻译更新不会伪造新的研究语义版本。
- 用户 YAML 不是已发布 Graph 版本：Web 明确上传到当前 Manager 的本地 SQLite，用户可下载、删除和选择默认文件；Swift 只把 YAML 导入 `Documents/FactorTester/research-graphs`，不自动上传，也不记录语言字段。用户文件只有一次结构校验，不参与 canonical Graph 的发布/激活/回滚治理。
- canonical Graph 与 server-managed presentations 仍以保存它们的 Manager 为来源。现有联邦同步 worker 只同步任务控制事件；本 ADR 不把研究图版本或 presentation 误当成已经自动复制到所有 Manager。需要读取其他服务器的 Graph 时，必须通过已认证的目标节点路由读取；需要让另一台服务器本地拥有该版本，则应走明确的发布/导入流程，并以 `graph_id + version + content_hash` 做幂等校验。presentation 以 `graph_id + version + locale` 对齐，不能改变 canonical Graph 身份。用户文件标记为 `sync_scope=manager-local`，不通过 Manager 间联邦代理隐式复制；用户在另一台服务器上需要该文件时，必须再次显式上传，默认选择也不会跨服务器传播，避免跨服务器泄露或产生不一致的默认文件。
