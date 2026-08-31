# ADR 108：测试工作台运行可观测性

## 状态

已接受。

## 背景

IC 和回测配置页共享同一个运行批次区域，但旧实现只有选中产品组后才加载，导致初始配置页看不到 RunSpec 和运行控制。相同的全局 IIFE 边界还允许批次/结果模块调用配置或 Job API，却不声明模块依赖。

## 决策

- 设置壳准备好后，每个测试配置页都加载运行批次视图；执行/动作代码仍延迟到用户预览或运行分组。禁用批次动作说明必须先选择产品组。
- 批次和提交组声明 `workbench-ic-controls`，内嵌结果/进度组声明 `jobs`；依赖必须显式，不能依赖偶然的全局变量。
- 内嵌进度条复用 `FTJobProgress.progressView` 和 SSE 流；收到终态事件后只再读取一次 Job detail，再渲染领域结果。
- 复用 `FTICResults.section` 和 `FTBacktestResults.section`，使配置页和 Job detail 使用同一 Highcharts/表格查看器。
- 成功提交响应包含所选 Manager `server_id`；RunSpec/Job 链接和详情请求保留它，远程执行节点可继续定位；生成物读取仍按 storage-server 查询，不继承 worker 端口。

## 后果

配置页在未选择目录前就有稳定的 RunSpec/运行界面，提交测试可显示进度、Job 链接和最终图表/表格。页面只增加轻量视图和进度代码，编译器、源码和提交代码仍按动作延迟加载。一个可见批次面板拥有共享进度流，与 Job detail 的流语义一致。
