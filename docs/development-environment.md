# 开发环境

## 标准环境

项目以 Conda 环境 `ft` 作为当前标准运行环境。

```bash
conda env create -f environment.yml
conda activate ft
```

当前基线依赖来自现有可运行环境：

| 包 | 版本 |
|---|---:|
| Python | 3.14.0 |
| numpy | 2.3.4 |
| pandas | 3.0.2 |
| pytest | 9.0.3 |
| flask | 3.1.3 |
| scipy | 1.16.3 |
| waitress | 3.0.2 |
| matplotlib | 3.10.7 |
| tqdm | 4.67.1 |
| pyarrow | 22.0.0 |

## 测试

统一用 `ft` 环境执行测试：

```bash
conda run -n ft python -m pytest -q
```

不要默认使用 shell 当前激活的 `base` 环境；`base` 环境缺少本项目所需的量化计算依赖。

也可以使用仓库提供的统一入口脚本：

```bash
./scripts/test.sh
```

### 可选：离线 git hooks

由于数据/环境限制，无法依赖 GitHub Actions 时，可以启用本仓库内置的离线 hooks，在 commit/push 前自动跑测试：

```bash
git config core.hooksPath .githooks
```

关闭：

```bash
git config --unset core.hooksPath
```

## 说明

- `conda env export --from-history` 目前只能导出 `python`，因为其余包是后续安装的；因此仓库使用 `environment.yml` 显式记录当前真实运行基线。
- 数据文件仍位于仓库外部的 `../data/` 目录。若要启动 Flask app，需要保证该目录结构存在。
