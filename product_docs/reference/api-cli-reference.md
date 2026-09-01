## 使用原则 {#usage-principles}

本页只列稳定的业务入口和典型用途。命令帮助和接口返回的 schema 才是参数的最终契约；安装版本可能增加字段，但不应依赖未登记的内部路由、页面抓取或数据库文件。

当前统一边界是：FactorTester CLI 面向业务对象，Manager API 面向客户端和服务端之间的业务域。旧的 custom-factors、catalog 或仅供页面内部使用的路径不是公开集成入口，即使某个部署暂时仍能响应，也不应写入 Agent Skill 或脚本。

## CLI 总览 {#cli-overview}

先检查当前版本：

```text
factortester --help
factortester <domain> --help
```

常用业务域如下：

| 业务域 | 典型命令 | 用途 |
| --- | --- | --- |
| 因子库 | `factortester factor-library families`、`factors`、`factor-sets` | 查询因子家族、具体因子和因子集合 |
| 因子工作区 | `factortester factor-library workspace user download`、`upload` | 在用户工作区与数据库因子库之间同步；上传前应先下载并检查冲突 |
| 产品库 | `factortester product-library list`、`info`、`availability`、`capabilities` | 查询产品、数据源、产品组、分类和字段能力 |
| 测试配置 | `factortester workspace ...`、`run preview` | 编辑可复用配置、预览规范化结果 |
| 测试提交 | `factortester run submit` | 冻结 RunSpec 并创建 Job |
| 任务 | `factortester job list`、`status`、`config`、`result`、`artifact`、`cancel` | 管理任务、查看冻结输入和结果 |
| 研究 | `factortester research ...` | 管理 Research、Workspace、Report、Evidence 和研究图 |

需要机器读取时使用 `--json`；脚本应检查 `success`、错误码和 schema 版本，而不是解析人类可读的行。

## 因子库与产品库 {#factor-product-library}

因子库的核心读取入口：

```text
factortester factor-library families --scope all --json
factortester factor-library factors --scope all --json
factortester factor-library factor-sets --scope all --json
factortester factor-library describe <family-or-factor-ref> --json
```

产品库的核心读取入口：

```text
factortester product-library list --json
factortester product-library sources list --json
factortester product-library groups list --json
factortester product-library categories list --json
factortester product-library availability --json
factortester product-library capabilities --json
```

查询结果中的 ref、owner、revision、source kind 和权限提示必须原样保存到后续 RunSpec 或研究证据中。显示名称只能帮助用户识别，不能替代稳定引用。

## 配置、提交与任务 {#configuration-run-job}

典型流程：

```text
factortester workspace create --json
factortester workspace use <workspace-id> --json
factortester run preview --json
factortester run submit --json
factortester job status <job-id> --json
factortester job config <job-id> --json
factortester job artifacts <job-id> --json
```

`run preview` 展示规范化后的候选配置；只有 `run submit` 才形成不可变 RunSpec。任务详情中的配置、Attempt 和 Artifact 应使用 Job 返回的身份读取，不能以当前工作区后来修改的内容代替。

结果查询应优先获取目录和摘要，再按用户打开的表格、图表或分析页获取对应生成物。大序列不应在首屏一次性下载。

## 研究与报告 {#research-commands}

研究命令的入口按对象分组：

```text
factortester research --help
factortester research reports --help
factortester research workspaces --help
factortester research evidence --help
factortester research graphs --help
```

报告写入应使用稳定的 Research、Workspace、Report 和 component ID。若需要客户端下载，先读取访问范围和资源清单，再下载明确授权的文件；不要把报告正文中的本地路径当作下载地址。

## 公开技术文档 API {#technical-docs-api}

技术文档是公开的 Manager 内容，不需要账户会话：

```text
GET /docs
GET /api/docs/index
GET /api/docs/pages/<slug>
GET /api/docs/test-fields?client=web&page=1&page_size=20
```

返回的 revision 是内容目录版本。客户端可以缓存 index，并在用户打开具体页面时懒加载 page；字段参考接口另外按当前页返回注册字段，`client` 可取 `web`、`swift` 或 `cli`。页面不存在或文档编译失败应显示明确错误，不应回退到旧业务页面。

## 失败与兼容 {#failure-compatibility}

401/403 表示身份或权限不足，404 表示对象或路由不存在，409 通常表示 revision、并发或冲突，422 表示业务 schema 无法接受，503 表示依赖暂不可用。Agent 必须保留原始错误摘要和 request/job 身份，并按帮助文本重新确认参数。

不要使用下列方式“修复”失败：扫描服务器目录猜对象、直接调用未登记内部路径、把空列表当成权限通过、在客户端补写服务端默认值、或把一次重试当成新的研究结论。
