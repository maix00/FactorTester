## 职责 {#responsibility}

Web 负责页面渲染；Swift 负责 macOS 窗口、原生标签页和本地权限。Swift 嵌入与浏览器使用同一 Web 页面，避免维护两套报告或研究图渲染器。

## 导航流程 {#navigation-flow}

Web Shell 将 URL 分类为稳定路由，再懒加载对应模块。浏览器中的内部链接交给 Web 标签页管理；Swift 嵌入页面中的对象链接通过桥接交回 Swift，由 Swift 创建或复用自己的标签页。

## 规范代码入口 {#canonical-paths}

- Web 路由分类：`server/manager/web/app/navigation.js`
- Web 路由分派：`server/manager/web/app/route-dispatch.js`
- Web 标签页：`server/manager/web/app/tabs.js`
- Swift 模块与标签页：`apple/Sources/Navigation/`

## 不变量 {#invariants}

“研究”等功能入口复用固定功能标签页；具体报告、Job 和对象详情可以拥有独立标签页。视觉上选中的标签必须与实际内容路由一致。
