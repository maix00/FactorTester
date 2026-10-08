## 何时使用 CLI {#when-to-use-cli}

重复提交、批量检查、研究报告 authoring 和任务核对适合使用 FactorTester CLI。先通过 `factortester --help` 或具体子命令的 `--help` 读取当前安装版本披露的合同；不要根据旧文档猜测参数，也不要直接改写服务器数据库、工作区索引或报告存储。

CLI 命令按业务对象组织：因子库、产品库、测试配置/任务、Research/Report/Evidence 和公开文档。命令返回的稳定 ref、schema version、状态和错误码比人类可读的名称更适合脚本判断。

## Agent 如何使用平台 {#agent-platform-use}

Agent 应使用已安装的 `cli-anything-factortester-research` 或 `cli-anything-factortester-manager` Skill。Skill 负责说明何时查询、怎样形成证据、哪些操作需要正式对象引用，以及失败后如何安全恢复；CLI 是实际执行和返回结构化结果的唯一入口。

## 保持可追溯 {#keep-traceable}

自动化提交应保留规范化 preview、冻结 RunSpec、目标服务、Job/Attempt 身份和必要输入。对同一逻辑操作使用请求幂等标识或稳定对象引用，重试查询可以安全重复，提交和删除则必须根据命令契约确认是否幂等。

终端证据应来自真实 CLI 查询；外部事实优先引用权威链接。本地文件只有在来源、获取方式、版本和完整性都可说明时才适合作为证据。脚本不应通过 `grep` 扫描服务器父目录来寻找因子、产品组或报告。

## 不应自动化什么 {#automation-boundaries}

不要绕过权限、伪造 Evidence、手工修改义务账本或把平台故障解释为研究失败。需要服务器维护权限的动作属于独立维护流程，不因普通研究自动化而获得授权。

遇到 schema、权限或数据能力错误时，应保存错误摘要和原始请求上下文，修复公共注册/解析 helper 后重新提交新的 revision；不要用另一个客户端私自补字段或修改历史 Job。

## Agent 操作顺序 {#agent-sequence}

Agent 先读取当前业务入口和适用对象，再查询字段/候选，构造结构化草稿，执行 validate，最后由用户或授权流程 apply/submit。页面辅助草稿只是页面状态的可追溯载体，不是绕过后端 RunSpec 校验的通道。
