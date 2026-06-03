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
  _prev_close: =INDEX(INDIRECT("'"&上一行B&"'!G:G"), MATCH(上一行E, INDIRECT("'"&上一行B&"'!B:B"), 0))
      通过上一行 instrument_id (B列) 动态获取前合约 sheet 名，不硬编码
  _cur_close:  =INDEX(INDIRECT("'"&本行B&"'!G:G"), MATCH(本行D, INDIRECT("'"&本行B&"'!B:B"), 0))
      通过本行 instrument_id (B列) 动态获取本合约 sheet 名，不硬编码
  _prev_adj:   上一行的 adjustment_mul
  adjustment_mul: =IF(第一行, 1, _prev_close/_cur_close * _prev_adj)
  adjustment_add: =0

MAIN sheet（三列独立 VSTACK，各自溢出）：
  A3 = VSTACK(INDIRECT(_SWITCHES!L3), ...)  — 合约 11 列数据（不包 HSTACK）
  L3 = VSTACK(EXPAND(_SWITCHES!I3,...), ...)  — adjustment_mul
  M3 = VSTACK(EXPAND(_SWITCHES!J3,...), ...)  — adjustment_add
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
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from tests.calc import TEST_1_DIR, TEST_2A_DIR

# --- XML 命名空间 ---
NS_CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS_SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_MD = 'http://schemas.openxmlformats.org/spreadsheetml/2006/9/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS_RELS = 'http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('', NS_SHEET)
ET.register_namespace('r', NS_R)
ET.register_namespace('x14', NS_MD)

# --- 样式 ---
FORMULA_FILL = PatternFill(start_color='FFFFF2CC', end_color='FFFFF2CC', fill_type='solid')
HEADER_FILL = PatternFill(start_color='FFD9E1F2', end_color='FFD9E1F2', fill_type='solid')


def _col_letter(idx: int) -> str:
    return get_column_letter(idx)


# test_1 合约 sheet 列布局 (row1=remark, row2=header, row3+=data)
# A=trade_time, B=trading_day, C=instrument_id, D=open_price, E=highest_price,
# F=lowest_price, G=close_price, H=settlement_price, I=volume, J=turnover, K=open_interest
CONTRACT_COLS = [
    'trade_time', 'trading_day', 'instrument_id',
    'open_price', 'highest_price', 'lowest_price', 'close_price', 'settlement_price',
    'volume', 'turnover', 'open_interest',
]
CONTRACT_CLOSE_COL = 7      # G: close_price
CONTRACT_TD_COL = 2          # B: trading_day
DATA_START_ROW = 3           # 数据从第3行开始 (1=remark, 2=header)

# _SWITCHES 列定义
# A=trading_day, B=instrument_id, C=windcode, D=start_date, E=end_date
# F=_prev_close, G=_cur_close, H=_prev_adj, I=adjustment_mul, J=adjustment_add
# K=_nrows, L=_ref_str, M=_cum_offset, N=_ref_str_full
#
# _ref_str:      Python 写入纯文本，如 'a2405'!A3:K14027，供 INDIRECT 使用
# _cum_offset:   该合约在 _SWITCHES 数据块中的起始行（用于独立溢出 adjustment）
# _ref_str_full: Python 写入纯文本，如 'a2405'!A3:M14027（含 adjustment 列，13列）
#                但合约 sheet 只有 11 列...不行
#
# 实际用 _BLOCKS 辅助 sheet：
#   每个合约一行，用 INDIRECT 溢出 11 列数据 + 2 列 adjustment（独立溢出区域，互不重叠）
# MAIN 直接 VSTACK(_BLOCKS!A3#, _BLOCKS!A4#, ...) 或用 INDIRECT 取 _BLOCKS 的溢出区域
SW_ORIG_COLS = 5
PREV_CLOSE_COL = SW_ORIG_COLS + 1  # F=6
CUR_CLOSE_COL = SW_ORIG_COLS + 2   # G=7
PREV_ADJ_COL = SW_ORIG_COLS + 3    # H=8
ADJ_MUL_COL = SW_ORIG_COLS + 4     # I=9
ADJ_ADD_COL = SW_ORIG_COLS + 5     # J=10
SW_NROWS_COL = SW_ORIG_COLS + 6    # K=11: _nrows
SW_REF_STR_COL = SW_ORIG_COLS + 7  # L=12: _ref_str

