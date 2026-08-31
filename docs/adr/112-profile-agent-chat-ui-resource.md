# ADR 112：Profile Agent 会话使用成熟的行业 UI 资源

## 状态

已接受。

## 背景

Profile 详情页需要真正的会话界面：流式助手消息、会话状态、Markdown、错误处理和移动端输入框行为。Manager 已拥有认证的 Profile Agent app-server bridge 及 SSE 事件流；若用自定义气泡和 textarea 重建这些交互，会重复一个成熟 UI 问题。

仓库是无依赖的 vanilla JavaScript 壳，不是 React 应用；服务器 Agent 边界还负责选择 provider 并把凭据留在浏览器之外。因此聊天 UI 必须与 provider 无关。

## 决策

使用官方 ChatKit Web Component 作为 Profile Agent 聊天表面：

- [ChatKit JS](https://openai.github.io/chatkit-js/)
- [ChatKit JS 快速开始](https://openai.github.io/chatkit-js/quickstart/)
- [ChatKit Python 协议类型](https://github.com/openai/chatkit-python/blob/main/chatkit/types.py)

只有打开 Profile Agent 会话 tab 时才懒加载组件。`profile/chatkit-adapter.js` 把 ChatKit 的 thread/streaming 事件协议转换为现有认证 Manager RPC/SSE bridge；它不选择模型、不接收 provider token、不暴露服务器路径。Provider 选择仍是服务器/Profile 关注点，因此未来非 OpenAI provider 可以复用相同 UI 协议。

评估过这些替代方案：

- [assistant-ui](https://www.assistant-ui.com/docs/) 的 React 可复用界面最完整，支持自定义 runtime、REST/custom protocol、AG-UI、A2A、LangGraph 等，是未来迁移候选，但需要 React 构建；
- [Vercel AI Elements](https://elements.ai-sdk.dev/) 提供可组合会话、prompt、工具、来源和工作流组件，但依赖 React/shadcn 与 Vercel AI SDK，不适合当前 vanilla 壳直接引入；
- [CopilotKit](https://docs.copilotkit.ai/) 提供 React 聊天组件和 headless UI，支持 AG-UI 后端，适合将来采用 AG-UI，但会引入更大的 React/Agent UI 集成面；
- [Flowise Embed](https://docs.flowiseai.com/using-flowise/embed) 最接近脚本嵌入，但把 UI 耦合到 Flowise chatflow/backend，不适合 FactorTester 认证 Profile Agent 协议。

当前 ChatKit 只作展示层；本地 `chatkit-adapter.js` 和 `chatkit-protocol.js` 保持 provider 无关。若壳未来迁到 React，首选替代是 assistant-ui，后端协议边界优先采用 AG-UI。

## 后果

Profile 页面获得维护中的会话 UI，而不是自制 transcript/composer。Manager 必须在认证壳 CSP 中允许官方 ChatKit script 和 iframe 来源。ChatKit 是外部懒加载依赖；将来若有离线或供应链要求，应固定并 vendor 版本，同时保留 adapter 边界。附件和 provider 专属控件在 Manager 提供对应认证协议操作前保持禁用。
