# Lightweight Charts 来源与静态产物

源码是 `third_party/lightweight-charts` Git submodule，来自 `maix00/lightweight-charts` fork，固定在上游 v5.2.1。克隆仓库后先执行 `git submodule update --init --depth 1 third_party/lightweight-charts`。若浅克隆未包含固定提交，使用普通 `git submodule update --init`。

在本地开发机运行 `python scripts/chart-workbench/vendor_lightweight_charts.py`，脚本检查 submodule 提交和版本，下载同版本官方 npm 预构建产物并验证固定 SHA-512，写入 `static/vendor/lightweight-charts/`，登记 Web manifest。发布时静态产物随代码携带，服务器和 macOS 客户端运行时不访问 npm 或 GitHub。改动 fork 源码后必须更新固定提交、从该源码构建并替换产物，不能继续使用旧 npm 产物。

页面真正挂载图表时必须提供用户可见的 TradingView 署名和 `https://www.tradingview.com/` 链接，保留随产物提供的 LICENSE 与 NOTICE。`lightweight-charts-indicators` 和 `lightweight-charts-drawing` 目前只是候选参考，不属于此阶段的依赖。
