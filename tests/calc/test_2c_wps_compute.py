#!/usr/bin/env python3
"""
test_2c_wps_compute.py — 自动用 WPS Office 打开 test_2a 的 xlsx，
等待公式计算完成后自动保存并关闭。

用法:
  python tests/calc/test_2c_wps_compute.py              # 处理全部 88 个品种
  python tests/calc/test_2c_wps_compute.py A B C        # 只处理指定品种
  python tests/calc/test_2c_wps_compute.py --wait-scale 2.0  # 保守模式，等 2 倍时间
  python tests/calc/test_2c_wps_compute.py --force A    # 即使已 DONE 也重跑
  python tests/calc/test_2c_wps_compute.py --verify-only # 只检查全部品种是否 DONE

流程:
  1. 用 openpyxl(data_only=True) 读取 _SWITCHES!Z1，若已为 "DONE" 则跳过
  2. open -a WPS Office 打开 xlsx
  3. 立刻触发一次保存，让 WPS 开始计算并落盘公式缓存
  4. 轮询 _SWITCHES!Z2 保存计数 + _SWITCHES!Z1 DONE
  5. 用 WPS 的 Quit and Close All Windows 退出，避免下一个品种继承旧 tab
  6. 再次用 openpyxl(data_only=True) 验证 _SWITCHES!Z1 == "DONE"

依赖:
  - macOS + WPS Office (/Applications/wpsoffice.app)
  - 系统偏好设置 → 隐私与安全性 → 辅助功能 → 已授权终端/VS Code
"""

import subprocess
import sys
import zipfile
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from tests.calc import TEST_2A_DIR

# ============================================================
# 配置
# ============================================================

WPS_APP = '/Applications/wpsoffice.app'
SAVE_POLL_INTERVAL = 5          # 保存后每 5 秒检测落盘
RETRY_WAIT = 5                  # CALC 后等 5 秒再保存
MAX_RETRIES = 20                # 最多重试 20 次（10+5×20 = 110s ≈ 2 min）
OPEN_SAVE_DELAY = 2             # 打开后尽快保存，但留一点时间让 WPS 建立窗口

FORMULA_FILL = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')
NS_SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
MAIN_COL_STYLE_TARGETS = {
    1: 'date',      # A: trading_day
    2: 'datetime',  # B: trade_time
    18: 'datetime', # R: datetime-like source column
}
DATE_NUMFMT = 'yyyy\\-mm\\-dd'
DATETIME_NUMFMT = 'yyyy\\-mm\\-dd\\ h:mm:ss'


@dataclass(frozen=True)
class WorkbookStatus:
    product: str
    path: Path
    done: bool
    z1: str | None
    z2: int | None
    error: str | None = None

# ============================================================
# 工具函数
# ============================================================

def patch_flag(xlsx_path: Path, save_target: int) -> None:
    """给 _SWITCHES!Z1 写入完成 flag，并给 Z2 写入本轮保存计数公式。
    
    Z1 = IF(ISNUMBER(MAIN!右下角),"DONE","CALC")
    Z2 = IF(Z1="DONE", save_target, 0)

    Z2 必须在 WPS 打开前写成公式。打开后再用 openpyxl 修改同一个 xlsx，
    WPS 当前工作簿不会可靠地接收这次修改，还可能触发外部修改冲突。
    在 MAIN row 2 表头中扫描找到 adjustment_mul 列，
    用它作为检测列（REDUCE+VSTACK 全部溢出后一定有值）。
    """
    try:
        wb = load_workbook(xlsx_path)
        sw = wb['_SWITCHES']
        main = wb['MAIN']
        
        # 在 MAIN row 2 中找 "adjustment_mul" 列
        adj_mul_col = None
        for col in range(1, main.max_column + 1):
            val = main.cell(2, col).value
            if val and str(val).strip() == 'adjustment_mul':
                adj_mul_col = col
                break
        
        if adj_mul_col is None:
            # 找不到就回退到最后非空列 - 1
            for col in range(main.max_column, 0, -1):
                if main.cell(2, col).value is not None:
                    adj_mul_col = col - 1
                    break
        
        adj_mul_letter = get_column_letter(adj_mul_col or 1)
        
        # 合约数
        n_contracts = sw.max_row - 2 if sw.max_row else 0
        
        # 右下角 = adjustment_mul 列 × 最后一行
        corner_row = 2 + n_contracts
        corner_cell = f'{adj_mul_letter}{corner_row}'
        
        z1_formula = f'=IF(ISNUMBER(MAIN!{corner_cell}),"DONE","CALC")'
        z2_formula = f'=IF(Z1="DONE",{int(save_target)},0)'
        sw.cell(1, 26, z1_formula).fill = FORMULA_FILL
        sw.cell(2, 26, z2_formula).fill = FORMULA_FILL
        
        wb.save(xlsx_path)
        wb.close()
    except Exception as e:
        print(f'  ⚠️ patch_flag failed: {e}', flush=True)

