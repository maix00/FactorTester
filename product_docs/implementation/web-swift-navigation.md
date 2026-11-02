## 职责 {#responsibility}

React 负责页面、设置、翻译和报告渲染；Swift 负责原生窗口、设备密钥、连接选择与本机资源桥。桌面与浏览器使用同一 /app，不另维护一套 Swift 业务表单。客户端能力可以不同，但业务字段、对象引用和权限语义共用。

## 导航流程 {#navigation-flow}

桌面 Shell 由公共页面注册表创建 Dockview 面板。功能入口复用已有面板，具体对象可作为独立面板或详情 overlay 打开。页面状态与实例绑定，非活动面板保留挂载但隐藏，重新选择时恢复其筛选和草稿。

移动端使用 Ionic Header、返回栈和功能入口；通知中心与助手保留在 Header。
共享表格及图表的放大模式与普通页面导航分开，设备方向由设置控制。
Manager 切换只向桌面/移动原生宿主开放；普通网页使用当前站点，不显示本机连接设置。

## 规范代码入口 {#canonical-paths}

- 公共页面注册：`web/app/src/registry.ts`
- 桌面工作区：`web/app/src/desktop-shell.tsx`
- 移动端导航：`web/app/src/mobile-shell.tsx`
- 原生连接与研究桥：`apple/Sources/Features/Web/`

## 不变量 {#invariants}

“研究”等功能入口复用固定功能标签页；具体 Research、Report、Job 和对象详情可以拥有独立标签页。视觉上选中的标签必须与实际内容路由一致；离开再返回时，当前子 tab、表单草稿和 overlay 状态必须从标签页会话恢复。

父子标签页可以表达研究文件夹和具体研究页面的归属，但禁止 Research 之间形成嵌套。拖拽排序只作用于允许排序的具体标签页，功能入口本身不参与排序；收起侧栏只改变可见宽度，不改变层级和对齐关系。
