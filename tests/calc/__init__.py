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

from openpyxl.styles import Alignment, Font, PatternFill

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
#   === Excel 动态数组溢出 + 列格式关键技术（test_2a 已验证）===
#   1. 多列溢出方案：
#      - 每列独立 CHOOSECOLS(单一 REDUCE+HSTACK, col_N) 动态数组公式
#      - REDUCE 共享子表达式，23 个 CHOOSECOLS 各取一列
#      - 优势：每列独立 s=（样式索引），日期列可单独设置日期格式
#   2. WPS 动态数组溢出格式继承规则：
#      - <col style="xfId"> → 溢出行继承列样式 ✅
#      - <col numFmtId="164"> → 溢出行不继承 ❌（WPS 忽略）
#      - 公式行自身的 s= → 覆盖 <col style>
#   3. 日期格式方案（两管齐下）：
#      a) XML 注入 <cols><col style="xfId"/>：溢出行获得日期格式
#      b) 公式行 cell s=：公式行（row 3）获得日期格式
#      c) xfId → numFmtId 映射：从 styles.xml 的 cellXfs 中查找
#   4. openpyxl 限制：
#      - ColumnDimension.number_format 写入后无 numFmtId（WPS 不认）
#      - ColumnDimension.style 无 setter，无法直接赋值
#      - 结论：必须用 XML 后处理（zipfile + ElementTree）
#   5. 前复权方向（test_2a 使用前复权）：
#      - 最新合约 adj_mul = 1，向前反向累积
#      - adjustment_mul[i] = _cur_close[i] / _next_close * _next_adj
#      - 历史数据被压缩到最新价格水平
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

# ============================================================
# 共享 Excel 样式常量
# ============================================================

FORMULA_FILL = PatternFill(start_color='FFFFF2CC', end_color='FFFFF2CC', fill_type='solid')
HEADER_FILL = PatternFill(start_color='FFD9E1F2', end_color='FFD9E1F2', fill_type='solid')

# Row 1 remark 样式（test_1 / test_2a 共用）
REMARK_FILL = PatternFill(start_color='FFFCE4D6', end_color='FFFCE4D6', fill_type='solid')
REMARK_FONT = Font(bold=True)        # 也用于表头
REMARK_ALIGNMENT = Alignment(wrap_text=True, vertical='top')

# test_1 comment 样式
COMMENT_FONT = Font(italic=True, size=10)
COMMENT_ALIGNMENT = Alignment(wrap_text=True)  # 与 test_1 一致（无 vertical='top'）

# test_1 → 5 行 remark → 80pt；以此基准
REMARK_ROW_HEIGHT_PER_LINE = 16


def remark_height(text: str) -> float:
    """按行数动态计算 row 1 remark 高度，最小 45pt，最大 200pt"""
    lines = text.count('\n') + 1
    return max(45, min(200, lines * REMARK_ROW_HEIGHT_PER_LINE))
