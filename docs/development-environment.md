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

由于数据/环境限制，不能只依赖 GitHub Actions。每个开发 worktree 都应启用本仓库内置的离线 hooks，在 commit 前先检查生成的 Skill 副本，再运行测试：

```bash
git config extensions.worktreeConfig true
git config --worktree core.hooksPath "$(pwd)/.githooks"
```

关闭：

```bash
git config --worktree --unset core.hooksPath
```

## 说明

- `conda env export --from-history` 目前只能导出 `python`，因为其余包是后续安装的；因此仓库使用 `environment.yml` 显式记录当前真实运行基线。
- 数据文件仍位于仓库外部的 `../data/` 目录。若要启动 Flask app，需要保证该目录结构存在。

## CLI 与测试运行时的边界

`GTHT` 不安装 `factortester` 或 `factortester-manager`。这两个命令行应用
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
factortester          研究、Profile、Job 和本地客户端操作
factortester-manager  Manager 登录、任务/生成物查询和服务器声明操作
```

`factortester` 根命令不会注册 Manager 命令；两个入口仍然共享同一个已签名
runtime，但命令树和服务端权限不同。Swift 客户端使用 App 内的已签名 runtime，
不依赖 `GTHT` 或用户 PATH。

本机实际运行测试的依赖不安装到 CLI 环境。它们由执行端负责：优先使用
FactorTester Docker runner；必须原生运行时，才根据 Job/Worktree 的依赖清单
创建独立的 runner Conda/venv。这样升级 CLI 不会改变既有测试环境。
