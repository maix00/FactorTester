default_test_start_date = '2025-01-02'
default_test_end_date = '2025-05-31'
default_day_start_time = '00:00'
default_day_end_time = '00:00'
default_cn_futures_day_start = '09:00'
default_cn_futures_day_end = '15:00'
default_cn_futures_night_start = '21:00'
default_cn_futures_night_end = '15:00'

current_time_settings = {
    "start_date": default_test_start_date,
    "end_date": default_test_end_date,
    "start_time": default_day_start_time,
    "end_time": default_day_end_time,
    "session_type": "normal"
}

import pandas as pd
from typing import TYPE_CHECKING, List

sift_volume_ratio = 0.8
default_test_start_date = pd.Timestamp('2025-01-01', tz='Asia/Shanghai')
default_test_end_date = pd.Timestamp('2025-05-31', tz='Asia/Shanghai')
default_plot_test_start_date = pd.Timestamp('2025-01-01', tz='Asia/Shanghai')
default_plot_test_end_date = pd.Timestamp('2025-12-31', tz='Asia/Shanghai')
logger_dir_path_default = '../data/factor_tester_log/'
factor_info_path = '../data/Factors/'

from tools.products.categories.Category import CategoryTree, combine_trees
def get_cat_tree() -> CategoryTree:
    from tools.products.Product import Product
    from sources.LocalCNFutures.CNFutures import CNFuturesSectorNightTimeCategory
    return combine_trees(
        CNFuturesSectorNightTimeCategory.get_tree_with_parents(ancester=Product),
        CNFuturesSectorNightTimeCategory.get_tree(ancester=Product),
    )

if TYPE_CHECKING:
    from tools.products.Product import Product
def get_all_products() -> List[Product]:
    from sources.LocalCNFutures.CNFutures import get_all_futures
    return get_all_futures()