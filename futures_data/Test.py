"""
简化版期货主力合约处理器
功能：根据合约起止日表和日线行情，生成复权后的主力连续合约序列
"""

import os
import pandas as pd
import numpy as np
from tqdm import tqdm
import glob

exchange_map = {'DCE': 'DCE', 'CZCE': 'CZC', 'INE': 'INE', 'SHFE': 'SHF', 'CFFEX': 'CFE', 'GFEX': 'GFE'}

def build_minute_index(data_mink_dir: str, index_path: str) -> pd.DataFrame:
    pattern = os.path.join(data_mink_dir, "data_qc_future_mink_*.parquet")
    files = sorted(glob.glob(pattern))
    index_records = []
    for file_path in tqdm(files, desc="Building minute index"):
        # 读取 unique_instrument_id 和 trading_day
        df = pd.read_parquet(file_path, columns=['unique_instrument_id', 'trading_day'])
        df['trading_day'] = pd.to_datetime(df['trading_day'])
        grouped = df.groupby('unique_instrument_id')['trading_day'].agg(['min', 'max'])
        for uid, row in grouped.iterrows():
            index_records.append({
                'uid': uid,
                'file': os.path.basename(file_path),
                'min_time': row['min'],
                'max_time': row['max'],
            })
    index_df = pd.DataFrame(index_records)
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    index_df.to_parquet(index_path, index=False)
    return index_df

