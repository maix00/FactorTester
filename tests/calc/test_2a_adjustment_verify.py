"""
test_2a_adjustment_verify.py
-----------------------------
纯 Excel 公式版本 — REDUCE + VSTACK 动态拼接主力连续序列。

方案：
1. 从 test_1 复制合约 sheet 数据到 test_2a xlsx（同文件内）
2. _SWITCHES 用 INDIRECT 动态引用合约 sheet（不硬编码 sheet 名）
3. MAIN 用 REDUCE+VSTACK+INDIRECT 数组公式自动拼接所有合约数据行
   — 不需要 Python for 循环逐行写，不硬编码合约名或行号

🚫 test_1 已经跑好，此脚本不会重新跑 test_1。

_SWITCHES 辅助列（全部 Excel 公式，不硬编码行号、不硬编码 sheet 名）：
  _cur_close:  =INDEX(INDIRECT("'"&本合约B&"'!J:J"), MATCH(本合约D, INDIRECT("'"&本合约B&"'!E:E"), 0))
      本合约首日 (start_date) 收盘价
  _next_close: =INDEX(INDIRECT("'"&下一合约B&"'!J:J"), MATCH(下一合约D, INDIRECT("'"&下一合约B&"'!E:E"), 0))
      下一合约（更新合约）首日 (start_date) 收盘价
  _next_adj:   下一行的 adjustment_mul（向前引用）
  adjustment_mul: =IF(最后一行, 1, _cur_close/_next_close * _next_adj)
      前复权：最新合约=1，历史数据反向累积
  adjustment_add: =0

MAIN sheet（三列独立 VSTACK，各自溢出）：
  A3 = VSTACK(INDIRECT(_SWITCHES!L3), ...)  — 合约 21 列数据（不包 HSTACK）
  V3 = VSTACK(EXPAND(_SWITCHES!I3,...), ...)  — adjustment_mul
  W3 = VSTACK(EXPAND(_SWITCHES!J3,...), ...)  — adjustment_add
  关键洞察：VSTACK 参数包 HSTACK 会导致溢出仅第一个值

Output: data/test/test_2a/{prod}.xlsx
"""

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter, column_index_from_string

from tests.calc import TEST_1_DIR, TEST_2A_DIR

# --- XML 命名空间 ---
NS_SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS_RELS = 'http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('', NS_SHEET)
ET.register_namespace('r', NS_R)

# --- 样式 ---
FORMULA_FILL = PatternFill(start_color='FFFFF2CC', end_color='FFFFF2CC', fill_type='solid')
HEADER_FILL = PatternFill(start_color='FFD9E1F2', end_color='FFD9E1F2', fill_type='solid')
# Row 1 remark 样式（与 test_1 保持一致）
REMARK_FILL = PatternFill(start_color='FFFCE4D6', end_color='FFFCE4D6', fill_type='solid')
REMARK_FONT = Font(bold=True)
REMARK_ALIGNMENT = Alignment(wrap_text=True, vertical='top')
REMARK_ROW_HEIGHT = 60  # pt


def _col_letter(idx: int) -> str:
    return get_column_letter(idx)


def _col_idx(ref: str) -> int:
    """从 Excel 引用如 'A3' 或 'AB10' 提取 1-based 列号"""
    import re as _re
    m = _re.match(r'([A-Z]+)', ref)
    if not m:
        return 0
    return column_index_from_string(m.group(1))


