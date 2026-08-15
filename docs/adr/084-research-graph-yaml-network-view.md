# ADR-084：研究图的 YAML 发布下载与网络节点视图

## 状态

已接受

## 背景

研究图版本已经由 Manager 的 SQLite `research_graph_versions` 保存，并由现有协议校验和内容 hash 保证不可变。原 Web 页面把节点和边分别列成卡片，无法表达图的拓扑关系；同时，用户需要下载某个精确版本作为审阅、备份和离线处理材料。

## 决策

1. SQLite 中经过协议校验的 canonical Graph JSON 仍是运行时唯一权威。YAML 是从指定的 `graph_id/version` 即时生成的只读发布表示，不建立第二份可编辑版本源。
2. YAML 导出先移除 SQLite 行级的 `created_by`、`created_at` 元数据，再重新执行同一 Graph 校验；下载文件不接受客户端提交的 Graph 内容。文件名包含 graph id、版本号和 content hash 前缀。
3. `GET /api/research-graphs/<graph_id>/versions/<version>/yaml` 是只读下载端点，返回 `application/yaml`、ETag、不可变缓存策略和版本/hash 响应头。公共 Graph 网关只放行该端点以及既有的版本列表和 Active 读取端点。
4. 研究图选项卡使用随项目发布的 Cytoscape.js（MIT）在 Canvas 上绘制可缩放、拖动、选择和重新布局的网络图。节点/边语义在右侧详情面板显示；这不是节点列表，也不把研究图强制排成流程图。Web 与嵌入 Swift 的页面共用该渲染模块。
5. Cytoscape 资源不从 CDN 加载；版本、许可证、文件大小和 SHA-256 保存在 `static/vendor/cytoscape/` 的许可及校验清单中，并由静态资源 manifest 声明。
6. 研究图的语言版本是 canonical Graph 之外的 immutable presentation overlay。`research_graph_presentations` 以 `graph_id + version + locale + translation_revision` 为身份，并保存独立的 `translation_hash`；翻译文本不能写回 Graph JSON，也不能改变 Graph `content_hash`。
7. Presentation 必须通过服务端合约校验：它必须完整覆盖该 Graph 版本的 node/edge ID，且自身的 `content_hash`、版本和 locale 必须与目标 Graph 匹配。只有超级管理员可以发布新的语言版本/修订；重复内容按 hash 幂等，内容变化产生新的 translation revision。
8. 版本列表、Active 读取和 YAML 下载接受 `locale` 查询参数。没有已发布 presentation 时，API 明确返回 `presentation_status=missing`；语言 YAML 不伪装成 canonical Graph，而下载为包含 `graph` 与 `presentation` 的 `factor-tester.research-graph-presentation.v1` bundle。未带 locale 的旧 YAML 接口继续返回原 canonical Graph，保持兼容。

## 影响

- 旧 Graph 版本、Active 指针、分支固定版本和 hash 语义不改变。
- YAML 下载可用于外部审阅和恢复材料，但重新导入仍必须经过现有 Graph 注册/校验流程。
- 小型研究图使用内置 CoSE 力导向布局；未来若图规模显著增加，应单独评估 WebGL 渲染和布局性能，不在本决策中隐式引入新 CDN 或图形依赖。
- 语言切换只切换服务端返回的 presentation；前端不维护 node/edge 翻译表。这样 Swift 嵌入页面、Web 页面和 YAML 下载使用同一份服务器发布文本，翻译更新不会伪造新的研究语义版本。
