"""
简化版期货主力合约处理器
功能：根据合约起止日表和日线行情，生成复权后的主力连续合约序列
"""

import os
import sys
import json
import platform
from collections import defaultdict
import concurrent.futures
from pathlib import Path
from turtle import left
import pandas as pd
import numpy as np
from tqdm import tqdm

# 直接运行时将项目根加入 sys.path，确保 scripts 等顶层包可导入
if __package__ in (None, ""):
    _root = Path(__file__).resolve().parents[3]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from sources.LocalCNFutures import ROLLER_INFO_PATH, SOURCE_DATA_DIR
from sources.LocalCNFutures.contract_files import portable_contract_filename, resolve_contract_parquet_path

CONTRACT_MAPPING_PATH = os.path.join(SOURCE_DATA_DIR, 'wind_mapping.parquet')
CONTRACT_MAPPING_PATH_TRUNCATED = os.path.join(SOURCE_DATA_DIR, 'wind_mapping_truncated.parquet')
DAYK_PATH = os.path.join(SOURCE_DATA_DIR, 'data_dayk.parquet')
MINUTE_DATA_DIR = os.path.join(SOURCE_DATA_DIR, 'data_mink')
MINUTE_DATA_PREPROCESSED_DIR = os.path.join(SOURCE_DATA_DIR, 'data_mink_product')
MINUTE_INDEX_PATH = os.path.join(SOURCE_DATA_DIR, 'minute_index.parquet')
MAIN_MINK_FOLDER = os.path.join(SOURCE_DATA_DIR, 'main_mink') + '/'
MAIN_DAYK_FOLDER = os.path.join(SOURCE_DATA_DIR, 'main_dayk') + '/'

_MINUTE_PREPROCESS_MANIFEST = '_minute_preprocess_manifest.json'
BACKWARD_BASE_DATE_COL = 'BACKWARD_BASE_DATE'

_IS_WINDOWS = platform.system() == 'Windows'


def preprocess_minute_data(minute_raw_dir: str, minute_product_dir: str, force_rebuild: bool = True):
    """预处理分钟数据，生成每个 uid 的独立 parquet 文件。

    force_rebuild=True 时清空并全量重建；False 时按原始 parquet 的
    size/mtime 增量处理新增或变化的分片。
    """
    import shutil

    if not os.path.isdir(minute_raw_dir):
        raise FileNotFoundError(f"原始分钟数据目录不存在: {minute_raw_dir}")
    raw_files = sorted(
        os.path.join(minute_raw_dir, f)
        for f in os.listdir(minute_raw_dir) if f.endswith('.parquet')
    )
    if not raw_files:
        raise ValueError(f"原始分钟数据目录没有 parquet 文件: {minute_raw_dir}")

    if force_rebuild and os.path.exists(minute_product_dir):
        shutil.rmtree(minute_product_dir)
    os.makedirs(minute_product_dir, exist_ok=True)

    # 增量模式：加载已有 manifest，对比文件签名
    manifest_path = os.path.join(minute_product_dir, _MINUTE_PREPROCESS_MANIFEST)
    manifest = {} if force_rebuild else (json.load(open(manifest_path, encoding='utf-8')) if os.path.exists(manifest_path) else {})
    files_to_process = []
    for path in raw_files:
        stat = os.stat(path)
        sig = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        key = os.path.basename(path)
        if not force_rebuild and manifest.get(key) == sig:
            continue
        files_to_process.append((path, key, sig))

    if not files_to_process:
        print("Minute product data is up to date. Skipping preprocessing.")
        return

    print(f"Preprocessing {len(files_to_process)} / {len(raw_files)} minute parquet files...")

    def _write_uid_group(uid: str, group: pd.DataFrame) -> None:
        out_path = os.path.join(minute_product_dir, portable_contract_filename(uid))
        group = group.drop_duplicates(subset='trade_timestamp').sort_values('trade_timestamp')
        if os.path.exists(out_path):
            existing = pd.read_parquet(out_path)
            group = (
                pd.concat([existing, group], ignore_index=True)
                .drop_duplicates(subset='trade_timestamp', keep='last')
                .sort_values('trade_timestamp')
            )
        group.to_parquet(out_path, index=False)

    for path, key, sig in tqdm(files_to_process, desc="Preprocessing minute raw files"):
        df = pd.read_parquet(path)
        if df.empty:
            manifest[key] = sig
            continue
        required = {'unique_instrument_id', 'trade_timestamp'}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{path} 缺少必要列: {sorted(missing)}")

        groups = list(df.groupby('unique_instrument_id', sort=False))
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(groups))) as executor:
            futures = [executor.submit(_write_uid_group, str(uid), g) for uid, g in groups]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        manifest[key] = sig
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        del df

    import gc
    gc.collect()
    print("\nMinute data preprocessing completed.")