# test_1 合约 sheet 列布局 (row1=remark, row2=header, row3+=data)
# 21 列全量: A=trading_day, B=trade_time, C=trade_timestamp, D=exchange_id,
# E=instrument_id, F=unique_instrument_id, G=open_price, H=highest_price,
# I=lowest_price, J=close_price, K=settlement_price, L=upper_limit_price,
# M=lower_limit_price, N=pre_settlement_price, O=volume, P=turnover,
# Q=open_interest, R=insert_time, S=product_id, T=twap, U=vwap
CONTRACT_COLS = [
    'trading_day', 'trade_time', 'trade_timestamp', 'exchange_id',
    'instrument_id', 'unique_instrument_id', 'open_price', 'highest_price',
    'lowest_price', 'close_price', 'settlement_price', 'upper_limit_price',
    'lower_limit_price', 'pre_settlement_price', 'volume', 'turnover',
    'open_interest', 'insert_time', 'product_id', 'twap', 'vwap',
]
CONTRACT_CLOSE_COL = 10      # J: close_price (21列布局)
CONTRACT_TD_COL = 1           # A: trading_day
CONTRACT_INST_COL = 5          # E: instrument_id
DATA_START_ROW = 3             # 数据从第3行开始 (1=remark, 2=header)

# _SWITCHES 列定义
# A=trading_day, B=instrument_id, C=windcode, D=start_date, E=end_date
# F=_cur_close, G=_next_close, H=_next_adj, I=adjustment_mul, J=adjustment_add
# K=_nrows, L=_ref_str
#
# 前复权 (forward-adjusted)：最新合约 adj=1，历史数据反向累积
#   adjustment_mul[i] = _cur_close[i] / _next_close * _next_adj
#   最后一行=1，向前逐行乘 → 最新价格水平不变，历史数据被压缩
#
# _ref_str:      Python 写入纯文本，如 'a2405'!A3:U14027，供 INDIRECT 使用
SW_ORIG_COLS = 5
CUR_CLOSE_COL = SW_ORIG_COLS + 1   # F=6: _cur_close (本合约首日收盘)
NEXT_CLOSE_COL = SW_ORIG_COLS + 2  # G=7: _next_close (下一合约首日收盘)
NEXT_ADJ_COL = SW_ORIG_COLS + 3    # H=8: _next_adj (下一合约的 adj_mul)
ADJ_MUL_COL = SW_ORIG_COLS + 4     # I=9: adjustment_mul
ADJ_ADD_COL = SW_ORIG_COLS + 5     # J=10: adjustment_add
SW_NROWS_COL = SW_ORIG_COLS + 6    # K=11: _nrows
SW_REF_STR_COL = SW_ORIG_COLS + 7  # L=12: _ref_str

# MAIN 列布局 (21 数据列 + 2 adjustment 列 = 23 列, A..W)
# A..U = 合约数据, V=adjustment_mul, W=adjustment_add
MAIN_NCOLS = len(CONTRACT_COLS) + 2  # 23
MAIN_MUL_COL_OFFSET = len(CONTRACT_COLS) + 1  # V=22
MAIN_ADD_COL_OFFSET = len(CONTRACT_COLS) + 2  # W=23


def _check_sheets_match(src_path: Path, dst_path: Path) -> bool:
    """Check if dst has the same contract sheets (name/row count) as src.
    Returns True if sheets match → can do in-place update without re-copying."""
    if not dst_path.exists():
        return False
    try:
        src_wb = load_workbook(src_path, read_only=True)
        dst_wb = load_workbook(dst_path, read_only=True)
        src_ct = {sn for sn in src_wb.sheetnames if sn != '_SWITCHES'}
        dst_ct = {sn for sn in dst_wb.sheetnames if sn not in ('_SWITCHES', 'MAIN')}
        if src_ct != dst_ct:
            src_wb.close()
            dst_wb.close()
            return False
        for sn in src_ct:
            src_rows = src_wb[sn].max_row
            dst_rows = dst_wb[sn].max_row
            if src_rows != dst_rows:
                src_wb.close()
                dst_wb.close()
                return False
        src_wb.close()
        dst_wb.close()
        return True
    except Exception:
        return False


