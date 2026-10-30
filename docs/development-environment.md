# 开发环境

## 标准环境

项目以 Conda 环境 `GTHT` 作为仓库开发、服务器调试和测试运行环境。

```bash
conda env create -f environment.yml
conda activate GTHT
```

当前基线依赖来自现有可运行环境：

| 包 | 版本 |
|---|---:|
| Python | 3.14.0 |
| SQLite | 3.53.2 |
| numpy | 2.3.4 |
| pandas | 3.0.2 |
| pytest | 9.0.3 |
| flask | 3.1.3 |
| scipy | 1.16.3 |
| waitress | 3.0.2 |
| matplotlib | 3.10.7 |
| tqdm | 4.67.1 |
| pyarrow | 22.0.0 |
| maturin | 1.15.0 |
| celery | 5.6.3 |

## NautilusTrader 本地扩展

NautilusTrader 由 `vendor/nautilus_trader` 固定版本提供；因子核心和 bridge 由
`vendor/py-alpha-lib` 固定提交的 submodule 提供。初始化源码时使用
`git submodule update --init --recursive`。TradeResearch 的
`native/traderesearch_nautilus_runtime` 只负责把两者组装到一个原生扩展。第一次运行完整
测试或 Nautilus 集成测试前，统一测试入口会在 `GTHT` 中构建对应的 Python
扩展；也可以手动执行：

```bash
./scripts/build_nautilus_extension.sh
```

构建使用 vendor 仓库锁定的 Rust toolchain、`maturin==1.15.0` 和开发 profile
（默认 `opt-level=1`，降低 macOS Python 扩展链接体积），复用
`.artifacts/nautilus-build/host-target`。测试会拒绝静默跳过扩展缺失、加载其他
wheel 或版本不匹配的情况。

alpha adapter 及两个公共因子策略的原生测试使用同一固定 Nautilus 源码：

```bash
conda run -n GTHT python scripts/test_alpha_nautilus_adapter.py
```

该脚本从组合 manifest 读取 source patches，不另维护依赖版本清单。alpha 核心
不依赖 Nautilus；策略库管理与版本冻结仍属于 TradeResearch。

## SQLite 并发版本

GTHT 固定 SQLite 3.53.2。3.51.0/3.51.1 在 Unix 上并发打开与关闭 WAL 数据库时可能死锁，表现为测试 HTTP 请求永久等待、后台同步线程卡在原生锁中。
该问题已有 [SQLite 官方修复说明](https://www.sqlite.org/releaselog/3_51_2.html)。不要通过禁用同步或增加业务锁绕过旧运行库问题。
更新使用 `environment.yml`；单独维护现有环境时先做 Conda dry-run，检查只改变所需包。`scripts/test.sh` 提前拒绝受影响的两个版本。

## 测试

统一用 `GTHT` 环境执行测试：

```bash
conda run -n GTHT python -m pytest -q
```

不要默认使用 shell 当前激活的 `base` 环境；`base` 环境缺少本项目所需的量化计算依赖。

也可以使用仓库提供的统一入口脚本：

```bash
./scripts/test.sh
```

### 启用离线 git hooks

由于数据/环境限制，不能只依赖 GitHub Actions。每个开发 worktree 都应启用本仓库内置的离线 hooks：

```bash
git config extensions.worktreeConfig true
git config --worktree core.hooksPath "$(pwd)/.githooks"
```

Hook 根据暂存差异（commit）或待推送提交差异（push）选择聚焦测试：已明确映射的源码只运行对应测试，未知源码路径和公共配置仍运行完整测试；修改 selector 时运行 selector 自身的合同测试，修改 Git hook 时仍运行完整测试。只有文档变化时跳过测试，Skill 变化仍检查内置 Skill 激活。`scripts/test.sh` 不带参数始终运行完整 pytest，可传入 pytest 路径运行指定 Python 测试；`scripts/test_js.sh` 使用 `GTHT` Conda 环境中随 Python Playwright 捆绑的 Node 驱动，不依赖主机全局 npm 模块，不带参数运行全部 JS 测试，也可传入 `tests/js/test_*.js`。正式发布仍须遵守独立的发布验证门槛，hook 的范围选择不能替代发布验收。

关闭：

```bash
git config --worktree --unset core.hooksPath
```

## 说明

- `conda env export --from-history` 目前只能导出 `python`，因为其余包是后续安装的；因此仓库使用 `environment.yml` 显式记录当前真实运行基线。
- 数据文件仍位于仓库外部的 `../data/` 目录。若要启动 Flask app，需要保证该目录结构存在。

## CLI 与测试运行时的边界

`GTHT` 不安装 `traderesearch` 或 `traderesearch-manager`。这两个命令行应用
属于 FTClient.app 的用户运行时，不属于仓库的服务器/量化开发依赖。普通用户
安装 App 后由 App 激活内置 runtime；如需在终端调用，使用 App 生成的环境
脚本：

```bash
source "$HOME/Library/Application Support/FactorTester/bin/factortester-env.sh"
```

该脚本设置 `FACTORTESTER_CLI`、`FACTORTESTER_MANAGER_CLI` 和 PATH，入口
始终指向 App 当前激活版本。不要把这两个命令安装到全局 Python、Conda 或
pipx，也不要让外部 PATH 覆盖 App 管理入口。

同一个发布包可以提供两个入口：

```text
traderesearch          研究、Profile、Job 和本地客户端操作
traderesearch-manager  Manager 登录、任务/生成物查询和服务器声明操作
```

`factortester` 根命令不会注册 Manager 命令；两个入口仍然共享同一个已签名
runtime，但命令树和服务端权限不同。Swift 客户端使用 App 内的已签名 runtime，
不依赖 `GTHT` 或用户 PATH。

本机实际运行测试的依赖不安装到 CLI 环境。它们由执行端负责：优先使用
FactorTester Docker runner；必须原生运行时，才根据 Job/Worktree 的依赖清单
创建独立的 runner Conda/venv。这样升级 CLI 不会改变既有测试环境。

本机 Cargo 操作从仓库根运行，复用根 `.cargo/config.toml` 的单一 host target，避免在 alpha、Nautilus、runtime 各自产生一套依赖编译产物。Linux 发布容器使用单独的有界 target，不能与 macOS 架构混用。运行时构建回执放在 `.artifacts/runtime-receipts`，不放进可删除的 Cargo target。清理前确认无 Cargo/rustc/maturin 进程且已安装扩展不是 target 内符号链接；使用 `cargo clean --target-dir <明确的生成目录>`，不得清理源码、数据、数据库或用户备份。缓存被淘汰后重编译是正常代价，不虚报为增量命中。
