## 执行职责 {#responsibility}

测试执行把用户草稿转换为可审计任务。字段注册协议声明字段的类型、默认值、适用条件和冻结位置；客户端读取该契约并提交结构化配置。Manager 负责身份和对象授权、配置规范化、RunSpec 冻结、Job 创建、执行计划和结果登记。Nautilus worker 只消费冻结输入，不读取页面草稿、DOM 或本机研究状态。

IC、因子序列和回测可以共享配置框架，但它们的核心输入、执行器和输出 schema 不因此相同。每种测试类型都应明确注册自己的适用字段和结果声明。

## 阶段与责任交接 {#data-flow}

| 阶段 | 负责组件 | 必须保留的事实 |
| --- | --- | --- |
| 字段读取与编辑 | 注册协议、React 页面或 CLI | schema revision、显式输入和候选引用 |
| 预览 | Manager authoring 服务 | 默认值来源、条件推导、生效值、校验错误 |
| 提交 | Manager | 权限结果、RunSpec、请求幂等身份和 Job |
| 计划与派发 | Manager、ExecutionPlan、Celery/RabbitMQ | 节点能力、数据 Bundle 匹配和路由状态 |
| 执行 | 对应测试模块和 Nautilus worker | Attempt 状态、输入版本、日志和执行错误 |
| 结果登记 | Job/Artifact 服务 | schema、内容身份、来源 Job/Attempt 和保留规则 |
| 读取与补充分析 | React 结果页及结果服务 | 请求切片、展示器、父 Job 和附加任务关联 |

预览与执行必须共用配置解析 helper。价格基准、费率、保证金、DMTM、时区和时间边界等运行时解析值要写入被冻结的配置，不能仅显示在 UI 摘要中。

## 验收要求 {#lifecycle}

每个提交都要能按 Job 找到 RunSpec 和 Attempt，再从 Attempt 找到生成物。验收至少确认输入引用、配置 hash、执行节点和数据 Bundle 符合计划；成功任务的已声明 Artifact 可读，失败任务保留错误层级和有效输入。只证明 HTTP 提交成功或 worker 启动，不能证明整条执行链通过。

任务重试产生新的执行历史，旧 RunSpec 和 Attempt 保持可读。附加分析应记录其父 Job 和消耗的 Artifact；相同分析请求按任务契约复用或去重，避免多个页面重复占用执行资源。

规范代码入口：

- 字段与配置规范化：`server/manager/services/test_authoring.py`
- 测试模块：`server/modules/`
- Job 路由与结果投影：`server/manager/http/`、`server/manager/storage/job_index.py`
- Web 测试工作台：`server/manager/web/test-modules/`
