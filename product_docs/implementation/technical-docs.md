## 公开文档的组成 {#composition}

公开内容的源目录是 `product_docs/`。清单把每页的 slug、中文标题、摘要、文档类型、关联页和可选的代码定位登记在一起；清单之外的 Markdown 不会因为文件存在就自动公开。

## 启动时编译 {#startup-compile}

`server/manager/services/technical_docs.py` 在 Manager 启动时读取清单，检查 schema、唯一 slug、source 是否仍在公开目录、实现页的代码路径是否存在、标题是否有稳定 anchor、内链是否指向已登记页面，然后一次性渲染页面、目录、搜索文本和 revision。

这项编译是启动门禁：如果文档引用了已删除的实现，Manager 应失败并给出明确错误，而不是带着过时目录继续服务。运行期间的读取只返回内存中的深拷贝，源文件变化不会在请求中途改变页面。

## HTTP 边界 {#http-boundary}

`server/manager/http/technical_docs_routes.py` 提供文档 shell、目录和单页读取；稳定入口为：

```text
GET /docs
GET /api/docs/index
GET /api/docs/pages/<slug>
```

`server/manager/http/request_security.py` 将这些只读文档入口明确标为公开，同时不改变任务、工作区、因子源码和研究文件的业务访问控制。公开只表示任何用户可以读经过编译的技术说明，不表示可以读取服务器磁盘或调用未登记 API。

## 渲染安全 {#render-safety}

Markdown 使用受限 CommonMark 配置；HTML、脚本、内嵌图片、iframe 和不安全 URL 不进入页面。实现页的 inline code 还要与清单声明的 canonical_paths 一致，避免“文档说的是 A、代码其实在 B”的静默漂移。

## 前端懒加载 {#lazy-reader}

`server/manager/web/docs/source.js` 负责目录和正文的缓存读取，`server/manager/web/docs/reader.js` 只在文档入口或具体页面打开时请求相应数据；`server/manager/web/styles/docs.css` 提供桌面目录、正文和移动端折叠布局。

目录先行的设计让首屏只下载页面元数据和搜索索引，长正文按需读取；字段参考页在打开后才加载当前表格页，筛选或换页只请求新的窗口，不预取整张表。它不是安全边界，真正的公开范围仍由 Manager 路由和编译清单决定。

字段参考页使用 `tools/testers/settings/registry.py` 和
`tools/testers/settings/applications.py` 中的同一测试设置注册协议生成 projection；
`server/manager/web/docs/field-catalog.js` 只负责读取当前页窗口并呈现表格。它展示
业务字段的类型、默认值、作用域、所在 tab 和客户端适用性；Web、Swift、CLI 只是
筛选视图。API schema、结果 Artifact schema 和内部 UI 状态不复制到这张表，而
分别由接口参考、结果文档和实现说明承载。

文档正文和字段目录都避免把大对象一次性塞进首屏：正文按页面读取，字段按服务端页窗口读取，完整字段规则只随当前返回页携带。缓存必须以文档 revision 和字段客户端投影为键，不能用一个客户端的结果冒充另一个客户端。

## 发布与回归 {#release-verification}

修改清单或正文后，至少运行文档编译、Markdown 安全、公开匿名访问和容器打包测试。验收重点是：默认页可打开、深链接回到同一 shell、未知页面返回 404、非法 Markdown 在启动阶段失败、公共文档不要求会话、业务私有入口仍然需要原有权限。
