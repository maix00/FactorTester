---
name: cli-anything-factortester-manager
description: 使用 FactorTester Manager CLI 检查和操作已授权的应用、Job、生成物、存储、Research Graph 版本与服务实例；已授权的部署使用现有脚本。
---

# FactorTester Manager CLI

使用已安装的 `factortester-manager` 执行 Click 单次命令。它通过认证后的 Manager API 操作应用，不是主机管理终端。

## 登录与任务边界

Manager CLI 由用户登录。可以使用已有的有效会话，不索取、提取或转移凭据。
未登录时仅暂缓依赖认证的运行时操作，继续代码实现、本地测试，以及独立授权的部署；不得因为 CLI 登录阻塞实现。

```bash
factortester-manager status --json
```

会话绑定完整 Manager URL，存储在系统凭据库中，不能跨服务器复用。
账户身份发生迁移后，由用户使用当前完整用户名重新登录对应 URL，不复制旧 token。
Manager 会话、研究 CLI 会话、浏览器会话和主机凭据不能互相替代。

## 命令导航

首次组合流程前读取对应命令组的 `--help`。需要结构化结果时使用 `--json`。

| 命令 | 用途 |
|---|---|
| `jobs list\|ports\|show` | 查看本机或跨服务器 Job |
| `jobs cancel\|retry\|continue\|approve` | 在明确授权下改变指定 Job |
| `artifacts list <job-id>` | 查看保留的生成物元数据 |
| `artifacts download <job-id> <name> --output <path>` | 使用服务器签发的数据能力下载生成物 |
| `artifacts delete <job-id> --yes` | 在明确授权下删除 Job 生成物 |
| `storage usage` | 查看 Job 与生成物占用 |
| `transfers metrics` | 查看有界传输指标 |
| `devices list\|summary\|revoke` | 查看设备，或在明确授权下撤销公网访问设备 |
| `research-graph versions\|active\|set-default` | 查看或启用 Graph 版本 |
| `services list\|start\|stop\|restart-api\|restart-bundle\|force-stop <port>` | 管理 Manager 所有的服务实例 |
| `server inspect\|access` | 查看身份和非敏感连接声明 |
| `server access check` | 检查声明的凭据是否存在，不读取其值 |
| `server access script download` | 校验 SHA-256 后保存声明脚本，不执行 |
| `server health\|network\|federation\|database` | 查看运行状态及脱敏的网络、联合与数据库状态 |
| `client release` | 构建并发布已授权的客户端版本 |
| `client release-upload` | 向明确指定的 Manager 发布已构建签名包 |

`client release --channel beta` 省略 `--version`、`--build`（或使用 `auto`）时，根据可达服务器 Beta 清单分配下一版本。
不可达服务器会跳过；可达但清单无效则报错。
`release-upload` 使用目标签发的数据能力传输包，目标通过签名、摘要、归档路径及 appcast 校验后才激活。
每个 URL 使用各自会话，离线目标明确报告，留待之后发布。

## 部署与管理入口

已授权的部署有现成脚本就使用脚本，先核对目标、作用范围、备份和回退方式。
本技能不规定具体部署脚本名、主机、端口或 SSH 别名。
用户指定的现有入口优先；`management_access` 为空或过时不能阻塞已确定的脚本入口。
只有声明与现有脚本都无法确定目标或传输方式时才请求补充信息。

CLI 不提供主机重启、容器生命周期、SSH、隧道变更或源码传输命令；这些是另外授权的主机操作。
`kind=wireguard` 只声明服务器间传输能力，不授权管理节点、密钥、路由或隧道生命周期。

## 自动化约定

解析 JSON，不解析供人阅读的说明。非零退出码表示失败，保留结构化错误。
连接声明仅存元数据，不得传入密码、token、私钥或可执行命令。
凭据检查只确认命名环境变量或 Keychain 项是否存在，不输出秘密。
下载的连接脚本应校验后以仅所有者可读写的权限保存。
仅在用户明确允许、且外部凭据工具无法被检查时使用 `--skip-credential-check`。

单次命令之间不依赖 REPL 或项目会话文件。Job、生成物、服务状态由后端持有；凭据由系统凭据库存储。
合并、推送、删除、重启和部署遵循当前用户授权及仓库工作流，命令可用不意味着自动获得权限。

## 常用检查

```bash
factortester-manager server inspect --json
factortester-manager server access --json
factortester-manager jobs list --scope server --limit 20 --json
factortester-manager storage usage --json
factortester-manager server health --json
factortester-manager transfers metrics --json
```
