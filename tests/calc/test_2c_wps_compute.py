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
  3. 等待估算的计算时间（基于合约数量）
  4. System Events 发送 Cmd+S 保存（处理可能出现的保存对话框）
  5. System Events 发送 Cmd+W 关闭
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

from tests.calc import TEST_2A_DIR, TEST_2C_DIR

# ============================================================
# 配置
# ============================================================

WPS_APP = '/Applications/wpsoffice.app'
SECONDS_PER_CONTRACT = 3      # 每个合约约 3 秒计算时间（REDUCE+VSTACK）
MIN_WAIT = 10                  # 最小等待 10 秒
MAX_WAIT = 120                 # 最大等待 120 秒（总体超时保护）
INITIAL_WAIT = 10               # 初始等待 10 秒让 WPS 开始计算
SAVE_POLL_INTERVAL = 5          # 保存后每 5 秒检测落盘
RETRY_WAIT = 5                  # CALC 后等 5 秒再保存
MAX_RETRIES = 20                # 最多重试 20 次（10+5×20 = 110s ≈ 2 min）

FORMULA_FILL = PatternFill(start_color='E2EFDA', end_color='E2EFDA', fill_type='solid')

# ============================================================
# 工具函数
# ============================================================

def patch_flag(xlsx_path: Path) -> None:
    """给 _SWITCHES!Z1 写入 flag 公式 + Z2 清零（不重新生成文件，只打补丁）
    
    Z1 = IF(ISNUMBER(MAIN!右下角单元格),"DONE","CALC")
    右下角 = MAIN row 2 最后一个非空列 × row(2+合约数)
    WPS 计算 REDUCE+VSTACK 动态数组全部填充后，右下角变为数值，Z1 自动变 "DONE"
    """
    try:
        wb = load_workbook(xlsx_path)
        
        # 探测 MAIN sheet 的下角
        main = wb['MAIN']
        # row 2 最后一个非空列
        last_col = main.max_column  # openpyxl 按全 sheet 记，但需要找 row 2 的实际非空
        # 从右向左扫描 row 2 找到真正的最后一个非空列
        last_data_col = 1
        for col in range(main.max_column, 0, -1):
            if main.cell(2, col).value is not None:
                last_data_col = col
                break
        
        # 探测 _SWITCHES 合约数
        sw = wb['_SWITCHES']
        n_contracts = sw.max_row - 2 if sw.max_row else 0
        
        # 右下角：最后一个数据行，倒数第二列（最后一列是 adjustment_add 恒为0）
        data_col = max(last_data_col - 1, 1)  # 跳过最后一列
        bottom_right_row = 2 + n_contracts
        corner_col_letter = get_column_letter(data_col)
        corner_cell = f'{corner_col_letter}{bottom_right_row}'
        
        # Z1 flag = IF(ISNUMBER(MAIN!corner),"DONE","CALC")
        existing = sw.cell(1, 26).value
        if existing is None or str(existing).strip() in ('', 'CALC', '0'):
            formula = f'=IF(ISNUMBER(MAIN!{corner_cell}),"DONE","CALC")'
            sw.cell(1, 26, formula).fill = FORMULA_FILL
        
        # Z2 清零（保存计数器）
        sw.cell(2, 26, 0)
        
        wb.save(xlsx_path)
        wb.close()
    except Exception as e:
        print(f'  ⚠️ patch_flag failed: {e}', flush=True)

def estimate_wait(xlsx_path: Path) -> int:
    """根据 _SWITCHES 合约数量估算 WPS 计算等待时间（秒）"""
    try:
        wb = load_workbook(xlsx_path, read_only=True, data_only=False)
        sw = wb['_SWITCHES']
        # 合约数量 = _SWITCHES 数据行数 (row 3 to max_row)
        n = sw.max_row - 2 if sw.max_row else 0
        wb.close()
        if n <= 0:
            return MIN_WAIT
        return min(max(int(n * SECONDS_PER_CONTRACT), MIN_WAIT), MAX_WAIT)
    except Exception:
        return MIN_WAIT


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
    """用 WPS 打开文件"""
    subprocess.run(['open', '-a', WPS_APP, xlsx_path], check=True)


# 全局保存计数器（每次 patch_flag 重置）
_save_seq = 0


