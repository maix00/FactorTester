## 系统职责与边界 {#responsibility}

Manager 提供 /app、认证会话、业务 API、对象目录、任务状态和结果投影。它是 Job、RunSpec 和业务授权的服务端权威，不承载所有大体积行情数据或执行器内存状态。

执行节点通过 Celery/RabbitMQ 接收经授权的冻结任务，由 Nautilus 完成事件驱动回测或已配置的交易执行。Data I/O 在 Bundle 所在主机读取所需数据，并提供有界 Arrow 批次和缓存。Alpha 因子引擎为表达式和策略提供共用计算能力；Manager、worker 和数据服务通过明确接口协作，不共享进程内 Python 对象。

电脑、网页、移动端和 CLI 是同一业务服务的不同客户端。Swift 宿主提供设备密钥、窗口和本机资源等窄桥接能力，不另建一套业务字段或授权规则。

## 一次任务的执行顺序 {#main-flow}

1. 客户端读取字段和对象候选，并提交待编辑配置。
2. Manager 按用户权限和当前注册契约规范化配置，返回预览。
3. 用户提交后，Manager 冻结 RunSpec，创建 Job/Attempt 和执行计划。
4. 执行计划匹配可用节点、服务版本和所需数据 Bundle；不满足时停止并报告原因。
5. 队列向执行节点投递任务。worker 按冻结引用读取数据和因子，产生结果。
6. Manager 登记状态和 Artifact 引用；客户端按需读取结果摘要、切片和明细。

执行过程和职责交接见“研究任务运行流程”。执行节点离线不改变已经持久化的 Job 或 Artifact 身份。

## 代码定位与扩展边界 {#canonical-paths}

- Manager 组合与状态：`server/manager/runtime.py`
- HTTP 路由：`server/manager/http/`
- React Web Shell：`web/app/src/desktop-shell.tsx`、`web/app/src/mobile-shell.tsx`
- 测试定义与执行：`server/services/`、`server/modules/`
- Swift 宿主与桥接：`apple/Sources/Features/Web/`、`apple/Sources/Navigation/`

新增模块应声明权威来源、对象引用、权限、生命周期、版本兼容和失败行为。服务器不扫描客户端文件系统以猜测本地数据源；客户端不自行发明公共字段语义。
