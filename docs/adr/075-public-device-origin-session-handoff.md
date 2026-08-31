# ADR 075：规范公共 IP 的设备认证

## 状态

已由 ADR-077 取代。

## 历史决策

浏览器设备认证只有一个来源：配置的公共 Manager HTTPS IP 端点。浏览器私钥只在那里注册和使用；ngrok 不执行设备挑战、设备校验或会话 handoff。

ngrok 只是访客入口。它通过短期访客 grant 一次性跳转到公共 IP；grant 允许公共 IP 合规页显示访客入口，但不认证用户，也不携带私钥或 Manager 会话。没有公共 IP 设备密钥的浏览器留在合规页；没有有效 ngrok grant 的直接公共 IP 访问永不显示访客入口，也不跳回 ngrok。