def process_product(prod_xlsx: Path) -> None:
    prod = prod_xlsx.stem
    src_path = TEST_1_DIR / f'{prod}.xlsx'
    if not src_path.exists():
        print(f"  ⚠️ test_1 file not found: {src_path.name}, skipping")
        return

    dst_path = TEST_2A_DIR / f'{prod}.xlsx'
    inplace = _check_sheets_match(src_path, dst_path)

    print(f"  Processing: {prod}..." + (" (in-place)" if inplace else ""), end='', flush=True)

    # ============================================================
    # 1. 读取 test_1 源文件结构
    # ============================================================
    src_wb = load_workbook(src_path, read_only=True)
    src_sheets_set = {sn for sn in src_wb.sheetnames if sn != '_SWITCHES'}

    # 每个合约 sheet 的数据行数
    sheet_rows = {}
    for sn in sorted(src_sheets_set):
        ws = src_wb[sn]
        n = ws.max_row - 2
        if n > 0:
            sheet_rows[sn] = n

    # 读取 _SWITCHES 中的切换列表
    sw_ws = src_wb['_SWITCHES']
    sw_header_row = 2
    sw_data_start = 3

    td_col = None
    inst_col = None
    wc_col = None
    sd_col = None
    ed_col = None
    for c in range(1, sw_ws.max_column + 1):
        v = sw_ws.cell(sw_header_row, c).value
        if v == 'trading_day':
            td_col = c
        elif v == 'instrument_id':
            inst_col = c
        elif v == 'windcode':
            wc_col = c
        elif v == 'start_date':
            sd_col = c
        elif v == 'end_date':
            ed_col = c

    if td_col is None or inst_col is None:
        print(f"  ⚠️ Cannot find _SWITCHES columns, skipping {prod}")
        src_wb.close()
        return

    switches = []
    for row in range(sw_data_start, sw_ws.max_row + 1):
        td = sw_ws.cell(row, td_col).value
        inst = sw_ws.cell(row, inst_col).value
        if td and inst:
            wc = sw_ws.cell(row, wc_col).value if wc_col else None
            sd = sw_ws.cell(row, sd_col).value if sd_col else None
            ed = sw_ws.cell(row, ed_col).value if ed_col else None
            # Keep original types (datetime, not str!) for Excel MATCH compatibility
            switches.append((str(inst), td, wc, sd, ed))

    if not switches:
        print(f"  ⚠️ No switches found for {prod}, skipping")
        src_wb.close()
        return

    # ============================================================
    # 2. 创建或打开输出 workbook
    # ============================================================
    if inplace:
        # Incremental: open existing file, update _SWITCHES + MAIN only
        src_wb.close()
        wb = load_workbook(dst_path)
        # Remove old _SWITCHES and MAIN sheets (re-create with fresh formulas)
        for sn in ('_SWITCHES', 'MAIN'):
            if sn in wb.sheetnames:
                del wb[sn]
        sheet_rows = {}
        for sn in wb.sheetnames:
            n = wb[sn].max_row - 2
            if n > 0:
                sheet_rows[sn] = n
    else:
        # Full: create new workbook, copy contract sheets from test_1
        sheet_rows = {}
        for sn in sorted(src_sheets_set):
            n = src_wb[sn].max_row - 2
            if n > 0:
                sheet_rows[sn] = n

        wb = Workbook()
        active_sheet = wb.active
        if active_sheet is not None:
            wb.remove(active_sheet)

        # 2a. 复制合约 sheet 数据（从 test_1 直接 copy values）
        for sn in sorted(src_sheets_set):
            dst_ws = wb.create_sheet(sn)
            src_ct = src_wb[sn]
            for row_data in src_ct.iter_rows(values_only=True):
                dst_ws.append(list(row_data))
        src_wb.close()

    # ----------------------------------------------------------
    # Sheet 0: _SWITCHES (增强版 — 辅助列计算 adjust_mul)
    # ----------------------------------------------------------
    sw_out = wb.create_sheet('_SWITCHES', 0)

    # Row 1: remark (合并单元格 + 自动换行)
    sw_remark = (
        '切换记录 + 前复权因子计算（最新合约=1，历史数据反向累积）\n'
        '辅助列公式全部为 Excel 函数，不硬编码行号\n'
        '_cur_close:  INDEX(INDIRECT("\'"&本合约B&"\'!J:J"), MATCH(本合约D, INDIRECT("\'"&本合约B&"\'!A:A"), 0))\n'
        '_next_close: INDEX(INDIRECT("\'"&下一合约B&"\'!J:J"), MATCH(下一合约D, INDIRECT("\'"&下一合约B&"\'!A:A"), 0))\n'
        'adj_mul: IF(最后一行,1, _cur_close/_next_close * _next_adj)'
    )
    sw_out.cell(1, 1, sw_remark)
    sw_out.merge_cells(start_row=1, start_column=1, end_row=1, end_column=12)
    sw_out.row_dimensions[1].height = REMARK_ROW_HEIGHT
    sw_cell1 = sw_out.cell(1, 1)
    sw_cell1.fill = REMARK_FILL
    sw_cell1.font = REMARK_FONT
    sw_cell1.alignment = REMARK_ALIGNMENT

    # Row 2: header
    headers = ['trading_day', 'instrument_id', 'windcode', 'start_date', 'end_date',
               '_cur_close', '_next_close', '_next_adj', 'adjustment_mul', 'adjustment_add',
               '_nrows', '_ref_str']
    for ci, h in enumerate(headers, 1):
        sw_out.cell(2, ci, h).fill = HEADER_FILL

    # ---- 写入切换数据 + 公式 ----
    contracts_in_order = [s[0] for s in switches]

    for i, (inst, td, wc, sd, ed) in enumerate(switches):
        row = i + 3  # Excel row (1=remark, 2=header)

        # 基本数据 — 保持原始类型（datetime 不转 str，Excel MATCH 才能匹配）
        sw_out.cell(row, 1, td)
        sw_out.cell(row, 2, inst)
        sw_out.cell(row, 3, wc)
        sw_out.cell(row, 4, sd)
        sw_out.cell(row, 5, ed)

        # ---- _cur_close (F列) ----
        # =INDEX(INDIRECT("'"&本行B&"'!J:J"), MATCH(本行D, INDIRECT("'"&本行B&"'!A:A"), 0))
        # 本合约首日 (start_date) 的收盘价，用于计算复权比例
        cur_b = f'{_col_letter(2)}{row}'    # B: instrument_id 本行
        cur_d = f'{_col_letter(4)}{row}'    # D: start_date 本行
        cur_close_ref = f'INDIRECT("\'"&{cur_b}&"\'!J:J")'
        cur_td_ref = f'INDIRECT("\'"&{cur_b}&"\'!A:A")'  # A:A = trading_day
        formula = f'=INDEX({cur_close_ref},MATCH({cur_d},{cur_td_ref},0))'
        sw_out.cell(row, CUR_CLOSE_COL, formula).fill = FORMULA_FILL

        # ---- _next_close (G列) ----
        # =INDEX(INDIRECT("'"&下一行B&"'!J:J"), MATCH(下一行D, INDIRECT("'"&下一行B&"'!A:A"), 0))
        # 下一合约（更新合约）首日 (start_date) 的收盘价
        if i == len(switches) - 1:
            sw_out.cell(row, NEXT_CLOSE_COL, '').fill = FORMULA_FILL
        else:
            next_b = f'{_col_letter(2)}{row + 1}'
            next_d = f'{_col_letter(4)}{row + 1}'
            next_close_ref = f'INDIRECT("\'"&{next_b}&"\'!J:J")'
            next_td_ref = f'INDIRECT("\'"&{next_b}&"\'!A:A")'
            formula = f'=INDEX({next_close_ref},MATCH({next_d},{next_td_ref},0))'
            sw_out.cell(row, NEXT_CLOSE_COL, formula).fill = FORMULA_FILL

        # ---- _next_adj (H列): 下一行的 adjustment_mul ----
        if i == len(switches) - 1:
            sw_out.cell(row, NEXT_ADJ_COL, '').fill = FORMULA_FILL
        else:
            sw_out.cell(
                row, NEXT_ADJ_COL,
                f'={_col_letter(ADJ_MUL_COL)}{row + 1}'
            ).fill = FORMULA_FILL

        # ---- adjustment_mul (I列) ----
        # 前复权：最后一行=1，向前累积 _cur_close/_next_close * _next_adj
        if i == len(switches) - 1:
            sw_out.cell(row, ADJ_MUL_COL, 1).fill = FORMULA_FILL
        else:
            cc = _col_letter(CUR_CLOSE_COL)
            nc = _col_letter(NEXT_CLOSE_COL)
            na = _col_letter(NEXT_ADJ_COL)
            sw_out.cell(
                row, ADJ_MUL_COL,
                f'=IF({cc}{row}="","",IF({nc}{row}="","",{cc}{row}/{nc}{row}*{na}{row}))'
            ).fill = FORMULA_FILL

        # ---- adjustment_add ----
        sw_out.cell(row, ADJ_ADD_COL, 0).fill = FORMULA_FILL

        # ---- _nrows（纯数值，供 MAIN 公式使用）----
        sw_out.cell(row, SW_NROWS_COL, sheet_rows.get(inst, 0))

        # ---- _ref_str（Python 写入的文本字符串，如 'a2405'!A3:U14027）----
        # 对 INDIRECT 来说，这是纯文本值，不需要先求值公式
        ref_str = f"'{inst}'!A3:U{sheet_rows.get(inst, 0) + 2}"
        sw_out.cell(row, SW_REF_STR_COL, ref_str).fill = FORMULA_FILL

    # ----------------------------------------------------------
    # Sheet 2: MAIN (单公式 REDUCE+HSTACK+VSTACK — 13列数据+mul+add，无硬编码)
    # ----------------------------------------------------------
    # 核心洞察：
    #   1. REDUCE 初始值为标量 0，LAMBDA 内 VSTACK(acc, HSTACK(data, mul, add))
    #   2. HSTACK 在 VSTACK 的 LAMBDA 内没溢出问题（因为标量 init）
    #   3. DROP(,1) 去掉初始标量行
    # 公式无需知道合约数量，自动遍历 _SWITCHES!L3:L{N}
    main_ws = wb.create_sheet('MAIN', 1)

    sw_last_row = 2 + len(switches)
    sw_last_col_letter = _col_letter(SW_REF_STR_COL)  # L

    # Row 1: remark (合并单元格 + 自动换行)
    main_remark = (
        f'主力连续序列 — REDUCE+HSTACK+VSTACK 单公式 (23列含复权因子)\n'
        f'合约数 = {len(switches)}，公式不硬编码合约数量\n'
        f'A3 = DROP(REDUCE(0, _SWITCHES!L3:L{sw_last_row}, LAMBDA(acc,ref, ...)), 1)'
    )
    main_ws.cell(1, 1, main_remark)
    main_ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=MAIN_NCOLS)
    main_ws.row_dimensions[1].height = REMARK_ROW_HEIGHT
    main_cell1 = main_ws.cell(1, 1)
    main_cell1.fill = REMARK_FILL
    main_cell1.font = REMARK_FONT
    main_cell1.alignment = REMARK_ALIGNMENT

    # Row 2: header (21 数据列 + 2 adjustment 列)
    for ci, cn in enumerate(CONTRACT_COLS):
        main_ws.cell(2, ci + 1, cn).fill = HEADER_FILL
    main_ws.cell(2, MAIN_MUL_COL_OFFSET, 'adjustment_mul').fill = HEADER_FILL
    main_ws.cell(2, MAIN_ADD_COL_OFFSET, 'adjustment_add').fill = HEADER_FILL

    # --- A3: 单公式溢出 23 列 (A3:W{lastrow}) ---
    # REDUCE VSTACK 拼接各合约 HSTACK(数据21列, mul, add)，DROP 去掉初始标量
    # 一式溢出所有 23 列，日期格式由 XML <col style> 后处理控制
    #   <col style="xfDate"> → A/B/R 列溢出区域显示日期格式
    #   A3 的 s= 匹配第一列(A列=trading_day)的日期格式
    base_formula = (
        f'REDUCE(0,_SWITCHES!{sw_last_col_letter}3:{sw_last_col_letter}{sw_last_row},'
        f'LAMBDA(acc,ref,'
        f'LET(r,ROW(ref),'
        f'd,INDIRECT(ref),'
        f'm,EXPAND(INDEX(_SWITCHES!I:I,r),INDEX(_SWITCHES!K:K,r),1,INDEX(_SWITCHES!I:I,r)),'
        f'a,EXPAND(INDEX(_SWITCHES!J:J,r),INDEX(_SWITCHES!K:K,r),1,INDEX(_SWITCHES!J:J,r)),'
        f'VSTACK(acc,HSTACK(d,m,a))'
        f')))'
    )
    main_ws.cell(3, 1, f'=DROP({base_formula},1)').fill = FORMULA_FILL

    contracts_in_order = [s[0] for s in switches]
    total_rows = sum(sheet_rows.get(c, 0) for c in contracts_in_order)

    # ============================================================
    # 3. 保存（不预写单元格格式——用 XML <col style> 后处理）
    # ============================================================
    dst_path = TEST_2A_DIR / f'{prod}.xlsx'
    wb.save(dst_path)
    wb.close()

    # ============================================================
    # 4. XML 后处理：标记动态数组 + 公式 s= + <col style>
    #    <col style> 作用于溢出行（WPS 已验证有效）
    #    公式单元格 s= 作用于公式行（覆盖 <col style>）
    # ============================================================
    last_row = 2 + total_rows
    col_numfmts = _read_contract_col_numfmts_from_xml(dst_path)
    # 注入 <cols> + 修改 A3..W3 的 s= + 标记每个为动态数组
    _patch_multi_col_formulas(dst_path, 'MAIN', col_numfmts, total_rows)

    print(f' ✅ ({total_rows} rows, {len(switches)} contracts, {len(contracts_in_order)} in MAIN)')


