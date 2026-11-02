## 职责与系统位置 {#responsibility}

Manager 提供 React /app、登录会话、目录与任务聚合。独立计算节点通过 Celery/RabbitMQ 执行冻结任务，数据 I/O 服务在 Bundle 所在主机读取并提供有界数据批次。Nautilus 承担回测与执行，Alpha 因子引擎提供共用因子计算；二者通过 bridge 协作。Swift 客户端是共享 Web 页面的原生宿主，提供本机研究、设备和 Manager 连接等窄桥接能力。

字段、对象和结果的职责也分开：测试注册协议声明可编辑/可冻结字段，目录服务提供稳定对象引用，执行器消费冻结 RunSpec，结果服务只读取已登记生成物。客户端可以有不同呈现方式，但不能各自发明字段语义。

## 主要流程 {#main-flow}

浏览器、桌面客户端和移动端打开共用 React 页面。桌面使用 Dockview 工作区，移动端使用 Ionic 导航与 Header；字段候选和结果查看器按需读取。保留挂载的非活动页面隐藏内容并保留草稿，避免其他页控件叠到当前页。

测试配置页面编辑包含 RunSpec 的 ExecutionPlan。自动或手动选择执行位置后，配置 JSON、页面和冻结计划保持一致；Manager 按节点能力、权限与数据可达性核验路由，再派发任务。结果和生成物通过对象引用聚合展示，计算节点离线不改变已持久化结果的身份。

## 规范代码入口 {#canonical-paths}

- Manager 组合与状态：`server/manager/runtime.py`
- HTTP 路由：`server/manager/http/`
- React Web Shell：`web/app/src/desktop-shell.tsx`、`web/app/src/mobile-shell.tsx`
- 测试定义与执行：`server/services/`、`server/modules/`
- Swift 宿主与桥：`apple/Sources/Features/Web/`、`apple/Sources/Navigation/`

这些路径用于定位职责，不代表整个目录都属于公开接口。

## 边界与扩展点 {#boundaries}

服务器不推测客户端本地有哪些数据源。模块、字段、生成物和展示器应通过后端注册协议扩展；前端不硬编码某个本地数据源或测试字段。新增客户端时复用同一字段契约，只增加该客户端的投影能力声明。

扩展必须同时说明所有权、权限、生命周期、版本和失败行为。只有影响用户提交或结果追溯的稳定业务契约才进入公开参考文档；进程内部缓存、DOM 状态和实现细节留在实现说明，不生成另一张公共字段表。
