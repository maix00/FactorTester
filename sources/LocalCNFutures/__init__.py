"""
本地中国期货数据源 (LocalCNFutures)

提供该数据源下的所有数据路径常量及合约信息读取函数。
"""
import os

DATA_DIR = os.environ.get(
    'GTHT_DATA_DIR',
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data')),
)

# ---- 展期/合约信息 ----
ROLLER_INFO_PATH = DATA_DIR + '/roller_info.parquet'

# ---- 合约级别分钟数据 ----
MINK_PRODUCT_DIR = DATA_DIR + '/data_mink_product'

# ---- 期限结构快照表 ----
TERM_STRUCTURE_PATH = DATA_DIR + '/cn_futures_term_structure.parquet'