def _read_contract_col_numfmts_from_xml(xlsx_path: Path) -> dict[int, int]:
    """
    从已保存的 xlsx 的 XML 层面读取合约 sheet 的列级 numFmtId。

    遍历样式表 styles.xml 的 cellXfs，找到合约数据行 cell 的 s=，
    映射到 numFmtId。
    """
    import zipfile as _zf
    with _zf.ZipFile(xlsx_path, 'r') as zf:
        # 解析 styles.xml
        styles = ET.parse(zf.open('xl/styles.xml'))
        styles_root = styles.getroot()
        cellXfs = styles_root.find(f'{{{NS_SHEET}}}cellXfs')
        if cellXfs is None:
            return {}
        xf_list = cellXfs.findall(f'{{{NS_SHEET}}}xf')
        numFmts = styles_root.find(f'{{{NS_SHEET}}}numFmts')

        # 找到合约 sheet（非 _SWITCHES, 非 MAIN）
        wb_xml = ET.parse(zf.open('xl/workbook.xml'))
        for sh in wb_xml.getroot().findall(f'{{{NS_SHEET}}}sheets/{{{NS_SHEET}}}sheet'):
            sn = sh.get('name')
            if sn in ('_SWITCHES', 'MAIN'):
                continue
            # 找这个 sheet 文件
            r_id = sh.get(f'{{{NS_R}}}id')
            rels_xml = ET.parse(zf.open('xl/_rels/workbook.xml.rels'))
            target = None
            for rel in rels_xml.getroot():
                if rel.get('Id') == r_id:
                    t = rel.get('Target')
                    if t is not None:
                        target = t.lstrip('/')
                    break
            if target is None:
                continue

            sheet = ET.parse(zf.open(target))
            s_root = sheet.getroot()
            # 找 row 3
            result = {}
            for row in s_root.findall(f'{{{NS_SHEET}}}sheetData/{{{NS_SHEET}}}row'):
                if row.get('r') == '3':
                    for c in row.findall(f'{{{NS_SHEET}}}c'):
                        r = c.get('r')
                        if r is None:
                            continue
                        s = c.get('s')
                        if s is None:
                            continue
                        si = int(s)
                        if si < len(xf_list):
                            nfi = xf_list[si].get('numFmtId')
                            if nfi is not None and nfi != '0':
                                # 找到列号
                                col_idx = _col_idx(r)
                                result[col_idx] = int(nfi)
                    break
            return result
    return {}


