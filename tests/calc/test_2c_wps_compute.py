#!/usr/bin/env python3
"""
test_2c_wps_compute.py — 自动用 WPS Office 打开 test_2a 的 xlsx，
等待公式计算完成后自动保存并关闭。

用法:
  python tests/calc/test_2c_wps_compute.py              # 处理全部 88 个品种
  python tests/calc/test_2c_wps_compute.py A B C        # 只处理指定品种
  python tests/calc/test_2c_wps_compute.py --wait-scale 2.0  # 保守模式，等 2 倍时间

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

import os
import subprocess
import sys
import time
from pathlib import Path

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


def check_done(xlsx_path: Path) -> bool:
    """读取 _SWITCHES!Z1 是否已变为 'DONE'"""
    return read_z1(xlsx_path) == "DONE"


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




def process_one(prod: str, wait_scale: float = 1.0) -> bool:
    """处理单个品种：patch_flag → WPS 打开 → 轮询保存+Z1 完成"""
    src = TEST_2A_DIR / f'{prod}.xlsx'
    if not src.exists():
        print(f'  ⚠️ {prod}.xlsx not found, skipping')
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

    return success and close_ok


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
    args = parser.parse_args()

    print('test_2c: WPS 自动打开 → 公式计算 → 保存关闭')
    print('=' * 60)
    print(f'  Source directory: {TEST_2A_DIR}')
    print(f'  Wait scale: {args.wait_scale}x')
    print()

    # 收集品种列表
    if args.product_codes:
        prods = args.product_codes
    else:
        prods = sorted(
            p.stem for p in TEST_2A_DIR.glob('*.xlsx')
            if not p.name.startswith('~$') and not p.name.startswith('.')
        )

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
        if process_one(prod, args.wait_scale):
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
