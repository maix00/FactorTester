"""
本地中国期货数据源 (LocalCNFutures)

提供该数据源下的所有数据路径常量及合约信息读取函数。
"""
from scripts.data_dir import DATA_DIR
from tools.data.artifacts.storage import artifact_path, source_data_root

SOURCE_DATA_DIR = str(source_data_root("LocalCNFutures", default=DATA_DIR))

# ---- 展期/合约信息 ----
ROLLER_INFO_PATH = str(artifact_path("LocalCNFutures", "roller_info.parquet"))

# ---- 合约级别分钟数据 ----
MINK_PRODUCT_DIR = SOURCE_DATA_DIR + '/data_mink_product'

# ---- 期限结构快照表 ----
TERM_STRUCTURE_PATH = str(artifact_path("LocalCNFutures", "term_structure-listed_contracts.parquet"))
