## 何时使用 CLI {#when-to-use-cli}

重复提交、批量检查、研究报告 authoring 和任务核对适合使用 TradeResearch CLI。先通过 `traderesearch --help` 或具体子命令的 `--help` 读取当前安装版本披露的合同；不要根据旧文档猜测参数，也不要直接改写服务器数据库、工作区索引或报告存储。

CLI 命令按业务对象组织：因子库、产品库、测试配置/任务、Research/Report/Evidence 和公开文档。命令返回的稳定 ref、schema version、状态和错误码比人类可读的名称更适合脚本判断。

## CLI 登录与用户批准 {#cli-device-approval}

首次 CLI 登录使用 Keycloak OAuth 设备授权。CLI 发起申请并在终端显示验证地址和一次性用户码；用户在浏览器中核对目标 Manager、应用及用户码，登录该 Manager 的 Keycloak 并批准。Agent 可以发起申请和等待结果，批准由用户完成，无需把密码交给 Agent。

Manager 管理命令示例（参数以当前安装入口的帮助为准）：

```bash
traderesearch-manager configure --url https://<manager-host>:7998
traderesearch-manager login --no-browser
traderesearch-manager status --json
```

设备授权中的责任分工如下：

- **CLI** 只申请一次性授权、等待结果，并向配置的目标 Manager 验证身份；未通过验证时不得保存会话。
- **用户** 在浏览器核对 Manager、应用和一次性用户码后作出批准或拒绝。拒绝、超时或过期后，本次申请结束；重新尝试必须生成新用户码。
- **目标 Manager** 验证 Keycloak issuer、subject 和准入权限。浏览器显示批准成功后，仍须等待 CLI 完成验证，并检查登录状态。
- **会话管理** 按 Manager URL 分开保存。切换端点时应重新核对身份和权限；不得复制浏览器 Cookie、密码或其他 Manager 的令牌。使用结束后执行 `traderesearch-manager logout`，撤销本 CLI 会话的刷新凭据并清除本地记录。

一次性验收应使用隔离 CLI 状态目录，记录不含凭据的状态摘要。退出该 CLI 会话不会撤销其他客户端各自持有的会话。

设备授权登录与设备自动登录白名单是两件事：批准本轮 OAuth 登录不等于注册计算节点、授予下载角色或批准业务写入；具体对象操作仍由 Keycloak 当前授权决定。

旧客户端可能只支持复用已有原生会话。若登录发现入口不存在、被转到合规页，或 Keycloak 客户端尚未配置，应报告该部署的能力缺口；若 TLS 信任失败，应核对目标部署的证书信任配置。不得跳过证书或身份校验，也不得为兼容旧技能而改变网络拓扑。各组件记录实际版本并按能力合同验收，技能说明以项目当前文档为准。

## Agent 如何使用平台 {#agent-platform-use}

Agent 应使用已安装的 `cli-anything-traderesearch-research` 或 `cli-anything-traderesearch-manager` Skill。Skill 负责说明何时查询、怎样形成证据、哪些操作需要正式对象引用，以及失败后如何安全恢复；CLI 是实际执行和返回结构化结果的唯一入口。

## 保持可追溯 {#keep-traceable}

自动化提交应保留规范化 preview、冻结 RunSpec、目标服务、Job/Attempt 身份和必要输入。对同一逻辑操作使用请求幂等标识或稳定对象引用，重试查询可以安全重复，提交和删除则必须根据命令契约确认是否幂等。

终端证据应来自真实 CLI 查询；外部事实优先引用权威链接。本地文件只有在来源、获取方式、版本和完整性都可说明时才适合作为证据。脚本不应通过 `grep` 扫描服务器父目录来寻找因子、产品组或报告。

## 不应自动化什么 {#automation-boundaries}

不要绕过权限、伪造 Evidence、手工修改义务账本或把平台故障解释为研究失败。需要服务器维护权限的动作属于独立维护流程，不因普通研究自动化而获得授权。

遇到 schema、权限或数据能力错误时，应保存错误摘要和原始请求上下文，修复公共注册/解析 helper 后重新提交新的 revision；不要用另一个客户端私自补字段或修改历史 Job。

## Agent 操作顺序 {#agent-sequence}

Agent 先读取当前业务入口和适用对象，再查询字段/候选，构造结构化草稿，执行 validate，最后由用户或授权流程 apply/submit。页面辅助草稿只是页面状态的可追溯载体，不是绕过后端 RunSpec 校验的通道。