def _patch_multi_col_formulas(xlsx_path: Path, sheet_name: str,
                              col_numfmts: dict[int, int],
                              total_data_rows: int):
    """
    XML 后处理：给 MAIN sheet 的 A3..W3 每列标记为独立的动态数组公式，
    并设置正确的 s= (style index) 从 col_numfmts 映射。

    每列公式 =CHOOSECOLS(DROP(REDUCE(...), 1), col_N)
    需要标记 ca="1" t="array" ref="A3:A{last_row+1}" 等。
    """
    # 1. numFmtId → xfId 映射（从 styles.xml）
    with zipfile.ZipFile(xlsx_path, 'r') as zf:
        styles = ET.parse(zf.open('xl/styles.xml'))
        xf_list = styles.getroot().findall(f'{{{NS_SHEET}}}cellXfs/{{{NS_SHEET}}}xf')
        nfi_to_xf = {}
        for i, xf in enumerate(xf_list):
            nfi = xf.get('numFmtId')
            if nfi is not None:
                nfi_to_xf[int(nfi)] = i

        # 2. 找 sheet 文件
        wb_xml = ET.parse(zf.open('xl/workbook.xml'))
        rel_target = None
        for sh in wb_xml.getroot().findall(f'{{{NS_SHEET}}}sheets/{{{NS_SHEET}}}sheet'):
            if sh.get('name') == sheet_name:
                r_id = sh.get(f'{{{NS_R}}}id')
                rels = ET.parse(zf.open('xl/_rels/workbook.xml.rels'))
                for rel in rels.getroot():
                    if rel.get('Id') == r_id:
                        t = rel.get('Target')
                        if t is not None:
                            rel_target = t.lstrip('/')
                        break
                break

        if rel_target is None:
            print(f'  ⚠️ Sheet "{sheet_name}" not found')
            return

        sheet = ET.parse(zf.open(rel_target))
        sheet_root = sheet.getroot()

        # 3. 注入 <cols> — 为日期列设 style（引用 cellXfs index）
        #    WPS 动态数组溢出区域继承 <col style>，但公式单元格自身
        #    的 s= 会覆盖列级样式，所以公式单元格也设 s=
        cols = sheet_root.find(f'{{{NS_SHEET}}}cols')
        if cols is not None:
            sheet_root.remove(cols)
        cols_el = ET.Element(f'{{{NS_SHEET}}}cols')
        for ci in range(1, MAIN_NCOLS + 1):
            col_el = ET.SubElement(cols_el, f'{{{NS_SHEET}}}col')
            col_el.set('min', str(ci))
            col_el.set('max', str(ci))
            col_el.set('width', '13')
            col_el.set('customWidth', '1')
            # 日期列：注入 style 指向日期格式的 cellXfs
            if ci in col_numfmts:
                xf_id = nfi_to_xf.get(col_numfmts[ci])
                if xf_id is not None:
                    col_el.set('style', str(xf_id))
        sheet_root.insert(0, cols_el)

        # 4. A3 单公式溢出 23 列 — 标记动态数组 ref=A3:W{safe_ref_end}
        #    s= 取自 A 列(trading_day)的日期格式
        last_row = 2 + total_data_rows
        safe_ref_end = last_row + 1

        # A 列日期 xfId（用于 A3 的 s=）
        a_xf_id = nfi_to_xf.get(col_numfmts.get(1, 0), 0)

        for row in sheet_root.findall(f'{{{NS_SHEET}}}sheetData/{{{NS_SHEET}}}row'):
            if row.get('r') == '3':
                for c in row.findall(f'{{{NS_SHEET}}}c'):
                    r = c.get('r')
                    if r != 'A3':
                        continue
                    f_el = c.find(f'{{{NS_SHEET}}}f')
                    if f_el is not None:
                        f_el.set('ca', '1')
                        f_el.set('t', 'array')
                        f_el.set('ref', f'A3:W{safe_ref_end}')
                        c.set('cm', '1')
                    c.set('s', str(a_xf_id))
                    break
                break

        # 5. 收集并重写
        all_files = {}
        for name in zf.namelist():
            if name != rel_target:
                all_files[name] = zf.read(name)
        all_files[rel_target] = ET.tostring(sheet_root, xml_declaration=True, encoding='UTF-8')

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.xlsx')
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf_out:
            for name, data in all_files.items():
                zf_out.writestr(name, data)
        shutil.move(tmp_path, str(xlsx_path))
    finally:
        if Path(tmp_path).exists():
            Path(tmp_path).unlink(missing_ok=True)

    print(f'  🔧 Patched MAIN!A3: single dynamic array A3:W{safe_ref_end} + col styles')


