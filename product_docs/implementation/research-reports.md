## 职责 {#responsibility}

研究报告保存结构化章节、小节、对象链接与证据引用。Research 是协作对象，一个 Research 可以包含多份 Report；Report 不是 Research 的同义词。

## 存储与发布 {#storage-publishing}

authoring 后端维护当前可写树与提交事务；发布生成只读投影。SQLite 保存节点、定位与提交收据，避免大量小 JSON 文件成为权威存储。Git 记录报告工作区中需要审计的材料。

研究报告列表属于研究入口或具体 Research 页面；某份报告打开后才建立去重的独立标签页，并挂在对应 Research 之下。报告页面应恢复阅读位置和当前章节，但不能借此把 Research 嵌套到另一个 Research。

客户端创建的研究内容与服务器 Profile Agent 创建的内容共享同一结构化 authoring 和发布协议。共享/公开时只发布允许的投影：报告可读不等于文件可下载，Research 的共享范围才决定关联 Evidence/Artifact 的下载范围。

## 规范代码入口 {#canonical-paths}

- 报告 authoring：`tools/cli/release/research_reporting/authoring/`
- 报告展示服务：`server/services/research_report_presentations.py`
- Manager 报告读取：`server/manager/http/server_research_routes.py`、`server/manager/http/client_research_routes.py`、`server/manager/http/public_research_routes.py`
- Web 报告渲染：`server/manager/web/report/`

## 边界 {#boundaries}

研究要求、义务和证据是不同对象；界面显示内容存在，不等于绑定自动成立。普通小节与系统特殊小节共享折叠交互，但系统绑定只能通过正式 authoring 协议变更。

证据可以跨 Research 复用，但证据所有权、报告可见性、Research 共享和文件下载是独立权限判断。阅读器按需加载章节和对象传输，不把完整研究树、所有生成物或服务器目录一次性发给客户端。