def reset_save_seq() -> None:
    """重置保存计数器（每个产品开始时调用）"""
    global _save_seq
    _save_seq = 0


def wps_save_and_check(xlsx_path: Path, timeout: int = 20) -> tuple[bool, bool]:
    """发送 Cmd+S（带递增计数），轮询 Z2 确认落盘，同时读 Z1 状态
    
    返回 (saved: 保存是否落盘, done: 是否 DONE)
    
    流程：
      1. 用 openpyxl 在 _SWITCHES!Z2 写入递增计数 → 保存（给 WPS 看）
      2. WPS Cmd+S 保存
      3. 轮询 openpyxl data_only=True 读 Z2，等计数出现 = 落盘
      4. 同时读 Z1 返回 done 状态
    """
    global _save_seq
    _save_seq += 1
    target = _save_seq

    # 在 Z2 写入目标计数，让 WPS 下次 Cmd+S 把它写进缓存
    try:
        wb = load_workbook(xlsx_path)
        wb['_SWITCHES'].cell(2, 26, _save_seq)
        wb.save(xlsx_path)
        wb.close()
    except Exception:
        pass

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
    while time.time() < deadline:
        time.sleep(SAVE_POLL_INTERVAL)
        z2_val = read_z2(xlsx_path)
        z1_val = read_z1(xlsx_path)
        if z2_val == target:
            return (True, z1_val == "DONE")
        elif z2_val is not None and z2_val > target:
            # 落盘已完成（WPS 可能已内部保存了更新的计数）
            return (True, z1_val == "DONE")

    return (False, False)


def kill_wps() -> None:
    """强制关闭所有 WPS 进程"""
    subprocess.run(['pkill', '-f', 'wpsoffice'], check=False)
    time.sleep(2)


import shutil


def process_one(prod: str, wait_scale: float = 1.0) -> bool:
    """处理单个品种：备份→patch→WPS→轮询保存+Z1完成→成功删备份/失败恢复"""
    src = TEST_2A_DIR / f'{prod}.xlsx'
    if not src.exists():
        print(f'  ⚠️ {prod}.xlsx not found, skipping')
        return False

    TEST_2C_DIR.mkdir(parents=True, exist_ok=True)
    backup = TEST_2C_DIR / f'{prod}.xlsx'

    # 1) 备份原始文件
    shutil.copy2(src, backup)

    # 2) 在 test_2a 原文件上打 flag 补丁
    patch_flag(src)
    reset_save_seq()

    print(f'  📂 {prod} — opening WPS... ', end='', flush=True)

    try:
        wps_open(str(src))
    except Exception as e:
        print(f'❌ open failed: {e}')
        shutil.copy2(backup, src)
        backup.unlink(missing_ok=True)
        return False

    # 3) 初始等待 WPS 开始计算
    print(f'[wait {INITIAL_WAIT}s]', end='', flush=True)
    time.sleep(INITIAL_WAIT)

    # 4) 循环保存+轮询，直到 Z1=DONE 或 max_retries
    success = False
    for retry in range(MAX_RETRIES):
        saved, done = wps_save_and_check(src, timeout=SAVE_POLL_INTERVAL * 4)

        if done and saved:
            print(f' ✅ DONE (retry={retry})')
            success = True
            break
        elif saved:
            # 已落盘但 CALC — 等 RETRY_WAIT 再保存
            print(f'⏳', end='', flush=True)
            time.sleep(RETRY_WAIT)
        else:
            # 保存未落盘 — 不是本次保存？等待上次落盘
            print(f'⏳', end='', flush=True)
            time.sleep(RETRY_WAIT)
    else:
        print(f' ⚠️ max retries ({MAX_RETRIES}) reached')

    # 5) 关闭 WPS 文档
    script = '''
    tell application "System Events"
        tell process "WPS Office"
            set frontmost to true
            delay 0.5
            keystroke "w" using command down
            delay 1
            keystroke return
        end tell
    end tell
    '''
    subprocess.run(['osascript', '-e', script], check=False, timeout=15)
    time.sleep(1)

    if success:
        backup.unlink(missing_ok=True)
    else:
        shutil.copy2(backup, src)
        backup.unlink(missing_ok=True)
        return False

    return True


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
