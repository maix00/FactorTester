# Chart workbench Web bundle

此 React + TypeScript 边界按页面需要挂载，复用现有 Manager/客户端 Web 的身份与价格 API。产品行情入口加载 `chart-workbench-price`，静态产物为 `static/vendor/chart-workbench/price-chart.js`，随仓库交付，运行时不调用 npm。

在开发环境中执行 `npm ci && npm run typecheck && npm run build`。提交源码、锁文件与重新生成的静态产物，不提交 `node_modules/`。图内使用 Lightweight Charts 内置 TV 标识，不添加第二份文字标注。
