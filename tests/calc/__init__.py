"""
tests/calc 包初始化 — 统一管理 test 数据路径与数据源。

================================================================
🚫 数据源白名单（Agent 和 Human 都必须遵守）
================================================================
本包所有脚本只允许使用以下两个数据源路径：

  1. WIND_MAPPING_PATH  — Wind 主力合约映射表 (wind_mapping.parquet)
  2. MIN_DATA_DIR        — 分钟行情数据目录 (data_mink_product/)

❌ 禁止引入任何其他数据源路径，包括但不限于：
   · main_dayk / main_mink（test_2a 若需主连数据，单独在脚本内声明）
   · 任何 CSV / Parquet / SQLite 数据目录
   · 任何通过 scripts/ 间接引入的外部数据

如确需新增数据源，必须：
  1. 先更新本文件的白名单
  2. 在 _DATA_SOURCES_DOC 中补充说明
  3. 提交时在 commit message 中注明新增理由

================================================================
路径集中管理
================================================================
所有 test 脚本的路径配置集中于此，避免各自重复定义。
test_0 / test_1 / test_2a 等脚本通过 `from tests.calc import ...` 使用。

================================================================
"""

from pathlib import Path

from scripts.data_dir import DATA_DIR as _ROOT_DATA_DIR

# ============================================================
# 数据源路径（只读）
# ============================================================

# Wind 主力合约映射表
WIND_MAPPING_PATH = Path(_ROOT_DATA_DIR) / 'wind_mapping.parquet'

# 分钟行情数据目录
MIN_DATA_DIR = Path(_ROOT_DATA_DIR) / 'data_mink_product'

# ============================================================
# Test 输出路径
# ============================================================

# test_0: 统计分析结果
TEST_0_DIR = Path(_ROOT_DATA_DIR) / 'test' / 'test_0'
TEST_0_PRODUCTS_XLSX = TEST_0_DIR / '_products.xlsx'

# test_1: 截断数据导出（每个品种一个 Excel，直接放在此目录下）
TEST_1_DIR = Path(_ROOT_DATA_DIR) / 'test' / 'test_1'

# test_2a: Excel 公式复权验证
TEST_2A_DIR = Path(_ROOT_DATA_DIR) / 'test' / 'test_2a'

# test_2b / test_2c (预留给后续)
TEST_2B_DIR = Path(_ROOT_DATA_DIR) / 'test' / 'test_2b'
TEST_2C_DIR = Path(_ROOT_DATA_DIR) / 'test' / 'test_2c'

# ============================================================
# 全局配置
# ============================================================

WINDOW_DAYS = 2  # test_1 合约数据 ± 天数

# wind_mapping 交易所 → 分钟文件 交易所
# 数据源文档说明（供 agent 和 human 查阅）
_DATA_SOURCES_DOC = f"""
=== calc 包数据源白名单 ===
1. WIND_MAPPING_PATH = \"{WIND_MAPPING_PATH}\"
   → Wind 主力合约映射表，字段: S_INFO_WINDCODE, FS_MAPPING_WINDCODE, STARTDATE, ENDDATE
2. MIN_DATA_DIR = \"{MIN_DATA_DIR}\"
   → 分钟行情数据，文件命名: {{交易所}}|F|{{品种}}|{{合约}}.parquet

禁止使用其他数据源（main_dayk, main_mink, 自定义CSV等）。
"""

# --- 交易所映射 ---

WIND_EXCH_TO_MIN_EXCH: dict[str, str] = {
    'SHF': 'SHFE',
    'DCE': 'DCE',
    'CZC': 'CZCE',
    'INE': 'INE',
    'CFE': 'CFFEX',
    'GFE': 'GFEX',
}
