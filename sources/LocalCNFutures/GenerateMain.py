"""
简化版期货主力合约处理器
功能：根据合约起止日表和日线行情，生成复权后的主力连续合约序列
"""

import os
from turtle import left
import pandas as pd
import numpy as np
from tqdm import tqdm

contract_mapping_path = '../data/wind_mapping.parquet'
contract_mapping_path_truncated = '../data/wind_mapping_truncated.parquet'
dayk_path = '../data/data_dayk.parquet'
minute_data_dir = '../data/data_mink'               # 原始分钟分片数据目录
minute_data_preprocessed_dir = '../data/data_mink_product' # 预处理后按 uid 存储的分钟数据目录
minute_index_path = '../data/minute_index.parquet'  # 索引文件保存路径
main_mink_folder = '../data/main_mink/'             # 输出分钟主力序列文件夹
roller_info_path = '../data/roller_info.csv'        # 展期信息输出路径
main_dayk_folder = '../data/main_dayk/'             # 日线主力序列输出文件

def preprocess_minute_data(minute_raw_dir: str, minute_product_dir: str, force_rebuild: bool = True):
    """并行预处理分钟数据，生成每个 uid 的独立 parquet 文件"""
    import shutil
    from pandarallel import pandarallel

    if not force_rebuild and os.path.exists(minute_product_dir) and len(os.listdir(minute_product_dir)) > 0:
        print("Minute product data already exists. Skipping rebuild.")
        return

    if os.path.exists(minute_product_dir):
        shutil.rmtree(minute_product_dir)
    os.makedirs(minute_product_dir, exist_ok=True)

    print("Loading all minute data...")
    all_data = pd.concat([pd.read_parquet(os.path.join(minute_raw_dir, f))
                          for f in os.listdir(minute_raw_dir) if f.endswith('.parquet')], ignore_index=True)
    print(f"Total rows: {len(all_data)}")

    pandarallel.initialize(progress_bar=True)

    def process_group(group):
        uid = group['unique_instrument_id'].iloc[0]
        out_path = os.path.join(minute_product_dir, f"{uid}.parquet")
        group.drop_duplicates(subset='trade_timestamp').sort_values('trade_timestamp').to_parquet(out_path, index=False)

    all_data.groupby('unique_instrument_id').parallel_apply(process_group)  # type: ignore

    del all_data
    import gc
    gc.collect()

    print("\nMinute data preprocessing completed.")

