# 本地 Xpert ChatKit 构建

上游：<https://github.com/xpert-ai/chatkit-js>，Apache-2.0。
固定版本：`20d26e03db7ca740cac78e5c69a95eb18dbdb613`。
构建产物随仓库保存，运行服务器无需 npm、Xpert 云服务或 OpenAI UI CDN。

在仓库外准备干净的上游 checkout，使用它声明的 pnpm 与 lockfile 安装依赖：

```sh
pnpm --filter @xpert-ai/chatkit-ui... --filter @xpert-ai/chatkit-web-component... install --frozen-lockfile --ignore-scripts
```

在 FactorTester 任务 worktree 中用 GTHT Python 构建：

```sh
python scripts/xpert-chatkit/build.py --source /absolute/path/to/upstream --pnpm /absolute/path/to/pnpm
```

脚本核对版本与干净状态，临时应用 `host-integration.patch`，结束后撤回该补丁。
它重新生成 `static/vendor/xpert-chatkit/` 及 manifest 的 `vendor_assets` 声明。
不把上游依赖目录放入 FactorTester，不启动任何云后端。

补丁仅补足宿主刷新/显示历史命令、隐藏只读输入框及阻止运行中发送补充请求。
运行中消息默认排队，点击「引导」后使用 Manager 严格轮次 Steer；失败保留消息且不自动重发。修改补丁后必须重新构建，并验证桌面和移动 WebKit。

`frame-bootstrap.js` 将 iframe SDK 请求限定到同源、单个 Profile 的 Manager 适配器。
`cs-x-factor-tester` 仅满足上游 UI 的就绪检查，不是凭据，也不授予权限。
Manager 登录和 Profile 权限仍由既有 API 校验；关闭界面只取消监听，不停止服务器任务。
