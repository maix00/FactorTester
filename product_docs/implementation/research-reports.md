## 报告对象与阅读关系 {#responsibility}

Report 保存结构化章节、对象链接和 Evidence 引用；Research 提供协作上下文，一个 Research 可以包含多份 Report。Report 和 Research 可以分别授权，不能把“报告存放在服务器”直接解释成“报告已共享”。

报告树由领域 authoring 服务维护。ReportBranch 是可编辑版本线；已发布内容是供读者读取的只读投影。插入、移动和删除操作由报告树领域逻辑校验父子类型、顺序和循环关系，不由底层文档数据库代替。

## 编辑、提交和发布 {#storage-publishing}

编辑者在草稿中通过稳定 component ID 指定内容位置，提交后获得 revision 或操作收据。发布前校验结构、对象引用、Evidence 绑定和目标可见范围。用户明确发布后，系统生成对应的只读阅读投影；后续编辑应进入新的草稿或分支，不改写已发布版本。

客户端创建的本机报告需要显式发布，已有发布记录按服务能力分批检查更新。服务器 Profile Agent 创建的报告从其授权工作区读取。跨 Manager 的摘要、对象字节和报告正文由各自所有者提供；不可把可见元数据误认为拥有下载权。

## 阅读、同步和并发边界 {#reading-sync}

React 阅读器按需加载章节、对象链接和允许显示的证据摘要，不把整个研究树或全部生成物一次发送给客户端。报告读者能看正文，不代表能下载底层 Artifact；下载权限由 Research 和对象存储端分别校验。

报告同步或发布暂不可达时，应保留待同步状态和原有草稿，不把失败伪装为已发布。发生并发 revision 冲突时，必须保留双方内容并返回冲突；禁止用 last-write-wins 静默覆盖。CouchDB 提供文档 revision、冲突检测和附件存储，报告树操作仍由领域服务负责。

规范代码入口：

- 报告 authoring：`tools/cli/release/research_reporting/authoring/`
- 报告展示服务：`server/services/research_report_presentations.py`
- 本机目录与原生桥：`tools/cli/release/research_reporting/local_catalog.py`、`apple/Sources/Features/Web/LocalResearchBridge.swift`
- Manager 报告与授权：`server/manager/http/research_catalog_routes.py`、`server/manager/services/research_couchdb_publication.py`
- React 报告页面：`web/app/src/pages/research.tsx`、`web/app/src/components/local-research-page.tsx`