def generate_main_contract_series(contract_start_end_path: str|pd.DataFrame = contract_mapping_path, 
                                  dayk_path: str = dayk_path,
                                  minute_data_dir: str = minute_data_dir, 
                                  minute_data_preprocessed_dir: str = minute_data_preprocessed_dir,
                                  main_mink_folder_path: str = main_mink_folder, 
                                  main_dayk_folder_path: str = main_dayk_folder, 
                                  roller_info_path: str = roller_info_path, 
                                  products_list: list = [],
                                  rebuild_minute_product: bool = True,
                                  rebuild_roller_info: bool = False,) -> pd.DataFrame:
    """
    增量更新主力合约序列（仅追加尾部新合约，不修改历史）
    使用分钟数据索引，按需加载分钟数据。
    """
    # ========== 1. 处理分钟索引 ==========
    if rebuild_minute_product:
        preprocess_minute_data(minute_data_dir, minute_data_preprocessed_dir, force_rebuild=True)

    # ========== 2. 加载已有 roller_info ==========
    existing = pd.DataFrame(columns=['PRODUCT', 'CONTRACT', 'STARTDATE', 'ENDDATE', 'PREV_CLOSE', 'END_CLOSE', 'FORWARD_BASE_DATE', 'FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO'])
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
        
        df_dayk = dayk_groups.get(row['CONTRACT_UID'], pd.DataFrame(columns=['trading_day', 'close_price']))
        left = df_dayk['trading_day'].searchsorted(row['STARTDATE'], side='left')
        right = df_dayk['trading_day'].searchsorted(row['ENDDATE'], side='right')
        interval_data = df_dayk.iloc[left:right]
        end_close = interval_data['close_price'].iloc[-1] if not interval_data.empty else np.nan
        
        def load_contract_data_mink(uid: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
            file_path = os.path.join(minute_data_preprocessed_dir, f"{uid}.parquet")
            if not os.path.exists(file_path):
                return pd.DataFrame(columns=['trading_day', 'close_price', 'trade_time'])
            return ((df := pd.read_parquet(file_path, filters=[('trading_day', '>=', start_date), ('trading_day', '<=', end_date)]))
                .assign(trading_day=pd.to_datetime(df['trading_day']))).rename(columns={'unique_instrument_id': 'contract_uid'})
        df_mink = load_contract_data_mink(row['CONTRACT_UID'], row['STARTDATE'], row['ENDDATE'])
        
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
    info_df = pd.concat([existing.drop(columns=['FORWARD_FACTOR', 'BACKWARD_FACTOR', 'ADJ_RATIO']), added_df], ignore_index=True) if not existing.empty else added_df
    info_df = info_df.sort_values(['PRODUCT', 'STARTDATE']).reset_index(drop=True)

    info_df['HAS_DATA'] = info_df['END_CLOSE'].notna()
    block_start = (info_df['PRODUCT'] != info_df['PRODUCT'].shift(1)) | (info_df['HAS_DATA'] & ~info_df['HAS_DATA'].shift(1).fillna(False).astype(bool))
    info_df['BLOCK_ID'] = block_start.cumsum()
    info_df['FORWARD_BASE_DATE'] = pd.to_datetime(info_df.groupby('BLOCK_ID')['FORWARD_BASE_DATE'].ffill())

    def compute_factors(block):
        block['ADJ_RATIO'] = (block['PREV_CLOSE'] / block['END_CLOSE'].shift(1)).fillna(1)
        block['FORWARD_FACTOR'] = block['ADJ_RATIO'].cumprod()
        block['BACKWARD_FACTOR'] = block['ADJ_RATIO'].iloc[::-1].cumprod().shift(1).fillna(1).iloc[::-1]
        return block
    
    valid_rows = info_df[info_df['HAS_DATA']].groupby(['PRODUCT', 'FORWARD_BASE_DATE'], group_keys=False).apply(compute_factors)
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
        product_data = {}
        for idx, df in tqdm(enumerate(pieces), desc=f"Asserting ADJ cols to {name} Main Series", position=0, leave=True, mininterval=0.5):
            if df.empty or not added_df.iloc[idx]['IS_LAST_BLOCK']: continue;
            df = df.assign(adjustment_mul=added_df.iloc[idx]['BACKWARD_FACTOR'], adjustment_add=0.0)
            product_data.setdefault(added_df.iloc[idx]['PRODUCT'], []).append(df)

        added_first = {uid: group.iloc[0] for uid, group in added_df.groupby('PRODUCT')}
        for product, df_list in tqdm(product_data.items(), desc=f"Saving {name} Main Series", position=0, leave=True, mininterval=0.5):
            save_path = os.path.join(main_folder_path, f"{product}.parquet")
            if product in overlapped_products and os.path.exists(save_path):
                existing_df = (tdf := pd.read_parquet(save_path, filters=[('trading_day', '<', added_first[product]['STARTDATE'])])).assign(trading_day=pd.to_datetime(tdf['trading_day']))
                existing_df['adjustment_mul'] *= added_first[product]['BACKWARD_FACTOR'] # 后复权
                df_list = [existing_df] + df_list
            product_df = pd.concat(df_list, ignore_index=True).assign(unique_instrument_id=product).sort_values('trade_time')
            product_df.to_parquet(save_path, index=False)
    
    return info_df

# 使用示例
if __name__ == '__main__':
    # 测试截断再补全
    test_products = []
    # test_products = ['A.DCE', 'AD.SHF', 'AD_S.SHF', 'AF-S.CFE', 'AG.SHF', 'AG_S.SHF']
    
    if test_products:
        cutoff = pd.to_datetime('2025-05-30').strftime('%Y%m%d')
        # 截断合约映射表，只保留 STARTDATE <= cutoff_date 的合约
        def _cutoff(g): g.iloc[-1] = cutoff; return pd.to_datetime(g)
        df = ((df := pd.read_parquet(contract_mapping_path, 
                filters=[('S_INFO_WINDCODE', 'in', test_products), ('STARTDATE', '<=', cutoff)])
            .rename(columns={'S_INFO_WINDCODE': 'PRODUCT', 'FS_MAPPING_WINDCODE': 'CONTRACT'})
            .sort_values(['PRODUCT', 'STARTDATE']))
            .assign(ENDDATE=df.groupby('PRODUCT')['ENDDATE'].transform(_cutoff))
            .assign(STARTDATE=pd.to_datetime(df['STARTDATE']))
            .reset_index(drop=True))

        # 调用主函数
        df = generate_main_contract_series(
            contract_start_end_path=df,
            rebuild_roller_info=True, # 强制重建展期信息，覆盖原文件
            rebuild_minute_product=False, # 不强制重建分钟数据，假设之前已经处理过了
        )
        print(df)

        # 增量更新（假设有新数据）
        df = generate_main_contract_series(
            products_list=test_products, # 只更新测试产品
            rebuild_minute_product=False, # 不重建分钟数据，使用之前处理好的数据
        )
        print(df)

    else:
        df = generate_main_contract_series(
            rebuild_roller_info=True,
            rebuild_minute_product=False,
        )
        print(df)