## 职责与系统位置 {#responsibility}

Manager 提供统一 Web Shell、登录会话、公开目录与任务聚合；工作端口执行测试和研究图操作；Swift 客户端承载本地资源访问与原生标签页；用户工作区保存本地因子、研究包和可追溯输入。

## 主要流程 {#main-flow}

浏览器或 Swift 打开 Manager 页面，Manager 根据注册模块提供界面与公共数据。提交测试时，Manager 选择工作端口并记录路由，工作端口执行冻结 RunSpec，结果再由 Manager 聚合展示。

## 规范代码入口 {#canonical-paths}

- Manager 组合与状态：`server/manager/runtime.py`
- HTTP 路由：`server/manager/http/`
- Web Shell：`server/manager/web/app/`
- 测试定义与执行：`server/services/`、`server/test_modules/`
- Swift 导航与嵌入：`apple/Sources/Navigation/`

这些路径用于定位职责，不代表整个目录都属于公开接口。

## 边界与扩展点 {#boundaries}

服务器不推测客户端本地有哪些数据源。模块、字段、生成物和展示器应通过后端注册协议扩展；前端不硬编码某个本地数据源或测试字段。