def _xml_tostring(root):
    """Serialize XML element to bytes with XML declaration."""
    return ET.tostring(root, xml_declaration=True, encoding='UTF-8')


def _inject_col_formats(sheet_root, col_formats: dict[int, str]):
    """
    Inject <cols><col numFmtId="..."/></cols> into sheet XML so that dynamic
    array spill columns display dates/datetimes correctly.

    Uses only standard Excel numFmtId values that are available in every
    workbook without needing to modify styles.xml:
      14 = 'dd/mm/yyyy' (or regional date format)
      22 = 'dd/mm/yyyy h:mm'

    Note: the exact display format varies by locale.  For zh-CN Excel,
    numFmtId 14 typically displays as 'yyyy/mm/dd' or 'yyyy-mm-dd'.
    """
    cols = sheet_root.find(f'{{{NS_SHEET}}}cols')
    if cols is None:
        sheet_data = sheet_root.find(f'{{{NS_SHEET}}}sheetData')
        cols = ET.Element(f'{{{NS_SHEET}}}cols')
        if sheet_data is not None:
            sheet_root.insert(list(sheet_root).index(sheet_data), cols)
        else:
            sheet_root.insert(0, cols)

    # Remove any existing <col> for our indices
    our_indices = set(col_formats.keys())
    for ec in list(cols.findall(f'{{{NS_SHEET}}}col')):
        ec_min = int(ec.get('min', '0'))
        ec_max = int(ec.get('max', '0'))
        if not our_indices.isdisjoint(range(ec_min, ec_max + 1)):
            cols.remove(ec)

    for col_idx, fmt in sorted(col_formats.items()):
        col_el = ET.SubElement(cols, f'{{{NS_SHEET}}}col')
        col_el.set('min', str(col_idx))
        col_el.set('max', str(col_idx))
        col_el.set('customFormat', '1')
        if 'h:mm' in fmt:
            col_el.set('numFmtId', '22')
        else:
            col_el.set('numFmtId', '14')



def main():
    print("test_2a: Excel-formula adjustment verification (INDEX/MATCH, in-file)")
    print("=" * 60)
    print("\n⛔ Note: test_1 data is NOT re-run.")
    print("   Contract data copied from test_1 (no INDIRECT cross-file refs)")
    print(f"   Source: {TEST_1_DIR}")
    print(f"   Output: {TEST_2A_DIR}")

    # 确保输出目录存在（不清空，支持增量更新）
    TEST_2A_DIR.mkdir(parents=True, exist_ok=True)

    # 🔧 DEBUG: 只跑 A.xlsx
    xlsx_path = TEST_1_DIR / 'A.xlsx'
    if xlsx_path.exists():
        process_product(xlsx_path)

    print(f"\nDone! Output: {TEST_2A_DIR}")


if __name__ == '__main__':
    main()
