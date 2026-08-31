# ADR-136：服务器拥有管理访问方式与部署脚本

> **编号迁移说明：** 本文原文件名为 `094-server-owned-management-access.md`。
> 因 ADR-094 已用于本地研究运行时与共享报告同步，本文迁移为 ADR-136；决策内容不因重编号改变。

## 状态

已接受。

## 背景

`factortester-manager` 必须能在没有 FactorTester 源码树的管理员设备上使用。
CLI 不能根据主机名或角色猜测目标是本地 Docker、远程 SSH 还是部署传输。现有
Manager 身份契约已经有经过校验的非秘密 `management_access` 投影，但部署设置
过去没有条目，资产目录也没有脚本。

## 决策

1. 每个 Manager 自己的 `.settings` 是连接方式、endpoint、端口、Profile、能力
   和本地凭据前置条件的权威。
2. 仓库只携带 `server/access-scripts/` 下小型、审查过的非秘密资产。Manager
   只向授权 Manager 主体提供资产，并校验声明的 SHA-256。
3. CLI 只展示声明、检查本机就绪状态并以 owner-only 权限下载脚本；不执行服务端
   返回的内容，也不接收私钥、密码、token 或可执行命令。
4. 本地和公共节点提供 Docker 检查/重启 helper；公共节点额外提供有界 SSH
   检查和精确 SHA 的发布激活。激活仍受远程备份、健康检查、PostgreSQL 保留和
   回滚事务保护。
5. WireGuard 是服务器间应用传输声明，不是 Manager CLI 的主机管理方式；peer
   key、路由和隧道生命周期由部署拥有。

## 后果

干净的管理员设备可以配置并认证 Manager，再发现目标专属的管理流程；但新设备
仍需自己的 Docker Context、SSH profile 或云凭据，服务器不能替它生成。公共 IP、
SSH profile 或 Docker Context 改变时，需要更新该服务器 `.settings` 并重新部署。
下载脚本不等于授权修改主机，操作员批准和目标主机授权仍是不同边界。