# MAIN 列布局 (11 数据列 + 2 adjustment 列 = 13 列, A..M)
# A..K = 合约数据, L=adjustment_mul, M=adjustment_add
MAIN_NCOLS = len(CONTRACT_COLS) + 2  # 13
MAIN_MUL_COL_OFFSET = len(CONTRACT_COLS) + 1  # L=12 (在 13 列中的位置)
MAIN_ADD_COL_OFFSET = len(CONTRACT_COLS) + 2  # M=13


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
        wb.remove(wb.active)

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

    # Row 1: remark
    sw_out.cell(
        1, 1,
        '切换记录 + 复权因子计算\n'
        '辅助列公式全部为 Excel 函数，不硬编码行号\n'
        '_prev_close: INDEX(前合约!G:G, MATCH(end_date, 前合约!B:B, 0))\n'
        '_cur_close:  INDEX(本合约!G:G, MATCH(start_date, 本合约!B:B, 0))\n'
        'adj_mul: IF(第一行,1, _prev_close/_cur_close * _prev_adj)'
    )

    # Row 2: header
    headers = ['trading_day', 'instrument_id', 'windcode', 'start_date', 'end_date',
               '_prev_close', '_cur_close', '_prev_adj', 'adjustment_mul', 'adjustment_add',
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

        # ---- _prev_close ----
        # =INDEX(INDIRECT("'"&上一行B&"'!G:G"), MATCH(上一行E, INDIRECT("'"&上一行B&"'!B:B"), 0))
        # 不硬编码 sheet 名：通过上一行 instrument_id (B列) 动态获取前合约 sheet 名
        if i == 0:
            sw_out.cell(row, PREV_CLOSE_COL, '').fill = FORMULA_FILL
        elif i > 0:
            prev_b = f'{_col_letter(2)}{row - 1}'   # B: instrument_id 上一行
            prev_e = f'{_col_letter(5)}{row - 1}'   # E: end_date 上一行
            prev_g_ref = f'INDIRECT("\'"&{prev_b}&"\'!G:G")'
            prev_b_ref = f'INDIRECT("\'"&{prev_b}&"\'!B:B")'
            formula = f'=INDEX({prev_g_ref},MATCH({prev_e},{prev_b_ref},0))'
            sw_out.cell(row, PREV_CLOSE_COL, formula).fill = FORMULA_FILL

        # ---- _cur_close ----
        # =INDEX(INDIRECT("'"&本行B&"'!G:G"), MATCH(本行D, INDIRECT("'"&本行B&"'!B:B"), 0))
        cur_b = f'{_col_letter(2)}{row}'    # B: instrument_id 本行
        cur_d = f'{_col_letter(4)}{row}'    # D: start_date 本行
        cur_g_ref = f'INDIRECT("\'"&{cur_b}&"\'!G:G")'
        cur_b_ref = f'INDIRECT("\'"&{cur_b}&"\'!B:B")'
        formula = f'=INDEX({cur_g_ref},MATCH({cur_d},{cur_b_ref},0))'
        sw_out.cell(row, CUR_CLOSE_COL, formula).fill = FORMULA_FILL

        # ---- _prev_adj: 上一行的 adjustment_mul ----
        if i == 0:
            sw_out.cell(row, PREV_ADJ_COL, 1).fill = FORMULA_FILL
        else:
            sw_out.cell(
                row, PREV_ADJ_COL,
                f'={_col_letter(ADJ_MUL_COL)}{row - 1}'
            ).fill = FORMULA_FILL

        # ---- adjustment_mul ----
        if i == 0:
            sw_out.cell(row, ADJ_MUL_COL, 1).fill = FORMULA_FILL
        else:
            pc = _col_letter(PREV_CLOSE_COL)
            cc = _col_letter(CUR_CLOSE_COL)
            pa = _col_letter(PREV_ADJ_COL)
            sw_out.cell(
                row, ADJ_MUL_COL,
                f'=IF({pc}{row}="","",IF({cc}{row}="","",{pc}{row}/{cc}{row}*{pa}{row}))'
            ).fill = FORMULA_FILL

        # ---- adjustment_add ----
        sw_out.cell(row, ADJ_ADD_COL, 0).fill = FORMULA_FILL

        # ---- _nrows（纯数值，供 MAIN 公式使用）----
        sw_out.cell(row, SW_NROWS_COL, sheet_rows.get(inst, 0))

        # ---- _ref_str（Python 写入的文本字符串，如 'a2405'!A3:K14027）----
        # 对 INDIRECT 来说，这是纯文本值，不需要先求值公式
        ref_str = f"'{inst}'!A3:K{sheet_rows.get(inst, 0) + 2}"
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

    # Row 1: remark
    main_ws.cell(
        1, 1,
        f'主力连续序列 — REDUCE+HSTACK+VSTACK 单公式 (13列含复权因子)\n'
        f'合约数 = {len(switches)}，公式不硬编码合约数量\n'
        f'A3 = DROP(REDUCE(0, _SWITCHES!L3:L{sw_last_row}, LAMBDA(acc,ref, ...)), 1)'
    )

    # Row 2: header (11 数据列 + 2 adjustment 列)
    for ci, cn in enumerate(CONTRACT_COLS):
        main_ws.cell(2, ci + 1, cn).fill = HEADER_FILL
    main_ws.cell(2, MAIN_MUL_COL_OFFSET, 'adjustment_mul').fill = HEADER_FILL
    main_ws.cell(2, MAIN_ADD_COL_OFFSET, 'adjustment_add').fill = HEADER_FILL

    # --- A3: 单公式 — REDUCE 遍历 ref_str，HSTACK(data, mul, add)，VSTACK 累积 ---
    # =DROP(
    #   REDUCE(0, _SWITCHES!L3:L{N},
    #     LAMBDA(acc, ref,
    #       LET(
    #         r, ROW(ref),                    -- _SWITCHES 行号
    #         data, INDIRECT(ref),            -- 11 列合约数据
    #         mul, EXPAND(INDEX(_SWITCHES!I:I,r), INDEX(_SWITCHES!K:K,r), 1, INDEX(_SWITCHES!I:I,r)),
    #         add, EXPAND(INDEX(_SWITCHES!J:J,r), INDEX(_SWITCHES!K:K,r), 1, INDEX(_SWITCHES!J:J,r)),
    #         VSTACK(acc, HSTACK(data, mul, add))
    #       )
    #     )
    #   ), 1
    # )
    formula = (
        f'=DROP('
        f'REDUCE(0,_SWITCHES!{sw_last_col_letter}3:{sw_last_col_letter}{sw_last_row},'
        f'LAMBDA(acc,ref,'
        f'LET(r,ROW(ref),'
        f'd,INDIRECT(ref),'
        f'm,EXPAND(INDEX(_SWITCHES!I:I,r),INDEX(_SWITCHES!K:K,r),1,INDEX(_SWITCHES!I:I,r)),'
        f'a,EXPAND(INDEX(_SWITCHES!J:J,r),INDEX(_SWITCHES!K:K,r),1,INDEX(_SWITCHES!J:J,r)),'
        f'VSTACK(acc,HSTACK(d,m,a))'
        f'))),'
        f'1)'
    )
    main_ws.cell(3, 1, formula).fill = FORMULA_FILL

    contracts_in_order = [s[0] for s in switches]
    total_rows = sum(sheet_rows.get(c, 0) for c in contracts_in_order)

    # ============================================================
    # 3. 保存
    # ============================================================
    dst_path = TEST_2A_DIR / f'{prod}.xlsx'
    wb.save(dst_path)
    wb.close()

    # ============================================================
    # 4. XML 后处理：标记 MAIN!A3 为动态数组公式（ca="1"）
    #    防止 WPS/Excel 自动插入 @ implicit intersection operator
    # ============================================================
    _patch_dynamic_array_formula(dst_path, 'MAIN', 'A3')

    print(f' ✅ ({total_rows} rows, {len(switches)} contracts, {len(contracts_in_order)} in MAIN)')


def _patch_dynamic_array_formula(xlsx_path: Path, sheet_name: str, cell_ref: str):
    """
    在 xlsx 的 XML 层面标记指定单元格为动态数组公式。

    修改 sheet XML 中 <f> 元素加 ca="1" 属性，
    并在 cell 元素加 cm="1" vm="1" 属性。
    同时创建/更新 metadata.xml 声明 vm="1"。
    """
    # 1. 读 workbook.xml 找 sheetId → rId → sheet 文件名
    with zipfile.ZipFile(xlsx_path, 'r') as zf:
        wb_xml = ET.parse(zf.open('xl/workbook.xml'))
        wb_root = wb_xml.getroot()
        rel_target = None
        for sh in wb_root.findall(f'{{{NS_SHEET}}}sheets/{{{NS_SHEET}}}sheet'):
            if sh.get('name') == sheet_name:
                r_id = sh.get(f'{{{NS_R}}}id')
                # 2. 读 workbook.xml.rels 找文件名 (target 相对于 xl/)
                rels_xml = ET.parse(zf.open('xl/_rels/workbook.xml.rels'))
                for rel in rels_xml.getroot():
                    if rel.get('Id') == r_id:
                        rel_target = rel.get('Target').lstrip('/')
                        break
                break

        if rel_target is None:
            print(f'  ⚠️ Sheet "{sheet_name}" not found, skipping XML patch')
            return

        # rel_target 已是完整的 zip 内路径如 "xl/worksheets/sheet2.xml"
        full_sheet_file = rel_target

        # 3. 读 sheet XML
        sheet_xml = ET.parse(zf.open(full_sheet_file))
        sheet_root = sheet_xml.getroot()

        # 4. 找到指定 cell 的 <c> 和 <f>
        match = re.match(r'([A-Z]+)(\d+)', cell_ref)
        if not match:
            print(f'  ⚠️ Invalid cell_ref "{cell_ref}"')
            return
        col_letter, row_num = match.groups()
        found = False
        for row in sheet_root.findall(f'{{{NS_SHEET}}}sheetData/{{{NS_SHEET}}}row'):
            if row.get('r') == row_num:
                for cell in row.findall(f'{{{NS_SHEET}}}c'):
                    if cell.get('r') == cell_ref:
                        f_el = cell.find(f'{{{NS_SHEET}}}f')
                        if f_el is not None:
                            f_el.set('ca', '1')
                            cell.set('cm', '1')
                            cell.set('vm', '1')
                            found = True
                        break
                break

        if not found:
            print(f'  ⚠️ Cell {cell_ref} not found in {sheet_name}, skipping XML patch')
            return

        # 5. 读/建 metadata.xml
        md_file = 'xl/metadata.xml'
        try:
            md_xml = ET.parse(zf.open(md_file))
            md_root = md_xml.getroot()
        except KeyError:
            md_root = ET.Element(f'{{{NS_MD}}}metadata')

        vm_el = md_root.find(f'{{{NS_MD}}}valueMetadata')
        if vm_el is None:
            vm_el = ET.SubElement(md_root, f'{{{NS_MD}}}valueMetadata')
        else:
            vm_el.clear()
        ET.SubElement(vm_el, f'{{{NS_MD}}}bk')

        # 6. 读 Content_Types
        ct_xml = ET.parse(zf.open('[Content_Types].xml'))
        ct_root = ct_xml.getroot()

        # 确保 metadata.xml 在 Content_Types 中声明
        part_name = '/xl/metadata.xml'
        has_md = any(ov.get('PartName') == part_name
                     for ov in ct_root.findall(f'{{{NS_CT}}}Override'))
        if not has_md:
            ET.SubElement(ct_root, f'{{{NS_CT}}}Override',
                          PartName=part_name,
                          ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheetMetadata+xml')

        # 7. 收集所有文件，替换修改过的
        all_files = {}
        for name in zf.namelist():
            if name not in (full_sheet_file, md_file, '[Content_Types].xml'):
                all_files[name] = zf.read(name)

        all_files[full_sheet_file] = _xml_tostring(sheet_root)
        all_files[md_file] = _xml_tostring(md_root)
        all_files['[Content_Types].xml'] = _xml_tostring(ct_root)

    # 8. 重写 xlsx（在 with 外，使用收集好的数据）
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

    print(f'  🔧 Patched {cell_ref} as dynamic array formula (ca="1")')


def _xml_tostring(root):
    """Serialize XML element to bytes with XML declaration."""
    return ET.tostring(root, xml_declaration=True, encoding='UTF-8')


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