def preprocess_minute_data_stream(minute_raw_dir: str, minute_product_dir: str,
                                   force_rebuild: bool = True,
                                   flush_threshold: int = 200_000):
    """流式预处理分钟数据 — 专为 Windows 优化。

    单遍顺序扫描原始文件，每个 uid 用内存缓冲区累积，
    缓冲区满才 flush 到磁盘，避免频繁小文件读-改-写。

    force_rebuild=True 时清空并全量重建；False 时按原始 parquet 的
    size/mtime 增量处理新增或变化的分片。
    """
    import shutil

    if not os.path.isdir(minute_raw_dir):
        raise FileNotFoundError(f"原始分钟数据目录不存在: {minute_raw_dir}")
    raw_files = sorted(
        os.path.join(minute_raw_dir, f)
        for f in os.listdir(minute_raw_dir) if f.endswith('.parquet')
    )
    if not raw_files:
        raise ValueError(f"原始分钟数据目录没有 parquet 文件: {minute_raw_dir}")

    if force_rebuild and os.path.exists(minute_product_dir):
        shutil.rmtree(minute_product_dir)
    os.makedirs(minute_product_dir, exist_ok=True)

    # 增量模式：加载已有 manifest，对比文件签名
    manifest_path = os.path.join(minute_product_dir, _MINUTE_PREPROCESS_MANIFEST)
    manifest = {} if force_rebuild else (
        json.load(open(manifest_path, encoding='utf-8')) if os.path.exists(manifest_path) else {}
    )
    files_to_process = []
    for path in raw_files:
        stat = os.stat(path)
        sig = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        key = os.path.basename(path)
        if not force_rebuild and manifest.get(key) == sig:
            continue
        files_to_process.append((path, key, sig))

    if not files_to_process:
        print("Minute product data is up to date. Skipping preprocessing.")
        return

    print(f"Processing {len(files_to_process)} / {len(raw_files)} files (stream mode)...")

    # ── 每个 uid 的缓冲区 ──
    buffer: dict[str, list[pd.DataFrame]] = defaultdict(list)
    _buf_sizes: dict[str, int] = defaultdict(int)

    def _flush(uid: str) -> None:
        """将缓冲区数据写入磁盘，同一 uid 只写 1 次（无需读回）。"""
        out_path = os.path.join(minute_product_dir, portable_contract_filename(uid))
        combined = pd.concat(buffer[uid], ignore_index=True)
        combined = combined.drop_duplicates(subset='trade_timestamp') \
                           .sort_values('trade_timestamp')

        # 增量模式下，已有文件需要合并去重
        if not force_rebuild and os.path.exists(out_path):
            existing = pd.read_parquet(out_path)
            combined = pd.concat([existing, combined], ignore_index=True) \
                          .drop_duplicates(subset='trade_timestamp', keep='last') \
                          .sort_values('trade_timestamp')

        combined.to_parquet(out_path, index=False)
        buffer[uid].clear()
        _buf_sizes[uid] = 0

    def _read_and_group(path: str) -> tuple[str, dict, dict[str, pd.DataFrame]]:
        """读取一个 parquet 文件，返回 (key, sig, {uid: group_df})。"""
        stat = os.stat(path)
        sig = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        key = os.path.basename(path)
        df = pd.read_parquet(path)
        if df.empty:
            return key, sig, {}
        required = {'unique_instrument_id', 'trade_timestamp'}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{path} 缺少必要列: {sorted(missing)}")
        groups = {}
        for uid, group in df.groupby('unique_instrument_id', sort=False):
            groups[str(uid)] = group
        return key, sig, groups

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            fut_to_info = {executor.submit(_read_and_group, p): (p, k, s)
                           for p, k, s in files_to_process}
            with tqdm(total=len(files_to_process), desc="Processing") as pbar:
                for future in concurrent.futures.as_completed(fut_to_info):
                    path, key, sig = fut_to_info[future]
                    try:
                        _, _, groups = future.result()
                    except Exception:
                        # 如果 read 失败，退回到单线程重试
                        _, _, groups = _read_and_group(path)

                    for uid_str, group in groups.items():
                        buffer[uid_str].append(group)
                        _buf_sizes[uid_str] += len(group)
                        if _buf_sizes[uid_str] >= flush_threshold:
                            _flush(uid_str)

                    manifest[key] = sig
                    with open(manifest_path, 'w', encoding='utf-8') as f:
                        json.dump(manifest, f, ensure_ascii=False, indent=2)
                    pbar.update(1)
    finally:
        # 确保所有缓冲区刷入磁盘
        for uid in list(buffer.keys()):
            if buffer[uid]:
                _flush(uid)

    import gc
    gc.collect()
    print("\nMinute data preprocessing completed (stream mode).")


