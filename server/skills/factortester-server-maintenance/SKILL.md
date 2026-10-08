---
name: factortester-server-maintenance
description: 使用 FactorTester Manager CLI 检查和操作已授权的应用运行状态，并通过现有部署脚本处理明确授权的服务器维护。适用于具体维护任务，不授予额外后端权限。
---

# FactorTester 服务器维护

使用 `factortester-manager` 的 Click 单次命令访问 Manager API。它是应用客户端，不是主机管理终端。

## 登录与实现

Manager CLI 由用户登录。不得索取、提取或转移登录凭据。可以使用已有的有效登录；未登录时，仅暂缓必须认证的运行时操作，继续已授权的代码实现、本地测试，以及通过现有脚本执行的独立授权部署。不得因为 CLI 登录阻塞实现。

```bash
factortester-manager status --json
```

会话按完整 Manager URL 存放在系统凭据库中，不得跨服务器 URL 复用。命令语法通过对应命令组的 `--help` 读取。

## 操作边界

| 操作 | 所需授权与入口 |
|---|---|
| 本地源码检查、编辑、测试、提交 | 遵循仓库任务授权及 Git/worktree 工作流 |
| 应用运行状态读取或修改 | 已授权的 Manager 主体，通过 Manager CLI |
| 主机、容器、隧道、发布传输 | 明确的部署授权；有现成部署脚本就使用脚本 |
| 合并、推送、发布 | 遵循用户明确授权及仓库发布规则 |

Manager token、浏览器会话与主机凭据各自独立，不得互相替代，不输出其内容。

## 确认目标与入口

可通过以下命令读取服务器身份及非敏感连接声明：

```bash
factortester-manager server inspect --json
factortester-manager server access --json
```

`server`、`factor_tester`、`management_access` 是运行时声明。声明可包含方式、配置标识、端点、端口及能力，不应包含秘密或可执行命令。

有现成部署脚本就使用脚本，先检查其目标配置和作用范围。用户指定的现有入口优先；`management_access` 为空或过时不应阻塞该入口。只有声明和现有脚本都不能确定目标与传输方式时才请求补充信息，不猜测备用地址或通道。本技能不规定具体部署脚本名、主机、端口或 SSH 别名。

`kind=wireguard` 仅声明服务器间传输能力，不授权创建节点、更改路由或修改密钥。隧道握手成功也不代表应用正常。

## 维护流程

1. 阅读仓库 `server/AGENTS.md` 和与本次任务相关的说明。
2. 对已有维护案例使用其简要恢复信息；不要读取无关目录。
3. 沿实际请求或调度路径复现具体异常，区分 `confirmed_reliable`、`research_input_issue`、`backend_change_proposed`。
4. 在语义所属模块修复已授权的问题，运行聚焦测试与受影响协议、重放测试。
5. 分开记录代码提交、测试结果、实际发布版本、运行时验收、限制与回退目标。

队列没有变化时不重复启动模型调用，也不通过数据库重建整套队列状态。已有充分授权无需重复询问。

## 按需参考

- 后端异常：[backend-change.md](references/backend-change.md)
- 数据库修改：[database-change.md](references/database-change.md)
- 容器、网络与发布：[infrastructure.md](references/infrastructure.md)

仅加载任务需要的说明。技能提供工作方法，不授予发布、数据库迁移或服务器角色权限。不得在公开客户端输出服务器源码、凭据、内部数据库路径、私有因子定义或完整生成物。修改前必须能确定目标、版本、授权及所需回退方案。
