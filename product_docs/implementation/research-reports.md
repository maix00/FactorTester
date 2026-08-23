## 职责 {#responsibility}

研究报告保存结构化章节、小节、对象链接、证据与要求绑定。它既是用户阅读内容，也是研究图判断已满足要求时使用的正式投影之一。

## 存储与发布 {#storage-publishing}

authoring 后端维护当前可写树与提交事务；发布生成只读投影。SQLite 保存节点、定位与提交收据，避免大量小 JSON 文件成为权威存储。Git 仍记录研究工作包中需要审计的材料。

## 规范代码入口 {#canonical-paths}

- 报告 authoring：`tools/cli/research_report_authoring/`
- 报告服务：`server/services/research_report*`
- Manager 报告读取：`server/manager/http/*research*`
- Web 报告渲染：`server/manager/web/report/`

## 边界 {#boundaries}

研究要求、义务和证据是不同对象；界面显示内容存在，不等于绑定自动成立。普通小节与系统特殊小节共享折叠交互，但系统绑定只能通过正式 authoring 协议变更。
