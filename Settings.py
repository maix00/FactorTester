from __future__ import annotations

# =============================================================================
# Settings.py
# 全局配置文件
#
# 定义系统级常量与工厂函数：
#   - 因子测试的默认日期区间
#   - 数据目录、日志目录路径
#   - 按成交量筛选品种的默认比例
#   - 交易时段默认时间
#   - get_cat_tree()  : 构建品种分类树（板块 × 夜盘时段）
#   - get_all_products(): 获取全量品种对象列表
# =============================================================================
import os
from pathlib import Path
import pandas as pd

# 按成交量 top-k 筛选时保留的品种比例（0~1）
sift_volume_ratio = 0.8

# IC 测试是否并行计算（默认 True，可设为 False 降级排错）
IC_PARALLEL: bool = True
# IC 并行计算的最大线程数
IC_PARALLEL_MAX_WORKERS: int = 8

# IC 测试的默认日期区间（带时区）
default_test_start_date = pd.Timestamp('2025-01-02', tz='Asia/Shanghai')
default_test_end_date = pd.Timestamp('2025-05-31', tz='Asia/Shanghai')

# 绘制净值曲线的默认日期区间（可与 IC 测试区间不同）
default_plot_test_start_date = pd.Timestamp('2025-01-02', tz='Asia/Shanghai')
default_plot_test_end_date = pd.Timestamp('2025-12-31', tz='Asia/Shanghai')

# data 根目录（统一由 scripts/data_dir.py 解析，支持 worktree 隔离）
from scripts.data_dir import DATA_DIR

# 统一本地 sqlite 路径（所有镜像库合并到一个文件）
CACHE_DIR = Path(DATA_DIR) / 'cache' / 'localdata'
CACHE_DB_PATH = CACHE_DIR / 'onlinedata.sqlite'

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

def get_cat_tree() -> CategoryTree:
    """
    构建品种分类树，合并「板块+夜盘时段」两级分类。

    返回：
        CategoryTree，根节点为 Product，叶节点为各组合分类
    """
    from tools.products.categories.Category import CategoryTree, combine_trees
    from tools.products.Product import Product
    from sources.LocalCNFutures.CNFutures import CNFuturesSectorNightTimeCategory
    return combine_trees(
        CNFuturesSectorNightTimeCategory.get_tree_with_parents(ancester=Product),
        CNFuturesSectorNightTimeCategory.get_tree(ancester=Product),
    )

def get_all_products():
    """
    获取本地 CN 期货数据源中所有品种对象列表。

    返回：
        List[CNFutures]，每个元素对应一个主力合约品种
    """
    from sources.LocalCNFutures.CNFutures import get_all_futures
    return get_all_futures()
