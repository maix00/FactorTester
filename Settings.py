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

from Category import CategoryTree, combine_trees
def get_cat_tree() -> CategoryTree:
    from Products import Product
    from CNFutures import CNFuturesSectorNightTimeCategory
    return CNFuturesSectorNightTimeCategory.get_tree_with_parents(ancester=Product)
