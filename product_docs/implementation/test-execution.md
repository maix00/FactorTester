## 职责 {#responsibility}

测试执行链路把编辑器草稿编译成 RunSpec，选择兼容的工作端口，创建 Job 与 Attempt，并登记输入、结果和生成物。字段注册、配置组和策略列表是同一份 authoring 契约的不同作用域，不应由某个前端页面单独拼装第二套字段。

## 数据流 {#data-flow}

注册字段定义类型、默认值、条件、作用域和冻结位置；前端只提交适用字段；后端再次规范化并冻结 RunSpec。预览和真实执行共享同一解析结果，并把显式值、注册默认、条件推导值和省略原因分开记录。

执行器按需加载所需行列，预回放阶段构建可复用市场数据索引，事件回放处理订单、保证金与策略回调。费率、时间边界、价格基准、DMTM、保证金和时区等运行时可变字段必须在实际执行前解析并写入冻结配置；不能只在 UI 摘要中显示一个默认值。

结果生成物按声明登记。首屏只读取结果 tab 所需的摘要或切片；完整序列和原始文件通过存储对象按需读取。附加分析以父 Job 的补充任务记录，避免多个用户点击同一分析时各自重复占用执行资源。

## 规范代码入口 {#canonical-paths}

- 测试 authoring 协议：`server/manager/services/test_authoring.py`
- 测试模块：`server/modules/`
- Job 路由与投影：`server/manager/http/`、`server/manager/storage/job_index.py`
- Web 测试工作台：`server/manager/web/test-modules/`

## 生命周期与权限 {#lifecycle}

提交身份与服务端口是运行元数据，不进入策略配置 hash。临时上传源码属于 Job 输入，应可在任务详情查看和下载，并与 Job 按同一保留策略清理。Job 失败也保留冻结输入和错误层级，方便区分配置、数据、执行和展示故障。

只有提交时生成的 RunSpec 才能进入执行队列；修改页面草稿不会改变运行中的任务。重试生成新的执行历史，旧的 RunSpec、Attempt 和 Artifact 仍可核对。