def generate_main_contract_series(contract_start_end_path: str, dayk_path: str,
                                  minute_data_dir: str, minute_index_path: str,
                                  main_mink_folder_path: str, main_dayk_folder_path: str, 
                                  roller_info_path: str, 
                                  products_list: list = [],
                                  rebuild_minute_index: bool = True,
                                  rebuild_roller_info: bool = False,) -> pd.DataFrame:
    """
    增量更新主力合约序列（仅追加尾部新合约，不修改历史）
    使用分钟数据索引，按需加载分钟数据。
    """
    from functools import lru_cache

    @lru_cache(maxsize=128)
    def read_file(file_path: str) -> pd.DataFrame:
        return pd.read_parquet(file_path) if file_path.endswith('.parquet') else pd.read_csv(file_path)
    
    # ========== 1. 处理分钟索引 ==========
    if rebuild_minute_index or not os.path.exists(minute_index_path):
        index_df = build_minute_index(minute_data_dir, minute_index_path)
    else:
        index_df = pd.read_parquet(minute_index_path)
        # 确保时间列是 datetime 类型
        index_df['min_time'] = pd.to_datetime(index_df['min_time'])
        index_df['max_time'] = pd.to_datetime(index_df['max_time'])

    # ========== 2. 加载已有 roller_info ==========
    existing = pd.DataFrame(columns=['PRODUCT', 'CONTRACT', 'STARTDATE', 'ENDDATE', 'PREV_CLOSE', 'END_CLOSE', 'FORWARD_BASE_DATE', 'FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO'])
    if os.path.exists(roller_info_path) and not rebuild_roller_info:
        existing = ((df := read_file(roller_info_path))
                    .assign(STARTDATE=pd.to_datetime(df['STARTDATE']), ENDDATE=pd.to_datetime(df['ENDDATE']))
                    .dropna(subset=['STARTDATE', 'ENDDATE']))

    # ========== 3. 加载新 mapping，找出需要新增的合约 ==========
    new_map = ((df := read_file(contract_start_end_path))
                .rename(columns={'S_INFO_WINDCODE': 'PRODUCT', 'FS_MAPPING_WINDCODE': 'CONTRACT'})
                .assign(STARTDATE=pd.to_datetime(df['STARTDATE']), ENDDATE=pd.to_datetime(df['ENDDATE']))
                .sort_values(['PRODUCT', 'STARTDATE']).reset_index(drop=True))
    new_map = new_map[new_map['PRODUCT'].isin(products_list)] if products_list else new_map # 筛选

    # 为每个产品找到已有最大 ENDDATE
    last_end = existing.groupby('PRODUCT')['ENDDATE'].max() if not existing.empty else pd.Series(dtype='datetime64[ns]')
    # 新增合约条件：ENDDATE > 已有最大 ENDDATE，或者没有已有合约（last_end 是 NaT）
    added_df = new_map[ ((end := new_map['PRODUCT'].map(last_end)).isna()) | (new_map['ENDDATE'].fillna(pd.Timestamp.max) > end.fillna(pd.Timestamp.min)) ]
    # 去除新增合约中那些唯一且 ENDDATE 全为 NaT 的产品（即原数据表中的占位行）
    added_df = added_df.dropna(subset=['STARTDATE', 'ENDDATE'])
    # 如果没有新增合约，直接返回已有数据
    if added_df.empty: return existing

    # ========== 4. 处理新增合约的 CONTRACT 字段，生成 CONTRACT_UID ==========
    # CZC合约特殊处理：补齐十年周期的年份信息（以ENDDATE为基准）
    def czc_patch_decade(row):
        if not row['CONTRACT'].endswith('CZC'):
            return row['CONTRACT']
        if pd.isna(row['ENDDATE']):
            return None
        contract_digits = ''.join([c for c in row['CONTRACT'] if c.isdigit()])
        if len(contract_digits) == 4:
            return row['CONTRACT']  # 已经是完整的年月格式，无需补丁
        elif len(contract_digits) == 3:
            end_str = row['ENDDATE'].strftime('%Y%m%d')
            # 根据ENDDATE的年份信息推断合约代码中的十年周期数字
            # 假设合约代码中的三位数字格式为 YMM，其中 Y 是年份的最后一位，MM 是月份
            # 假设ENDDATE的年份格式为 Y1Y2Y3Y4，如果 Y == Y4 则十年周期数字为 Y3，如果 Y3'Y4' := (Y3Y4 + 1) 且 Y == Y4' 则十年周期数字为 Y3'，否则无法确定
            decade_str = end_str[2] if contract_digits[0] == end_str[3] else end_two_plus[0] if contract_digits[0] == (end_two_plus := str(int(end_str[2:4]) + 1).zfill(2))[-1] else None
            assert decade_str is not None, f"CZC contract {row['CONTRACT']} has unexpected format or ENDDATE: {row['ENDDATE']}"
            return row['CONTRACT'].replace(contract_digits, decade_str + contract_digits) if decade_str is not None else None
        else:
            return None  # 无法处理的格式

    # 生成合约UID，并处理_F的特殊格式
    def contract_patched_to_uid(row):
        contract = row['CONTRACT_PATCHED']
        if contract is None:
            return None
        product_month, exchange = contract.split('.')
        first_digit_idx = next((i for i, c in enumerate(product_month) if c.isdigit()), len(product_month))
        product = product_month[:first_digit_idx]
        month = product_month[first_digit_idx:] # 如果是L2602F，将会得到2602F
        
        reverse_map = {v: k for k, v in exchange_map.items()}
        exchange_code = reverse_map.get(exchange, exchange)
        return f"{exchange_code}|F|{product}|{month}"

    added_df['CONTRACT_PATCHED'] = added_df.apply(czc_patch_decade, axis=1)
    added_df['CONTRACT_UID'] = added_df.apply(contract_patched_to_uid, axis=1)

    # ========== 5. 截断已有合约数据，准备生成主力序列 ==========
    def load_contract_data_mink(uid: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
        empty_df = pd.DataFrame(columns=['unique_instrument_id', 'trading_day', 'close_price', 'trade_time'])
        uid_records = index_df[index_df['uid'] == uid]
        if uid_records.empty:
            return empty_df
        mask = (uid_records['max_time'] >= start_date) & (uid_records['min_time'] <= end_date)
        files_to_read = uid_records[mask]['file'].tolist()
        pieces = []
        for fname in files_to_read:
            df = read_file(os.path.join(minute_data_dir, fname))
            sub = df[(df['unique_instrument_id'] == uid) & (df['trading_day'] >= start_date) & (df['trading_day'] <= end_date)]
            if not sub.empty:
                pieces.append(sub)
        if not pieces:
            return empty_df
        return pd.concat(pieces, ignore_index=True).rename(columns={'unique_instrument_id': 'contract_uid'})
    
    dayk_df = ((df := read_file(dayk_path))
               .assign(trading_day=pd.to_datetime(df['trading_day'])).sort_values('trading_day')
               .rename(columns={'unique_instrument_id': 'contract_uid'}))
    dayk_groups = {uid: group for uid, group in dayk_df.groupby('contract_uid')}
    
    def truncate_contract_data(row):
        if row['STARTDATE'] is pd.NaT or row['ENDDATE'] is pd.NaT:
            return np.nan, np.nan, pd.DataFrame(), None, pd.DataFrame()
        
        df_dayk = dayk_groups.get(row['CONTRACT_UID'], pd.DataFrame(columns=['trading_day', 'close_price']))
        df_mink = load_contract_data_mink(row['CONTRACT_UID'], row['STARTDATE'], row['ENDDATE'])
        
        interval_lambda = lambda df: df[(df['trading_day'] >= row['STARTDATE']) & (df['trading_day'] <= row['ENDDATE'])]
        interval_data = interval_lambda(df_dayk)
        interval_data_mink = interval_lambda(df_mink)
        
        end_close = interval_data['close_price'].iloc[-1] if not interval_data.empty else np.nan
        prev_trading_day = df_dayk.loc[df_dayk['trading_day'] < row['STARTDATE'], 'trading_day'].max() #type: ignore

        if pd.notna(prev_trading_day):
            prev_close = df_dayk['close_price'].loc[df_dayk['trading_day'] == prev_trading_day].iloc[0]
            return prev_close, end_close, interval_data, None, interval_data_mink
        else:
            start_interval = interval_data['trading_day'].iloc[0] if not interval_data.empty else None
            return np.nan, end_close, interval_data, start_interval, interval_data_mink

    # tqdm.pandas(desc="Truncating contracts")
    # results = added_df.progress_apply(truncate_contract_data, axis=1) #type: ignore
    # added_df['PREV_CLOSE'], added_df['END_CLOSE'], pieces, added_df['FORWARD_BASE_DATE'], pieces_mink = zip(*results)

    import concurrent.futures
    rows = [row for _, row in added_df.iterrows()]
    results = [None] * len(rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(truncate_contract_data, row): i for i, row in enumerate(rows)}
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Truncating contracts (multi-thread)"):
            idx = futures[future]
            results[idx] = future.result() # type: ignore
    added_df['PREV_CLOSE'], added_df['END_CLOSE'], pieces, added_df['FORWARD_BASE_DATE'], pieces_mink = zip(*results)

    # ========== 6. 合并数据，生成展期信息，并保存主力序列 ==========
    # 找出需要合并的行索引
    to_drop = []
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
            assert last_existing['PREV_CLOSE'] == first_added['PREV_CLOSE']
            existing.loc[last_existing.name, 'ENDDATE'] = first_added['ENDDATE'] # 更新 existing 该行的 ENDDATE
            existing.loc[last_existing.name, 'END_CLOSE'] = first_added['END_CLOSE'] # 更新 existing 该行的 END_CLOSE
            existing.loc[last_existing.name, '_SOURCE'] = 'added'
            to_drop.append(first_added.name) # 标记 added_df 中的这一行需要删除
    added_df = added_df.drop(index=to_drop) # 删除 added_df 中已合并的行
    # 合并 remaining added_df 与 existing
    info_df = pd.concat([existing.drop(columns=['FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO']), added_df], ignore_index=True)
    info_df = info_df.sort_values(['PRODUCT', 'STARTDATE']).reset_index(drop=True)

    info_df['HAS_DATA'] = info_df['END_CLOSE'].notna()
    block_start = (info_df['PRODUCT'] != info_df['PRODUCT'].shift(1)) | (info_df['HAS_DATA'] & ~info_df['HAS_DATA'].shift(1).fillna(False).astype(bool))
    info_df['BLOCK_ID'] = block_start.cumsum()
    info_df['FORWARD_BASE_DATE'] = pd.to_datetime(info_df.groupby('BLOCK_ID')['FORWARD_BASE_DATE'].ffill())

    def compute_factors(block):
        block = block.sort_values('STARTDATE')
        block['ADJ_RATIO'] = block['PREV_CLOSE'] / block['END_CLOSE'].shift(1)
        block['ADJ_RATIO'].fillna(1, inplace=True)
        block['FORWARD_FACTOR'] = block['ADJ_RATIO'].cumprod()
        block['BACKWARD_FACTOR'] = block['ADJ_RATIO'].iloc[::-1].cumprod().shift(1).fillna(1).iloc[::-1]
        return block
    
    valid_rows = info_df[info_df['HAS_DATA']].copy()
    valid_rows = valid_rows.groupby(['PRODUCT', 'FORWARD_BASE_DATE'], group_keys=False).apply(compute_factors)
    info_df = info_df.merge(valid_rows[['FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO']], left_index=True, right_index=True, how='left')

    df_copy = info_df.copy().drop(columns=['HAS_DATA', 'BLOCK_ID', '_SOURCE'])
    df_copy.to_parquet(roller_info_path if roller_info_path.endswith('.parquet') else roller_info_path.removesuffix(roller_info_path.split('.')[-1]) + 'parquet')
    df_copy.to_csv(roller_info_path if roller_info_path.endswith('.csv') else roller_info_path.removesuffix(roller_info_path.split('.')[-1]) + 'csv', index=False)

    # 找出每个产品最后一个块（BLOCK_ID 最大）
    last_block_per_product = info_df[info_df['BACKWARD_FACTOR'].notna()].groupby('PRODUCT')['BLOCK_ID'].max()
    info_df['IS_LAST_BLOCK'] = info_df.apply(lambda row: row['BLOCK_ID'] == last_block_per_product.get(row['PRODUCT'], -1), axis=1)
    
    added_df = info_df[info_df['_SOURCE'] == 'added'].reset_index(drop=True)
    assert len(added_df) == len(added_df_original)
    assert added_df['PRODUCT'].to_list() == added_df_original['PRODUCT'].to_list()
    assert added_df['STARTDATE'].to_list() == added_df_original['STARTDATE'].to_list()

    for name, main_folder_path, pieces in [('DayK', main_dayk_folder_path, pieces), ('MinK', main_mink_folder_path, pieces_mink)]:
        # 处理日线：只保留最后一块
        os.makedirs(main_folder_path, exist_ok=True)
        dayk_product_data = {}
        for idx, df in tqdm(enumerate(pieces), desc=f"\nGenerating {name} Main Series w/ ADJ cols"):
            if df.empty or not added_df.iloc[idx]['IS_LAST_BLOCK']:
                continue
            df['adjustment_mul'] = added_df.iloc[idx]['BACKWARD_FACTOR']
            df['adjustment_add'] = 0.0
            dayk_product_data.setdefault(added_df.iloc[idx]['PRODUCT'], []).append(df)

        for product, df_list in dayk_product_data.items():
            save_path = os.path.join(main_folder_path, f"{product}.parquet")
            if product in overlapped_products:
                if os.path.exists(save_path):
                    existing_df = (tdf := read_file(save_path)).assign(trading_day=pd.to_datetime(tdf['trading_day']))
                    added_first = added_df[added_df['PRODUCT'] == product].iloc[0]
                    existing_df = existing_df[existing_df['trading_day'] < added_first['STARTDATE']] # 只保留旧数据中早于新增数据的部分
                    existing_df['adjustment_mul'] *= added_first['BACKWARD_FACTOR'] # 后复权
                    df_list = [existing_df] + df_list
            product_df = pd.concat(df_list, ignore_index=True)
            product_df = product_df.sort_values('trade_time')
            product_df.to_parquet(save_path, index=False)
            print(f"Saved {product} daily main series to {save_path}")
    
    return info_df

# 使用示例
if __name__ == '__main__':
    # 定义路径
    contract_mapping_path = '../data/wind_mapping.parquet'
    contract_mapping_path_truncated = '../data/wind_mapping_truncated.parquet'
    dayk_path = '../data/data_dayk.parquet'
    minute_data_dir = '../data/data_mink'               # 原始分钟分片数据目录
    minute_index_path = '../data/minute_index.parquet'  # 索引文件保存路径
    main_mink_folder = '../data/main_mink/'             # 输出分钟主力序列文件夹
    roller_info_path = '../data/roller_info.csv'        # 展期信息输出路径
    main_dayk_folder = '../data/main_dayk/'             # 日线主力序列输出文件

    # 测试截断再补全
    test_products = []
    # test_products = ['A.DCE', 'AD.SHF', 'AD_S.SHF', 'AF-S.CFE', 'AG.SHF', 'AG_S.SHF']
    test_cutoff_date = '2025-05-30'
    
    if test_products:
        # 截断合约映射表，只保留 STARTDATE <= cutoff_date 的合约，并添加当前主力占位行
        df = ((df := pd.read_parquet(contract_mapping_path))
            .rename(columns={'S_INFO_WINDCODE': 'PRODUCT', 'FS_MAPPING_WINDCODE': 'CONTRACT'})
            .assign(STARTDATE=pd.to_datetime(df['STARTDATE']), ENDDATE=pd.to_datetime(df['ENDDATE']))
            .sort_values(['PRODUCT', 'STARTDATE'])
            .reset_index(drop=True))
        
        if test_cutoff_date is not None:
            cutoff = pd.to_datetime(test_cutoff_date)
            df = df[df['STARTDATE'] <= cutoff].reset_index(drop=True)

            def process_group(g):
                last_idx = g['STARTDATE'].idxmax()
                last_valid = g[g['ENDDATE'].notna()]
                # 如果最后一个有效合约的 ENDDATE 早于 cutoff，则不做任何修改
                # 否则，将该产品最后一个合约的 ENDDATE 改为 cutoff
                if not last_valid.empty and last_valid['ENDDATE'].iloc[-1] >= cutoff:
                    g.loc[last_idx, 'ENDDATE'] = cutoff
                # 生成原数据表中的占位行，它的PRODUCT,CONTRACT与最后一行相同，但始末日期均为None
                placeholder = g.loc[last_idx].copy() 
                placeholder['STARTDATE'] = placeholder['ENDDATE'] = pd.NaT
                return pd.concat([g, pd.DataFrame([placeholder])], ignore_index=True)

            df = df.groupby('PRODUCT', group_keys=False).apply(process_group).reset_index(drop=True)

        df = df[df['PRODUCT'].isin(test_products)] if test_products else df
        df.to_parquet(contract_mapping_path_truncated, index=False)

        # 调用主函数
        df = generate_main_contract_series(
            contract_start_end_path=contract_mapping_path_truncated,
            dayk_path=dayk_path,
            minute_data_dir=minute_data_dir,
            minute_index_path=minute_index_path,
            main_mink_folder_path=main_mink_folder,
            roller_info_path=roller_info_path,
            main_dayk_folder_path=main_dayk_folder,
            rebuild_roller_info=True, # 强制重建展期信息，覆盖原文件
        )
        print(df.tail())

        # 增量更新（假设有新数据）
        df = generate_main_contract_series(
            contract_start_end_path=contract_mapping_path,  # 完整映射
            dayk_path=dayk_path,
            minute_data_dir=minute_data_dir,
            minute_index_path=minute_index_path,
            main_mink_folder_path=main_mink_folder,
            roller_info_path=roller_info_path,
            products_list=test_products, # 只更新测试产品
            main_dayk_folder_path=main_dayk_folder,
        )
        print(df.tail())

    else:
        df = generate_main_contract_series(
            contract_start_end_path=contract_mapping_path,
            dayk_path=dayk_path,
            minute_data_dir=minute_data_dir,
            minute_index_path=minute_index_path,
            main_mink_folder_path=main_mink_folder,
            roller_info_path=roller_info_path,
            main_dayk_folder_path=main_dayk_folder,
        )
        print(df.tail())