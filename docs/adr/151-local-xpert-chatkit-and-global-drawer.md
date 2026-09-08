# ADR 151：本地 Xpert ChatKit 与应用级智能体 drawer

## 状态

已选择方案；Issue #385 隔离 worktree 实现与验证，未发布。替代 ADR 112 的官方 UI 分发选择。
ADR 150 在暂停的 Hermes 工作区中保留为独立草案，不属于本次变更。

## 决策

采用固定 SHA 的 Xpert ChatKit UI 与 Web Component，本地提供完整 iframe、字体及动态脚本。
保留 Manager 的 Profile、会话、RPC/SSE 和历史消息权威来源。现有 `chatkit-*` 名称的
模块是内部消息投影及适配器，不再加载官方 Web Component。浏览器不接收模型凭据。
Xpert SDK 的会话/运行请求仅在同源宿主适配器转换；不增加 Xpert 会话数据库。
不支持的端点明确失败，不转发到外部网络。

智能体 drawer 由应用外壳拥有。切换 tab 不隐藏、不搬动、不销毁 iframe，也不停止任务。
页面只发布可选 Profile 和辅助填写契约。研究 Profile 可以保留原会话；若不属于新页面
的可见范围，不为该页面连接填写接收器。页面销毁仅释放页面契约，不能销毁 drawer。
用户明确切换 Profile 时才更换聊天表面并清理旧监听。退出应用自然释放浏览器资源。

重建会话时通过当前运行状态发现运行中的 turn，续接已有事件流；续接不能提交用户消息、
创建 turn 或调用 steer。历史投影继续用于补齐缺失事件。

## 追加消息与 Steer

复用上游待发送区域：运行中追加消息默认排队，每条消息的「引导」按钮才提交 Steer。
成功回执后移除待发送项，加入会话；失败保留消息并显示错误，不自动作为新一轮发送。
宿主将 `client.runs.create` 转换为现有 `turn/steer`，校验会话与轮次身份。
显式 Steer 使用 `requireActiveTurn`；过期轮次拒绝，不能提升为 `turn/start`。
旧恢复调用仍保留原兼容行为。Steer 不关闭、不重新创建当前 SSE。

## 验证边界

浏览器验证使用本地合成会话，无生产负载。测试覆盖本地资源、历史与流式显示、只读拒绝、
隔离通道、切换 tab 不重建 drawer。真实供应商模型与生产部署不属于本轮本地测试回执。
构建及补丁说明见 `scripts/xpert-chatkit/README.md`。

## 会话身份与设置（2026-09-08）

ChatKit header 内承载 Profile；专门的 Agent 会话页固定身份，drawer 使用当前页面授权的候选。
原有模型、推理强度和速度档位控制器通过同源挂载槽进入 ChatKit 设置面板，沿用原有目录、保存验证和运行时回显 API。
挂载槽由 React 管理，控件 DOM 与事件由 Manager 管理；关闭面板后重开复用控件，销毁会话时撤销挂载注册。
不提供 pet 设置。会话样式在本地 `frame-theme.css` 中统一，构建时加入内容哈希；保留上游代码复制与滚动行为。
