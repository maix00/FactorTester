# ADR 072：公共 ngrok 入口与显式代理信任

## 状态

已接受。

## 背景

稳定的 `eloquence-drizzly-fencing.ngrok-free.dev` 浏览器来源最初终止在开发 Mac，再转发到该机器的 Manager 7998。现在公共 FactorTester Manager 自己拥有长期服务，Mac 离线时也必须可达。公共主机仍不能开放入站 TCP 80/443，ADR-069 仍限制为两个业务容器。

公共主机上的 ngrok Agent 可以通过出站 TLS 连接 ngrok，把稳定 HTTPS 来源转到已经发布的 Manager 7998。但转发到 Docker 发布的主机端口会改变容器内看到的直接对等端：Manager 看到固定传输网关 `172.30.186.1`，而非 host loopback。若不识别规范的转发客户端地址，就会把网关当作内网客户端并暴露内网信息；若信任所有私有对等节点的转发头，直接调用方或其他容器又可以伪造已批准地址。

## 决策

1. ngrok Agent 是主机级入口 daemon，不是第三个 FactorTester 业务容器。它由 systemd 以无特权 `ngrok` 用户启动，转发 `https://eloquence-drizzly-fencing.ngrok-free.dev` 到 `https://localhost:7998`。
2. 浏览器到 ngrok 使用 ngrok 公共信任证书；Agent 到 Manager 仍走 HTTPS，并通过显式 CA 文件校验持久化 Manager 证书。不得关闭上游校验。ngrok authtoken 只放在主机受 owner/group 限制的配置中，不进 Git 或容器镜像。
3. ngrok Traffic Policy 删除调用方提供的 `X-Forwarded-For` 和 `X-Forwarded-Proto`，然后从 `conn.client_ip` 和固定安全 scheme 写入恰好一个规范客户端地址；多值转发链不属于本部署合约。
4. Manager 只有在直接对等端为 loopback 或属于 `FACTORTESTER_TRUSTED_PROXY_CIDRS` 时才信任转发头。公共 Compose 项目只配置传输网段 `/29` 的固定网关 `172.30.186.1/32`。设置启动时解析；空项、错误网络和带 host bits 的 CIDR 直接阻止启动，不回退到宽泛私有网信任。
5. 即便对等端可信，Manager 也只接受一个语法正确的 IP 和一个协议值。缺失、错误、重复或逗号分隔值回退到直接对等端，不能创建 secure-proxy 或 public-client 身份。
6. 设备身份仍是绑定一个账户的已注册公钥。注册和最近 IP 只是审计元数据，既不是认证因素，也不要求相等。
7. `https://<public-ip>:7998` 直连继续可用。ngrok 来源是额外的浏览器来源，有自己的 WebCrypto 存储；白名单用户在任一来源用访客模式登录，该来源自动注册当前浏览器。不使用内部 Manager handoff 或一次性 grant，一个来源的密钥永远不复制到另一个来源。

## 运维与故障行为

- 不新增入站安全组规则。Agent 通过出站 TLS 连接 ngrok；客户端访问 ngrok 的 443，公共主机继续关闭 80/443。
- Manager/容器重启期间域名可能短暂返回上游错误；Agent 保持运行，7998 健康后自动重连。主机重启由 systemd 恢复入口。
- ngrok 不可用时，7998 公共 IP 直连和服务器间 WireGuard 仍独立可用。
- Manager 证书轮换需刷新 Agent 信任的 CA 副本并重启服务；普通镜像发布保留已有证书，无需重建 ngrok。
- 本地 Mac 不再为该域名运行 Agent。用相同 URL 重启第二个非 pooled Agent 只作为明确回滚操作，不能作为正常 active/active 拓扑。

## 后果

稳定域名由公共 Manager 提供，不依赖开发 Mac；公共设备审计记录真实 IPv4/IPv6 客户端地址，匿名内网 API 仍受保护。代理信任是显式部署能力，不从 RFC 1918 地址或 Docker 成员身份推断。公共主机仍只有 ADR-066/069 所需的两个业务容器，ngrok 生命周期独立于 FactorTester 镜像构建和 PostgreSQL 恢复。
