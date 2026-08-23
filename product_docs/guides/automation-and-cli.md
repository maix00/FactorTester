## 何时使用 CLI {#when-to-use-cli}

重复提交、批量检查、研究报告 authoring 和研究图推进适合使用 FactorTester CLI。先通过 `factortester --help` 或具体子命令的 `--help` 读取当前安装版本披露的合同；不要根据旧文档猜测参数，也不要直接改写服务器数据库或报告存储。

## Agent 如何使用平台 {#agent-platform-use}

Agent 应使用已安装的 `cli-anything-factortester-research` 或 `cli-anything-factortester-manager` Skill。Skill 负责说明何时查询、怎样形成证据、哪些操作需要正式对象引用，以及失败后如何安全恢复；CLI 是实际执行和返回结构化结果的唯一入口。

## 保持可追溯 {#keep-traceable}

自动化提交应保留冻结 RunSpec、目标服务、Job 身份和必要输入。终端证据应来自真实 CLI 查询；外部事实优先引用权威链接。本地文件只有在来源、获取方式与完整性都可说明时才适合作为证据。

## 不应自动化什么 {#automation-boundaries}

不要绕过权限、伪造 Evidence、手工修改义务账本或把平台故障解释为研究失败。需要服务器维护权限的动作属于独立维护流程，不因普通研究自动化而获得授权。
