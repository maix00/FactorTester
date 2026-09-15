from __future__ import annotations

# =============================================================================
# settings.py
# 全局配置文件
#
# 定义系统级常量与工厂函数：
#   - 数据目录、日志目录路径、SQLite 数据库路径
#   - 按成交量筛选品种的默认比例
#   - 交易时段默认时间
#   - get_cat_tree()  : 构建品种分类树（板块 × 夜盘时段）
#   - get_all_products(): 获取全量品种对象列表
# =============================================================================
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
# ── 平台感知的默认线程数 ──
# macOS: 保持 merge 前经过实际使用验证的 8 worker 上限。
# Windows/Linux: GIL 争抢重，线程过多反而互相踩踏，cap 更低。
def _default_max_workers(cpu_bound: bool = True) -> int:
    cpu = os.cpu_count() or 4
    if sys.platform == 'darwin':
        return min(cpu, 8 if cpu_bound else 12)
    else:
        return min(max(cpu // 2, 2), 4 if cpu_bound else 6)

# 按成交量 top-k 筛选时保留的品种比例（0~1）
sift_volume_ratio = 0.8

# IC 测试是否并行计算（默认 True，可设为 False 降级排错）
IC_PARALLEL: bool = True
# IC 并行计算的最大线程数（CPU 密集型，平台自适应）
IC_PARALLEL_MAX_WORKERS: int = _default_max_workers(cpu_bound=True)

# waitress 生产模式线程数（I/O 密集型，可略高于 CPU workers）。
# 容器/公网按部署规模用 FACTORTESTER_WAITRESS_THREADS 覆盖：默认值随
# CPU 数下降（Linux 上 4 核只有 2 线程），多用户并发下会成为排队瓶颈。
def _worker_env_override(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, 1), 64)


WAITRESS_THREADS: int = _worker_env_override(
    "FACTORTESTER_WAITRESS_THREADS", _default_max_workers(cpu_bound=False),
)

# data 根目录（统一由 scripts/data_dir.py 解析，支持 worktree 隔离）
from scripts.data_dir import DATA_DIR, CACHE_DB_PATH

if TYPE_CHECKING:
    from tools.products.categories.Category import CategoryTree

# ── SQLite 数据库路径（由 data_dir.py 从 .settings 统一解析）──
CACHE_DIR = Path(CACHE_DB_PATH).parent

# 日志文件存储目录
logger_dir_path_default = os.path.join(DATA_DIR, 'factor_tester_log')

# 因子测试结果缓存目录
factor_info_path = os.path.join(DATA_DIR, 'Factors')

# 默认交易日的开始/结束时间（用于判断场内/场外）
default_day_start_time = '00:00'
default_day_end_time = '00:00'

# 中国期货日盘时段默认时间
default_cn_futures_day_start = '09:00'
default_cn_futures_day_end = '15:00'

# 中国期货夜盘时段默认时间
default_cn_futures_night_start = '21:00'
default_cn_futures_night_end = '15:00'  # 夜盘跨零点，以次日 15:00 为结束

def get_cat_tree(category_id: str | None = None) -> CategoryTree:
    """
    构建品种分类树，合并「板块+夜盘时段」两级分类。

    返回：
        CategoryTree，根节点为 Product，叶节点为各组合分类
    """
    from tools.products.categories.Category import CategoryTree, combine_trees
    from tools.products.Product import Product
    from sources.LocalCNFutures.CNFutures import (
        CNFuturesDayNightTimeCategory,
        CNFuturesSectorCategory,
        CNFuturesSectorNightTimeCategory,
    )
    category = CNFuturesSectorNightTimeCategory
    if category_id == "day_night":
        category = CNFuturesDayNightTimeCategory
    elif category_id == "sector":
        category = CNFuturesSectorCategory
    elif category_id == "day_night_x_sector":
        category = CNFuturesDayNightTimeCategory * CNFuturesSectorCategory
    if category_id is None:
        cn_tree = combine_trees(
            category.get_tree_with_parents(ancester=Product),
            category.get_tree(ancester=Product),
        )
    else:
        # The catalog UI requested one explicit dimension.  Do not add the
        # category's parent projections as extra, duplicate branches.
        cn_tree = category.get_tree(ancester=Product)
    return cn_tree

def get_all_products():
    """
    获取本地 CN 期货数据源中所有品种对象列表。

    返回：
        List[CNFutures]，每个元素对应一个主力合约品种
    """
    from sources.LocalCNFutures.CNFutures import get_all_futures
    return list(get_all_futures())
