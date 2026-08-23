## 职责 {#responsibility}

测试执行链路把编辑器草稿编译成 RunSpec，选择兼容的工作端口，创建 Job 与 Attempt，并登记输入、结果和生成物。

## 数据流 {#data-flow}

注册字段定义默认值和条件；前端只提交适用字段；后端再次规范化并冻结 RunSpec。执行器按需加载所需行列，预回放阶段构建可复用市场数据索引，事件回放处理订单、保证金与策略回调。

## 规范代码入口 {#canonical-paths}

- 测试 authoring 协议：`server/manager/services/test_authoring.py`
- 测试模块：`server/test_modules/`
- Job 路由与投影：`server/manager/http/job_*`、`server/manager/storage/job_index.py`
- Web 测试工作台：`server/manager/web/test-modules/`

## 生命周期与权限 {#lifecycle}

提交身份与服务端口是运行元数据，不进入策略配置 hash。临时上传源码属于 Job 输入，应可在任务详情查看和下载，并与 Job 按同一保留策略清理。