def generate_main_contract_series(contract_start_end_path: str|pd.DataFrame = CONTRACT_MAPPING_PATH, 
                                  dayk_path: str = DAYK_PATH,
                                  minute_data_dir: str = MINUTE_DATA_DIR, 
                                  minute_data_preprocessed_dir: str = MINUTE_DATA_PREPROCESSED_DIR,
                                  main_mink_folder_path: str = MAIN_MINK_FOLDER, 
                                  main_dayk_folder_path: str = MAIN_DAYK_FOLDER, 
                                  roller_info_path: str = ROLLER_INFO_PATH, 
                                  products_list: list = [],
                                  rebuild_minute_product: bool = True,
                                  rebuild_roller_info: bool = False,) -> pd.DataFrame:
    """
    增量更新主力合约序列（仅追加尾部新合约，不修改历史）
    使用分钟数据索引，按需加载分钟数据。
    """
    # ========== 1. 处理分钟索引 ==========
    if _IS_WINDOWS:
        preprocess_minute_data_stream(
            minute_data_dir,
            minute_data_preprocessed_dir,
            force_rebuild=bool(rebuild_minute_product),
        )
    else:
        preprocess_minute_data(
            minute_data_dir,
            minute_data_preprocessed_dir,
            force_rebuild=bool(rebuild_minute_product),
        )

    # ========== 2. 加载已有 roller_info ==========
    existing = pd.DataFrame(columns=['PRODUCT', 'CONTRACT', 'STARTDATE', 'ENDDATE', 'PREV_CLOSE', 'END_CLOSE', BACKWARD_BASE_DATE_COL, 'FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO'])
    if os.path.exists(roller_info_path) and not rebuild_roller_info:
        existing = ((df := pd.read_parquet(roller_info_path))
                    .assign(STARTDATE=pd.to_datetime(df['STARTDATE']), ENDDATE=pd.to_datetime(df['ENDDATE']))
                    .dropna(subset=['STARTDATE', 'ENDDATE']))
    # 为每个产品找到已有最大 ENDDATE
    last_end = (existing.groupby('PRODUCT')['ENDDATE'].max() if not existing.empty else pd.Series(dtype='datetime64[ns]')).to_dict()

    # ========== 3. 加载新 mapping，找出需要新增的合约 ==========
    new_map = ((df := pd.read_parquet(contract_start_end_path) if not products_list else
                pd.read_parquet(contract_start_end_path, filters=[('S_INFO_WINDCODE', 'in', products_list)]))
                .rename(columns={'S_INFO_WINDCODE': 'PRODUCT', 'FS_MAPPING_WINDCODE': 'CONTRACT'})
                .assign(STARTDATE=pd.to_datetime(df['STARTDATE']), ENDDATE=pd.to_datetime(df['ENDDATE']))
                .sort_values(['PRODUCT', 'STARTDATE']).reset_index(drop=True)) \
                if isinstance(contract_start_end_path, str) else contract_start_end_path
    new_map.dropna(subset=['STARTDATE', 'ENDDATE'], how='all', inplace=True) # 去除没有任何日期信息的行（占位行）
    added_df = new_map[ ((end := new_map['PRODUCT'].map(last_end)).isna()) | (new_map['ENDDATE'] > end.fillna(pd.Timestamp.min)) ]
    if added_df.empty: return existing # 如果没有新增合约，直接返回已有数据

    # ========== 4. 处理新增合约的 CONTRACT 字段，生成 CONTRACT_UID ==========
    # CZC合约特殊处理：补齐十年周期的年份信息（以ENDDATE为基准）
    def czc_patch_decade(row):
        if not row['CONTRACT'].endswith('CZC'): return row['CONTRACT']
        if pd.isna(row['ENDDATE']): return None
        contract_digits = ''.join(filter(str.isdigit, row['CONTRACT']))
        if len(contract_digits) == 4: return row['CONTRACT']  # 已经是完整的年月格式，无需补丁
        elif len(contract_digits) == 3:
            end_str = row['ENDDATE'].strftime('%Y%m%d')
            # 根据ENDDATE的年份信息推断合约代码中的十年周期数字
            # 假设合约代码中的三位数字格式为 YMM，其中 Y 是年份的最后一位，MM 是月份
            # 假设ENDDATE的年份格式为 Y1Y2Y3Y4，如果 Y == Y4 则十年周期数字为 Y3，如果 Y3'Y4' := (Y3Y4 + 1) 且 Y == Y4' 则十年周期数字为 Y3'，否则无法确定
            decade_str = end_str[2] if contract_digits[0] == end_str[3] else end_two_plus[0] if contract_digits[0] == (end_two_plus := str(int(end_str[2:4]) + 1).zfill(2))[-1] else None
            assert decade_str is not None, f"CZC contract {row['CONTRACT']} has unexpected format or ENDDATE: {row['ENDDATE']}"
            return row['CONTRACT'].replace(contract_digits, decade_str + contract_digits) if decade_str is not None else None
        else: return None  # 无法处理的格式
        
    exchange_map = {'DCE': 'DCE', 'CZCE': 'CZC', 'INE': 'INE', 'SHFE': 'SHF', 'CFFEX': 'CFE', 'GFEX': 'GFE'}
    reverse_map = {v: k for k, v in exchange_map.items()}

    def patched_to_uid(patched):
        if patched is None:
            return None
        pm, exchange = patched.split('.')
        first_digit_idx = next((i for i, c in enumerate(pm) if c.isdigit()), len(pm))
        return f"{reverse_map.get(exchange, exchange)}|F|{pm[:first_digit_idx]}|{pm[first_digit_idx:]}"

    added_df['CONTRACT_PATCHED'] = added_df.apply(czc_patch_decade, axis=1)
    added_df['CONTRACT_UID'] = added_df['CONTRACT_PATCHED'].apply(patched_to_uid)

    # ========== 5. 截断已有合约数据，准备生成主力序列 ==========
    dayk_df = ((df := pd.read_parquet(dayk_path)).assign(trading_day=pd.to_datetime(df['trading_day']))
               .rename(columns={'unique_instrument_id': 'contract_uid'}))
    dayk_groups = {uid: group for uid, group in dayk_df.groupby('contract_uid')}
    
    def truncate_contract_data(row):
        if row['STARTDATE'] is pd.NaT or row['ENDDATE'] is pd.NaT:
            return np.nan, np.nan, pd.DataFrame(), None, pd.DataFrame()

        def load_contract_data_mink(uid: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
            file_path = str(resolve_contract_parquet_path(minute_data_preprocessed_dir, uid))
            if not os.path.exists(file_path):
                return pd.DataFrame(columns=['trading_day', 'close_price', 'trade_time'])
            lookback_start = start_date - pd.Timedelta(days=60)
            return ((df := pd.read_parquet(file_path, filters=[('trading_day', '>=', lookback_start), ('trading_day', '<=', end_date)]))
                .assign(trading_day=pd.to_datetime(df['trading_day']))).rename(columns={'unique_instrument_id': 'contract_uid'})
        
        df_mink_with_prev = load_contract_data_mink(row['CONTRACT_UID'], row['STARTDATE'], row['ENDDATE'])
        df_mink_with_prev = df_mink_with_prev.sort_values('trade_time') if 'trade_time' in df_mink_with_prev.columns else df_mink_with_prev
        prev_mink = df_mink_with_prev[df_mink_with_prev['trading_day'] < row['STARTDATE']]
        df_mink = df_mink_with_prev[df_mink_with_prev['trading_day'] >= row['STARTDATE']]
        prev_mink_close = prev_mink['close_price'].iloc[-1] if not prev_mink.empty else np.nan
        df_dayk = dayk_groups.get(row['CONTRACT_UID'], pd.DataFrame(columns=['trading_day', 'close_price']))
        # searchsorted 要求数据已排序；dayk_df 按多列排序后 groupby 不保证 trading_day 单调递增
        if not df_dayk['trading_day'].is_monotonic_increasing:
            df_dayk = df_dayk.sort_values('trading_day')
        left = df_dayk['trading_day'].searchsorted(row['STARTDATE'], side='left')
        right = df_dayk['trading_day'].searchsorted(row['ENDDATE'], side='right')
        interval_data = df_dayk.iloc[left:right]
        end_close = interval_data['close_price'].iloc[-1] if not interval_data.empty else np.nan

        if not df_mink.empty:
            end_close = df_mink['close_price'].iloc[-1]
            prev_close = prev_mink_close if not pd.isna(prev_mink_close) else df_dayk['close_price'].iloc[left - 1] if left > 0 else df_mink['close_price'].iloc[0]
            start_interval = None if (not pd.isna(prev_mink_close) or left > 0) else df_mink['trading_day'].iloc[0]
            return prev_close, end_close, interval_data, start_interval, df_mink

        if left > 0:
            return df_dayk['close_price'].iloc[left - 1], end_close, interval_data, None, df_mink
        else:
            start_interval = interval_data['trading_day'].iloc[0] if not interval_data.empty else None
            return np.nan, end_close, interval_data, start_interval, df_mink

    import concurrent.futures
    rows = [row for _, row in added_df.iterrows()]
    results = [None] * len(rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(truncate_contract_data, row): i for i, row in enumerate(rows)}
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Truncating contracts (multi-thread)"):
            idx = futures[future]
            results[idx] = future.result() # type: ignore
    added_df['PREV_CLOSE'], added_df['END_CLOSE'], pieces, added_df[BACKWARD_BASE_DATE_COL], pieces_mink = zip(*results)

    # ========== 6. 合并数据，生成展期信息，并保存主力序列 ==========
    # 找出需要合并的行索引
    to_drop = []
    continued_products = set()
    overlapped_products = set(existing['PRODUCT'].unique()) & set(added_df['PRODUCT'].unique())
    existing['_SOURCE'] = 'existing'
    added_df['_SOURCE'] = 'added'
    added_df_original = added_df.copy() # 用于后续验证
    existing.sort_values(['PRODUCT', 'STARTDATE'], inplace=True)
    for product in overlapped_products:
        last_existing = existing[existing['PRODUCT'] == product].iloc[-1] # existing 中该产品的最后一行
        first_added = added_df[added_df['PRODUCT'] == product].iloc[0] # added_df 中该产品的第一行
        if last_existing['CONTRACT'] == first_added['CONTRACT']:
            assert last_existing['STARTDATE'] == first_added['STARTDATE']
            assert last_existing['PREV_CLOSE'] == first_added['PREV_CLOSE'] or (pd.isna(last_existing['PREV_CLOSE']) and pd.isna(first_added['PREV_CLOSE']))
            existing.loc[last_existing.name, 'ENDDATE'] = first_added['ENDDATE'] # 更新 existing 该行的 ENDDATE
            existing.loc[last_existing.name, 'END_CLOSE'] = first_added['END_CLOSE'] # 更新 existing 该行的 END_CLOSE
            existing.loc[last_existing.name, '_SOURCE'] = 'added'
            continued_products.add(product)
            to_drop.append(first_added.name) # 标记 added_df 中的这一行需要删除
    added_df = added_df.drop(index=to_drop) # 删除 added_df 中已合并的行
    # 合并 remaining added_df 与 existing
    info_df = pd.concat([existing.drop(columns=['FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO']), added_df], ignore_index=True) if not existing.empty else added_df
    info_df = info_df.sort_values(['PRODUCT', 'STARTDATE']).reset_index(drop=True)

    info_df['HAS_DATA'] = info_df['END_CLOSE'].notna()
    block_start = (info_df['PRODUCT'] != info_df['PRODUCT'].shift(1)) | (info_df['HAS_DATA'] & ~info_df['HAS_DATA'].shift(1).fillna(False).astype(bool))
    info_df['BLOCK_ID'] = block_start.cumsum()
    info_df[BACKWARD_BASE_DATE_COL] = pd.to_datetime(info_df.groupby('BLOCK_ID')[BACKWARD_BASE_DATE_COL].ffill())

    def compute_factors(block):
        block['ADJ_RATIO'] = (block['END_CLOSE'].shift(1) / block['PREV_CLOSE']).fillna(1)
        # 前复权：最新合约因子为 1，历史合约反向累积到最新合约价格水平。
        block['FORWARD_FACTOR'] = block['ADJ_RATIO'].iloc[::-1].cumprod().shift(1).fillna(1).iloc[::-1]
        # 后复权：首个合约因子为 1，后续合约向历史价格水平累积。
        block['BACKWARD_FACTOR'] = block['ADJ_RATIO'].cumprod()
        return block
    
    valid_rows = info_df[info_df['HAS_DATA']].groupby(['PRODUCT', BACKWARD_BASE_DATE_COL], group_keys=False).apply(compute_factors)
    info_df = info_df.merge(valid_rows[['FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO']], left_index=True, right_index=True, how='left')

    df_copy = info_df.copy().drop(columns=['HAS_DATA', 'BLOCK_ID', '_SOURCE'])
    df_copy.to_parquet(roller_info_path if roller_info_path.endswith('.parquet') else roller_info_path.removesuffix(roller_info_path.split('.')[-1]) + 'parquet')
    df_copy.to_csv(roller_info_path if roller_info_path.endswith('.csv') else roller_info_path.removesuffix(roller_info_path.split('.')[-1]) + 'csv', index=False)

    # 找出每个产品最后一个块（BLOCK_ID 最大）
    last_block_per_product = info_df[info_df['FORWARD_FACTOR'].notna()].groupby('PRODUCT')['BLOCK_ID'].max()
    info_df['IS_LAST_BLOCK'] = info_df.apply(lambda row: row['BLOCK_ID'] == last_block_per_product.get(row['PRODUCT'], -1), axis=1)
    
    added_df = info_df[info_df['_SOURCE'] == 'added'].reset_index(drop=True)
    assert len(added_df) == len(added_df_original)
    assert added_df['PRODUCT'].to_list() == added_df_original['PRODUCT'].to_list()
    assert added_df['STARTDATE'].to_list() == added_df_original['STARTDATE'].to_list()

    for name, main_folder_path, pieces in [('DayK', main_dayk_folder_path, pieces), ('MinK', main_mink_folder_path, pieces_mink)]:
        # 处理日线：只保留最后一块
        os.makedirs(main_folder_path, exist_ok=True)
        product_data = {}
        for idx, df in tqdm(enumerate(pieces), desc=f"Asserting ADJ cols to {name} Main Series", position=0, leave=True, mininterval=0.5):
            if df.empty or not added_df.iloc[idx]['IS_LAST_BLOCK']: continue;
            df = df.assign(adjustment_mul=added_df.iloc[idx]['FORWARD_FACTOR'], adjustment_add=0.0)
            product_data.setdefault(added_df.iloc[idx]['PRODUCT'], []).append(df)

        added_first = {uid: group.iloc[0] for uid, group in added_df.groupby('PRODUCT')}
        for product, df_list in tqdm(product_data.items(), desc=f"Saving {name} Main Series", position=0, leave=True, mininterval=0.5):
            save_path = os.path.join(main_folder_path, f"{product}.parquet")
            if product in overlapped_products and os.path.exists(save_path):
                existing_df = (tdf := pd.read_parquet(save_path, filters=[('trading_day', '<', added_first[product]['STARTDATE'])])).assign(trading_day=pd.to_datetime(tdf['trading_day']))
                added_scale = added_first[product]['FORWARD_FACTOR']
                if product not in continued_products:
                    added_scale *= added_first[product]['ADJ_RATIO']
                existing_df['adjustment_mul'] *= added_scale # 前复权：旧 parquet 历史段补乘新增切换因子
                df_list = [existing_df] + df_list
            product_df = (
                pd.concat(df_list, ignore_index=True)
                .assign(unique_instrument_id=product)
                .sort_values('trade_time')
            )
            product_df.to_parquet(save_path, index=False)
    
    return info_df

# 使用示例
if __name__ == '__main__':
    df = generate_main_contract_series(
        rebuild_roller_info=True,
        rebuild_minute_product=False,
    )
    print(df)