def read_z1(xlsx_path: Path) -> str | None:
    """读取 _SWITCHES!Z1 计算完成 flag"""
    return _read_switches_cell(xlsx_path, 1, 26)


def read_z2(xlsx_path: Path) -> int | None:
    """读取 _SWITCHES!Z2 保存计数"""
    try:
        val = _read_switches_cell(xlsx_path, 2, 26)
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _read_switches_cell(xlsx_path: Path, row: int, col: int) -> str | None:
    """通用读取 _SWITCHES 单元格（data_only=True）"""
    try:
        wb = load_workbook(xlsx_path, read_only=True, data_only=True)
        sw = wb['_SWITCHES']
        val = sw.cell(row, col).value
        wb.close()
        return str(val).strip() if val is not None else None
    except Exception:
        return None


def _load_main_sheet_style_context(
    xlsx_path: Path,
) -> tuple[dict[int, str], ET.Element, ET.Element, str] | None:
    """Load styles.xml and MAIN sheet XML plus its styled columns map."""
    try:
        zf = zipfile.ZipFile(xlsx_path, 'r')
    except Exception:
        return None

    try:
        styles_root = ET.fromstring(zf.read('xl/styles.xml'))
        workbook = ET.fromstring(zf.read('xl/workbook.xml'))
        rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))

        main_rid = None
        for sheet in workbook.findall(f'{{{NS_SHEET}}}sheets/{{{NS_SHEET}}}sheet'):
            if sheet.get('name') == 'MAIN':
                main_rid = sheet.get(f'{{{NS_R}}}id')
                break
        if main_rid is None:
            return None

        target = None
        for rel in rels:
            if rel.get('Id') == main_rid:
                raw = rel.get('Target')
                if raw is None:
                    break
                target = raw.lstrip('/')
                if not target.startswith('xl/'):
                    target = f'xl/{target}'
                break
        if target is None:
            return None

        sheet_root = ET.fromstring(zf.read(target))
        cols = sheet_root.find(f'{{{NS_SHEET}}}cols')

        styled_cols: dict[int, str] = {}
        if cols is not None:
            for col in cols.findall(f'{{{NS_SHEET}}}col'):
                style = col.get('style')
                if style is None:
                    continue
                cmin = int(col.get('min', '0'))
                cmax = int(col.get('max', '0'))
                for ci in range(cmin, cmax + 1):
                    styled_cols[ci] = style

        return styled_cols, styles_root, sheet_root, target
    finally:
        zf.close()


def _numfmt_by_xf(styles_root: ET.Element) -> dict[int, str]:
    custom_numfmts = {
        int(nf.get('numFmtId', '0')): nf.get('formatCode', '')
        for nf in styles_root.findall(f'{{{NS_SHEET}}}numFmts/{{{NS_SHEET}}}numFmt')
    }
    builtins = {
        14: 'mm-dd-yy',
        22: 'm/d/yy h:mm',
    }
    formats: dict[int, str] = {}
    for idx, xf in enumerate(styles_root.findall(f'{{{NS_SHEET}}}cellXfs/{{{NS_SHEET}}}xf')):
        numfmt_id = int(xf.get('numFmtId', '0'))
        formats[idx] = custom_numfmts.get(numfmt_id, builtins.get(numfmt_id, 'General'))
    return formats


def _format_kind(format_code: str) -> str | None:
    fmt = format_code.lower().replace('\\-', '-').replace('\\ ', ' ')
    has_date = 'y' in fmt and 'm' in fmt and 'd' in fmt
    has_time = 'h' in fmt and 's' in fmt
    if has_date and has_time:
        return 'datetime'
    if has_date:
        return 'date'
    return None


