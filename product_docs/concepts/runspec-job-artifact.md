## 可编辑配置与 RunSpec {#configuration-runspec}

可编辑运行配置可以进入模板并继续修改。RunSpec 是提交时形成的不可变快照，包含解析后的默认值、显式覆盖、研究对象和执行所需输入引用。

## Job 与 Attempt {#job-attempt}

Job 是用户可见的任务身份；Attempt 是该任务的一次实际执行。重试可以产生新 Attempt，但不会悄悄改写原 RunSpec。

## Artifact {#artifact}

Artifact 是结构化统计、序列、图表、日志或其他输出。展示器依据生成物种类选择表格、SVG 或交互图，而不是仅依据文件扩展名猜测。
