## 职责 {#responsibility}

Web 负责页面渲染；Swift 负责 macOS 窗口、原生标签页和本地权限。Swift 嵌入与浏览器使用同一 Web 页面，避免维护两套报告渲染器。两种客户端可以有不同的入口和本地能力，但共享业务字段注册、对象引用和权限语义。

## 导航流程 {#navigation-flow}

Web Shell 将 URL 分类为稳定路由，再懒加载对应模块。路由只加载当前功能组；具体 tab、字段候选、图表和 overlay 在真正打开时加载，并把页面状态保存在对应标签页会话中。

浏览器中的内部链接交给 Web 标签页管理；Swift 嵌入页面中的对象链接通过桥接交回 Swift，由 Swift 创建或复用自己的标签页。一个功能入口、一个具体对象和一个报告阅读页的去重规则分别处理，不能把所有页面都当成同一个全局 tab。

## 规范代码入口 {#canonical-paths}

- Web 路由分类：`server/manager/web/app/navigation.js`
- Web 路由分派：`server/manager/web/app/route-dispatch.js`
- Web 标签页：`server/manager/web/app/tabs.js`
- Swift 模块与标签页：`apple/Sources/Navigation/`

## 不变量 {#invariants}

“研究”等功能入口复用固定功能标签页；具体 Research、Report、Job 和对象详情可以拥有独立标签页。视觉上选中的标签必须与实际内容路由一致；离开再返回时，当前子 tab、表单草稿和 overlay 状态必须从标签页会话恢复。

父子标签页可以表达研究文件夹和具体研究页面的归属，但禁止 Research 之间形成嵌套。拖拽排序只作用于允许排序的具体标签页，功能入口本身不参与排序；收起侧栏只改变可见宽度，不改变层级和对齐关系。