def main_spill_styles_ok(xlsx_path: Path) -> bool:
    """Return True when MAIN has the required column styles.

    We intentionally validate <col style>, not every cached spill cell. WPS can
    preserve column style inheritance even when materialized spill cells omit s=.
    """
    loaded = _load_main_sheet_style_context(xlsx_path)
    if loaded is None:
        return False
    styled_cols, styles_root, _sheet_root, _target = loaded
    xf_formats = _numfmt_by_xf(styles_root)

    for col_idx, expected_kind in MAIN_COL_STYLE_TARGETS.items():
        style = styled_cols.get(col_idx)
        if style is None:
            return False
        actual_kind = _format_kind(xf_formats.get(int(style), ''))
        if actual_kind != expected_kind:
            return False
    return True


def _ensure_numfmt_xf(styles_root: ET.Element, format_code: str) -> int:
    numFmts = styles_root.find(f'{{{NS_SHEET}}}numFmts')
    if numFmts is None:
        numFmts = ET.Element(f'{{{NS_SHEET}}}numFmts')
        styles_root.insert(0, numFmts)

    for nf in numFmts.findall(f'{{{NS_SHEET}}}numFmt'):
        if nf.get('formatCode') == format_code:
            numfmt_id = int(nf.get('numFmtId', '0'))
            break
    else:
        existing_ids = [
            int(nf.get('numFmtId', '0'))
            for nf in numFmts.findall(f'{{{NS_SHEET}}}numFmt')
        ]
        numfmt_id = max([163, *existing_ids]) + 1
        nf = ET.SubElement(numFmts, f'{{{NS_SHEET}}}numFmt')
        nf.set('numFmtId', str(numfmt_id))
        nf.set('formatCode', format_code)
        numFmts.set('count', str(len(numFmts.findall(f'{{{NS_SHEET}}}numFmt'))))

    cellXfs = styles_root.find(f'{{{NS_SHEET}}}cellXfs')
    if cellXfs is None:
        cellXfs = ET.SubElement(styles_root, f'{{{NS_SHEET}}}cellXfs')
        cellXfs.set('count', '0')

    for idx, xf in enumerate(cellXfs.findall(f'{{{NS_SHEET}}}xf')):
        if xf.get('numFmtId') == str(numfmt_id):
            return idx

    xf_list = cellXfs.findall(f'{{{NS_SHEET}}}xf')
    base_xf = xf_list[0] if xf_list else None
    new_xf = ET.SubElement(cellXfs, f'{{{NS_SHEET}}}xf')
    if base_xf is not None:
        for attr in ('fontId', 'fillId', 'borderId', 'xfId'):
            value = base_xf.get(attr)
            if value is not None:
                new_xf.set(attr, value)
    else:
        new_xf.set('fontId', '0')
        new_xf.set('fillId', '0')
        new_xf.set('borderId', '0')
        new_xf.set('xfId', '0')
    new_xf.set('numFmtId', str(numfmt_id))
    new_xf.set('applyNumberFormat', '1')
    cellXfs.set('count', str(len(cellXfs.findall(f'{{{NS_SHEET}}}xf'))))
    return len(cellXfs.findall(f'{{{NS_SHEET}}}xf')) - 1


