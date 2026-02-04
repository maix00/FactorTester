"""
本文件用于处理期货数据，将所有数据文件（parquet格式）合并后，按unique_instrument_id分组，去除重复的trade_timestamp并排序，最终将每个unique_instrument_id对应的数据保存为单独的CSV文件。输出文件夹如已存在则自动重命名备份。
主要流程：
1. 检查并处理输出文件夹的命名冲突。
2. 读取所有唯一的instrument_id。
3. 合并所有parquet数据文件。
4. 按unique_instrument_id筛选、去重、排序数据。
5. 将结果保存为CSV文件。
"""

import pandas as pd
import os
from tqdm import tqdm
import shutil

# 文件路径
unique_ids_file = './futures_data/unique_instrument_ids.txt'
data_folder = '../data/data_mink/'
output_folder = '../data/data_mink_product/'

# 处理输出文件夹命名冲突
if os.path.exists(output_folder):
    shutil.rmtree(output_folder)
os.makedirs(output_folder, exist_ok=True)

# 读取唯一的instrument_id
with open(unique_ids_file, 'r') as f:
    unique_instrument_ids = [line.strip() for line in f.readlines()]

# 缓存加载的数据
all_data = None

# 遍历每个unique_instrument_id
for unique_id in tqdm(unique_instrument_ids):
    combined_data = pd.DataFrame()
    
    # 第一次循环时读取所有数据文件
    if all_data is None:
        all_data = pd.DataFrame()
        data_list = []
        for filename in os.listdir(data_folder):
            if filename.endswith('.parquet'):
                file_path = os.path.join(data_folder, filename)
                data_list.append(pd.read_parquet(file_path))
        all_data = pd.concat(data_list, ignore_index=True)
    
    # 筛选匹配的unique_instrument_id
    filtered_data = all_data[all_data['unique_instrument_id'] == unique_id]

    # 去除重复的timestamp并排序
    filtered_data = filtered_data.drop_duplicates(subset='trade_timestamp').sort_values(by='trade_timestamp')

    # 保存到Parquet文件
    output_file_path = os.path.join(output_folder, f'{unique_id}.parquet')
    filtered_data.to_parquet(output_file_path, index=False)

# End of file futures_data/check_3.py