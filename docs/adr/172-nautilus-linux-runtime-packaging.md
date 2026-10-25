# ADR-172：Nautilus Linux 运行时打包

## 状态

阻塞（2026-10-25）。

## 事实

- 本地 Nautilus 为源码构建的 `2.0.0rc8`，扩展是 macOS arm64。
- PyPI 没有 `2.0.0rc8` 的 cp313/cp314 Linux wheel。
- piwheels 的 `2.0.0rc7`/`2.0.0rc6` 构建均失败，0 文件。
- 公网容器是 Python 3.14.7，没有 `nautilus_trader`。
- 公网没有 Rust/Cython/maturin 构建工具。

## 结论

不能通过 `pip install nautilus_trader==2.0.0rc8` 构建 Python 3.13 worker。
不能把本地 macOS `.so` 复制到 Linux 公网容器。

## 可选路径

1. 在 Linux 构建机安装 Rust/Cython，从 vendor 源码编译 cp313 wheel；
2. 发布 rc8 的 manylinux wheel 后再构建；
3. 将项目固定到有 Linux wheel 的 Nautilus 版本，重新做真实策略验收；
4. 暂缓公网真实 Nautilus，只保留本地真实执行。

## 禁止

- 用 fake executor 冒充公网 Nautilus；
- 把 macOS 二进制复制到 Linux；
- 在没有 wheel/构建工具时声称已部署。