def repair_main_spill_styles(xlsx_path: Path) -> bool:
    """Ensure MAIN has column styles for date/time spill columns.

    This repairs the column-level style contract only; it deliberately avoids
    writing s= onto every materialized spill cell.
    """
    try:
        loaded = _load_main_sheet_style_context(xlsx_path)
        if loaded is None:
            return False
        _styled_cols, styles_root, sheet_root, target = loaded

        date_style = _ensure_numfmt_xf(styles_root, DATE_NUMFMT)
        datetime_style = _ensure_numfmt_xf(styles_root, DATETIME_NUMFMT)
        expected_styles = {
            col_idx: str(date_style if kind == 'date' else datetime_style)
            for col_idx, kind in MAIN_COL_STYLE_TARGETS.items()
        }

        cols = sheet_root.find(f'{{{NS_SHEET}}}cols')
        if cols is None:
            cols = ET.Element(f'{{{NS_SHEET}}}cols')
            sheet_root.insert(0, cols)

        changed = False
        for col_idx, expected_style in expected_styles.items():
            col_el = None
            for existing in cols.findall(f'{{{NS_SHEET}}}col'):
                cmin = int(existing.get('min', '0'))
                cmax = int(existing.get('max', '0'))
                if cmin <= col_idx <= cmax:
                    col_el = existing
                    break
            if col_el is None:
                col_el = ET.SubElement(cols, f'{{{NS_SHEET}}}col')
                col_el.set('min', str(col_idx))
                col_el.set('max', str(col_idx))
                col_el.set('width', '13')
                col_el.set('customWidth', '1')
                changed = True
            if col_el.get('style') != expected_style:
                col_el.set('style', expected_style)
                changed = True

        if not changed:
            return True

        with zipfile.ZipFile(xlsx_path, 'r') as zf:
            all_files: dict[str, bytes] = {}
            for name in zf.namelist():
                if name in ('xl/styles.xml', target):
                    continue
                all_files[name] = zf.read(name)
            all_files['xl/styles.xml'] = ET.tostring(
                styles_root,
                xml_declaration=True,
                encoding='UTF-8',
            )
            all_files[target] = ET.tostring(sheet_root, xml_declaration=True, encoding='UTF-8')

        tmp_path = xlsx_path.with_suffix('.stylefix.tmp.xlsx')
        try:
            with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf_out:
                for name, data in all_files.items():
                    zf_out.writestr(name, data)
            tmp_path.replace(xlsx_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def check_done(xlsx_path: Path) -> bool:
    """读取 _SWITCHES!Z1 是否已变为 'DONE'"""
    return read_z1(xlsx_path) == "DONE"


def iter_test2a_files(products: list[str] | None = None) -> list[Path]:
    """返回要处理/校验的 test_2a workbook 列表。"""
    if products:
        return [TEST_2A_DIR / f'{prod}.xlsx' for prod in products]
    return sorted(
        path for path in TEST_2A_DIR.glob('*.xlsx')
        if not path.name.startswith('~$') and not path.name.startswith('.')
    )


def inspect_workbook(path: Path) -> WorkbookStatus:
    """只读检查一个 workbook 的 test_2c 完成状态。"""
    product = path.stem
    if not path.exists():
        return WorkbookStatus(product, path, False, None, None, 'missing file')

    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        sw = wb['_SWITCHES']
        z1_raw = sw['Z1'].value
        z2_raw = sw['Z2'].value
        wb.close()
    except KeyError:
        return WorkbookStatus(product, path, False, None, None, 'missing _SWITCHES sheet')
    except Exception as exc:
        return WorkbookStatus(product, path, False, None, None, f'cannot read workbook: {exc}')

    z1 = str(z1_raw).strip() if z1_raw is not None else None
    try:
        z2 = int(z2_raw) if z2_raw is not None else None
    except (TypeError, ValueError):
        z2 = None
    return WorkbookStatus(product, path, z1 == 'DONE', z1, z2)


def status_ok(status: WorkbookStatus, require_save_count: bool = True) -> bool:
    if status.error:
        return False
    if not status.done:
        return False
    if require_save_count and status.z2 is None:
        return False
    return True


def status_reason(status: WorkbookStatus, require_save_count: bool = True) -> str:
    if status.error:
        return status.error
    if not status.done:
        return f'Z1={status.z1!r}, expected DONE'
    if require_save_count and status.z2 is None:
        return 'Z2 save counter missing'
    return 'OK'


def verify_products(products: list[str] | None = None, require_save_count: bool = True) -> int:
    """校验 test_2c 是否已经对所有目标 workbook 完成计算/保存。"""
    files = iter_test2a_files(products)

    print('test_2c verify: WPS cached calculation status')
    print('=' * 60)
    print(f'  Source directory: {TEST_2A_DIR}')
    print(f'  Products: {len(files)}')
    print(f'  Require Z2 save counter: {require_save_count}')
    print()

    if not files:
        print('No test_2a workbooks found.')
        return 1

    statuses = [inspect_workbook(path) for path in files]
    failures = [s for s in statuses if not status_ok(s, require_save_count)]

    for status in statuses:
        if status_ok(status, require_save_count):
            print(f'✅ {status.product}: DONE (Z2={status.z2})')
        else:
            print(f'❌ {status.product}: {status_reason(status, require_save_count)}')

    print()
    print(f'Done! {len(statuses) - len(failures)} OK, {len(failures)} errors, {len(statuses)} total')

    if failures:
        print()
        print('Not complete:')
        for status in failures:
            print(f'  - {status.product}: {status_reason(status, require_save_count)}')
        return 1

    return 0


def wps_open(xlsx_path: str) -> None:
    """用 WPS 后台打开文件（不阻塞）"""
    subprocess.Popen(['open', '-g', '-a', WPS_APP, xlsx_path], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('opened', flush=True)


def next_save_target(xlsx_path: Path) -> int:
    """生成本轮 WPS 保存后应写入缓存的目标计数。

    目标值必须大于当前缓存值，否则上一次 WPS 保存留下的 Z2 可能造成误判。
    """
    previous = read_z2(xlsx_path) or 0
    return max(previous + 1, int(time.time()))


def wps_save_and_check(xlsx_path: Path, save_target: int, timeout: int = 20) -> tuple[bool, bool]:
    """发送 Cmd+S，轮询 Z2 确认 WPS 已保存，同时读 Z1 状态。
    
    返回 (saved: 保存是否落盘, done: 是否 DONE)
    
    流程：
      1. WPS Cmd+S 保存
      2. 轮询 openpyxl data_only=True 读 Z2，等计数出现 = WPS 已计算并保存缓存
      3. 同时读 Z1，只有 Z2 达到目标且 Z1 == DONE 才算完成
    """
    # 发送 Cmd+S
    script = '''
    tell application "System Events"
        tell process "WPS Office"
            set frontmost to true
            keystroke "s" using command down
            delay 1.5
            keystroke return
        end tell
    end tell
    '''
    subprocess.run(['osascript', '-e', script], check=False, timeout=15)

    # 轮询等待 Z2 == target（保存落盘），每 SAVE_POLL_INTERVAL 秒检测一次
    deadline = time.time() + timeout
    saw_save = False
    while time.time() < deadline:
        time.sleep(SAVE_POLL_INTERVAL)
        z2_val = read_z2(xlsx_path)
        z1_val = read_z1(xlsx_path)
        saw_save = z2_val is not None and z2_val >= save_target
        if saw_save and z1_val == "DONE":
            return (True, True)

    return (saw_save, False)


def wps_is_running() -> bool:
    """检查 WPS 主进程是否仍在运行。"""
    script = '''
    tell application "System Events"
        return exists process "WPS Office"
    end tell
    '''
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            check=False,
            timeout=5,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip().lower() == 'true'
    except Exception:
        return False


def wps_quit(timeout: int = 15) -> bool:
    """退出 WPS、关闭所有窗口/tab，并确认主进程消失。

    WPS 的普通 Cmd+Q 会在下次启动时恢复旧 tab。应用菜单里的
    "Quit and Close All Windows" 才会真正清掉多文档窗口状态。
    """
    script = f'''
    tell application "System Events"
        if not (exists process "WPS Office") then return "closed"
        tell process "WPS Office"
            set frontmost to true
            delay 0.5
            try
                click menu item "Quit and Close All Windows" of menu 1 of menu bar item "WPS Office" of menu bar 1
            on error
                keystroke "q" using {{command down, option down}}
            end try
        end tell
        delay 1
        if exists process "WPS Office" then
            tell process "WPS Office"
                if (count of windows) > 0 and exists sheet 1 of window 1 then
                    keystroke return
                    delay 1
                end if
            end tell
        end if
        repeat with i from 1 to {max(1, int(timeout))}
            if not (exists process "WPS Office") then return "closed"
            delay 1
        end repeat
        return "open"
    end tell
    '''
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            check=False,
            timeout=timeout + 5,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() == 'closed':
            return True
    except Exception:
        pass

    subprocess.run(['pkill', '-f', 'wpsoffice'], check=False)
    time.sleep(2)
    return not wps_is_running()


def kill_wps() -> None:
    """强制关闭所有 WPS 进程"""
    wps_quit(timeout=3)




def process_one(prod: str, wait_scale: float = 1.0, force: bool = False) -> bool:
    """处理单个品种：patch_flag → WPS 打开 → 轮询保存+Z1 完成"""
    src = TEST_2A_DIR / f'{prod}.xlsx'
    if not src.exists():
        print(f'  ⚠️ {prod}.xlsx not found, skipping')
        return False

    if not force and check_done(src):
        z2 = read_z2(src)
        if main_spill_styles_ok(src):
            print(f'  ↩ skip, already DONE (Z2={z2})')
            return True
        repaired = repair_main_spill_styles(src)
        if repaired and main_spill_styles_ok(src):
            print(f'  ↩ skip, already DONE; styles repaired (Z2={z2})')
            return True
        print(f'  ↩ skip, already DONE but style repair failed (Z2={z2})')
        return False

    save_target = next_save_target(src)

    # 打 flag 补丁：必须在 WPS 打开前完成，Z2 是等待 WPS 保存缓存的握手公式。
    patch_flag(src, save_target)

    print(f'  📂 {prod} — opening WPS... ', end='', flush=True)

    try:
        wps_open(str(src))
    except Exception as e:
        print(f'❌ open failed: {e}')
        return False

    # 打开后尽快保存一次，后续每轮保存都会推动 WPS 写出公式缓存。
    open_delay = max(1, int(OPEN_SAVE_DELAY * wait_scale))
    print(f'[open-save {open_delay}s]', end='', flush=True)
    time.sleep(open_delay)

    # 循环保存+轮询
    success = False
    poll_timeout = max(SAVE_POLL_INTERVAL, int(SAVE_POLL_INTERVAL * 4 * wait_scale))
    for retry in range(MAX_RETRIES):
        saved, done = wps_save_and_check(src, save_target, timeout=poll_timeout)

        if done and saved:
            print(f' ✅ DONE (retry={retry})')
            success = True
            break
        elif saved:
            print(f'⏳', end='', flush=True)
            time.sleep(RETRY_WAIT)
        else:
            print(f'⏳', end='', flush=True)
            time.sleep(RETRY_WAIT)
    else:
        print(f' ⚠️ max retries ({MAX_RETRIES}) reached')

    # 每个品种结束后退出 WPS，避免旧工作簿以 tab 形式留到下一个品种。
    close_ok = wps_quit()
    if not close_ok:
        print(' ⚠️ WPS quit not confirmed', end='', flush=True)

    style_ok = True
    if success and close_ok:
        style_ok = repair_main_spill_styles(src)
        if not style_ok:
            print(' ⚠️ style repair skipped/failed', end='', flush=True)

    return success and close_ok and style_ok


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='test_2c: WPS 自动打开 → 计算公式 → 保存 → 关闭'
    )
    parser.add_argument(
        'product_codes', nargs='*',
        help='品种代码（如 A B C），省略则处理全部 88 个品种'
    )
    parser.add_argument(
        '--wait-scale', type=float, default=1.5,
        help='等待时间倍率 (default: 1.5, 保守模式 2.0+)'
    )
    parser.add_argument(
        '--force', action='store_true',
        help='即使 _SWITCHES!Z1 已为 DONE，也重新打开 WPS 计算/保存'
    )
    parser.add_argument(
        '--verify-only', action='store_true',
        help='只检查 _SWITCHES!Z1/Z2 缓存状态，不打开 WPS'
    )
    parser.add_argument(
        '--allow-missing-save-count',
        action='store_true',
        help='verify-only 时只要求 Z1 == DONE，不要求 Z2 保存计数'
    )
    args = parser.parse_args()

    if args.verify_only:
        sys.exit(verify_products(
            args.product_codes or None,
            require_save_count=not args.allow_missing_save_count,
        ))

    print('test_2c: WPS 自动打开 → 公式计算 → 保存关闭')
    print('=' * 60)
    print(f'  Source directory: {TEST_2A_DIR}')
    print(f'  Wait scale: {args.wait_scale}x')
    print(f'  Force rerun: {args.force}')
    print()

    # 收集品种列表
    prods = [path.stem for path in iter_test2a_files(args.product_codes or None)]

    if not prods:
        print('No products found.')
        return

    total = len(prods)
    ok = 0
    fail = 0

    t0 = time.time()

    for i, prod in enumerate(prods):
        # 确保 WPS 已关闭（避免多文件同时打开）
        kill_wps()

        print(f'[{i+1}/{total}] {prod}', end='')
        if process_one(prod, args.wait_scale, force=args.force):
            ok += 1
        else:
            fail += 1

    elapsed = time.time() - t0
    print()
    print(f'Done! {ok} OK, {fail} errors, {total} total')
    print(f'Elapsed: {elapsed:.0f}s ({elapsed/60:.1f} min)')

    # 最终关闭 WPS
    kill_wps()

    if fail:
        sys.exit(1)


if __name__ == '__main__':
    main()
