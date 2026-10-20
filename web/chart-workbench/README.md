# Chart workbench Web bundle

此 React + TypeScript 边界按页面需要挂载，复用现有 Manager/客户端 Web 的身份与价格 API。产品行情、回测交易图和因子序列分别请求按需模块，但共用 `static/vendor/chart-workbench/chart-workbench.js`，避免重复下载 React 运行时。因子序列将同一产品的全部嵌套层级作为独立指标窗格显示；价格、成交量、持仓量与因子值共用时间轴，不共用数值刻度。产物随仓库交付，运行时不调用 npm。

在开发环境中执行 `npm ci && npm run typecheck && npm run build`。提交源码、锁文件与重新生成的静态产物，不提交 `node_modules/`。图内使用 Lightweight Charts 内置 TV 标识，不添加第二份文字标注。
