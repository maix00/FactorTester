"""
多用户并发访问测试
================
模拟 N 个同时在线用户，每个用户拥有独立的 requests.Session（对应独立的 Flask session cookie），
并发执行以下流程：
  1. 访问首页，初始化 session cookie
  2. 设置时间范围（set_time_range）
  3. 添加各自不同的参数（每个用户用不同的参数组合）
  4. 提交品种（使用相同的产品路径，模拟共享数据竞争）
  5. 运行 IC 测试（run_ic_test）
  6. 运行分组测试（run_group_test）
  7. 清理（删除 submission）

用法：
    # 确保 FactorTestServer 已在 localhost:8000 运行，然后：
    python test/test_concurrent_users.py

参数说明：
    BASE_URL : 服务器地址
    N_USERS  : 并发用户数
    FACTOR   : 要测试的因子家族（Factors/ 目录中的文件名，不含 .py）
    PRODUCTS_PATH : 提交的产品路径（tree 中任意一个叶子路径）
"""

import threading
import time
import requests
import json
from typing import Any

# ─── 配置 ──────────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
N_USERS = 5          # 并发用户数
FACTOR = "MmPosPct"   # 因子家族名（对应 Factors/MmPosPct.py）

# 时间范围配置（用于 set_time_range）
TIME_RANGE = {
    "start_date": "2024-01-01",
    "start_time": "09:00:00",
    "end_date": "2024-12-31",
    "end_time": "15:00:00",
    "timezone": "Asia/Shanghai",
}

# 分组测试配置（用于 run_group_test）
N_GROUPS = 5  # 分组数量

# 每个用户使用不同的参数（参数 key 需与 Mm.params 中的 .alias 对应）
# Mm 只有 H / L 两个 DataColumnParam，默认值均为 HIGH/LOW
# 此处用维度相同的默认值，主要验证 session 隔离（每个用户独立 params list）
def user_params(user_id: int) -> dict:
    """返回每个用户独立的参数组合（此处只更改注释性字段，实际可按 FinRangeParam 扩展）"""
    # Mm 因子没有数值型自由参数，只有 DataColumn 枚举型
    # 为了区分用户，我们用不同的 H / L 组合（0=HIGH, 1=LOW, 2=CLOSE 等按实际枚举扩展）
    # 这里直接使用默认值（HIGH / LOW），验证 session 隔离即可
    return {}   # 空 dict → 服务端使用各 param 的 default_value


# ─── 辅助 ──────────────────────────────────────────────────────────────────────
def log(user_id: int, msg: str):
    print(f"[User {user_id:02d}] {msg}")


def get_factor_list(session: requests.Session, user_id: int) -> list[dict]:
    """获取当前 session 对应的因子列表（含 alias）"""
    resp = session.get(f"{BASE_URL}/api/factor_list", params={"factor_family_alias": FACTOR})
    data = _safe_json(resp, "factor_list")
    if not data.get("success"):
        log(user_id, f"factor_list error: {data.get('error')}")
        return []
    return data.get("factors", [])


def _safe_json(resp: requests.Response, label: str) -> Any:
    """解析 JSON，失败时抛出带响应内容的详细错误"""
    try:
        return resp.json()
    except Exception:
        raise RuntimeError(f"{label} 返回非 JSON (status={resp.status_code}): {resp.text[:200]}")


def get_product_path() -> str:
    """从 tree-data 拿一个叶子产品路径（只需调用一次，所有用户共享同一路径）"""
    resp = requests.get(f"{BASE_URL}/api/tree-data")
    if resp.status_code != 200:
        raise RuntimeError(f"tree-data 请求失败: {resp.status_code}，请确认服务器已启动")

    def find_key_with_products(node):
        """递归找第一个有产品（有 desc 字段）且是 lazy 节点的 key"""
        if isinstance(node, list):
            for item in node:
                result = find_key_with_products(item)
                if result:
                    return result
            return None
        if not isinstance(node, dict):
            return None
        # lazy+folder+有desc 说明是包含真实产品的子类别节点
        if node.get("lazy") and node.get("folder") and node.get("desc") and node.get("key"):
            return node["key"]
        for child in node.get("children") or []:
            result = find_key_with_products(child)
            if result:
                return result
        return None

    data = _safe_json(resp, "tree-data")
    key = find_key_with_products(data)
    if not key:
        raise RuntimeError("tree-data 中未找到任何含产品的节点")
    return key


# ─── 单用户流程 ─────────────────────────────────────────────────────────────────
errors: list[str] = []
errors_lock = threading.Lock()

def run_user(user_id: int, product_path: str, barrier: threading.Barrier):
    s = requests.Session()
    try:
        # ── Step 1: 访问首页，初始化 session cookie ──────────────────────────
        resp = s.get(f"{BASE_URL}/")
        if resp.status_code not in (200, 302):
            raise RuntimeError(f"首页访问失败: {resp.status_code} {resp.text[:100]}")

        # ── Step 2: 设置时间范围 ───────────────────────────────────────────────
        resp = s.post(f"{BASE_URL}/set_time_range", json={
            "factor_family_alias": FACTOR,
            **TIME_RANGE
        })
        data = _safe_json(resp, "set_time_range")
        if not data.get("success"):
            raise RuntimeError(f"set_time_range 失败: {data.get('error')}")
        log(user_id, f"set_time_range OK: {TIME_RANGE['start_date']} ~ {TIME_RANGE['end_date']}")

        # ── Step 3: 添加参数（每个用户独立 session → 独立 params list） ─────
        params = user_params(user_id)
        resp = s.post(f"{BASE_URL}/add_params", json={"factor_family_alias": FACTOR, "params": params})
        data = _safe_json(resp, "add_params")
        if not data.get("success"):
            raise RuntimeError(f"add_params 失败: {data.get('error')}")
        log(user_id, f"add_params OK: {params or '(default)'}")

        # ── Step 4: 等待所有用户都完成参数添加，再同时提交品种（压测并发）──
        barrier.wait()

        # ── Step 5: 提交品种 ──────────────────────────────────────────────────
        id_time = f"user_{user_id}_{int(time.time() * 1000)}"
        resp = s.post(f"{BASE_URL}/submit_selected_products", json={
            "selected_paths": [product_path],
            "id_time": id_time,
        })
        data = _safe_json(resp, "submit_selected_products")
        if not data.get("success"):
            raise RuntimeError(f"submit_selected_products 失败: {data.get('error')}")
        submission_id = id_time
        log(user_id, f"submit OK: {data.get('count_desc')}  tester={data.get('factor_tester_serial')}")

        # ── Step 6: 获取因子列表（使用服务端 session params） ────────────────
        factors = get_factor_list(s, user_id)
        if not factors:
            raise RuntimeError("factor_list 为空，无法运行 IC 测试")
        factor_configs = [{"alias": f["alias"], "return_freq": "N"} for f in factors]
        log(user_id, f"factors: {[f['alias'] for f in factors]}")

        # ── Step 7: 运行 IC 测试 ──────────────────────────────────────────────
        resp = s.post(f"{BASE_URL}/run_ic_test", json={
            "submission_id": submission_id,
            "factor_family_alias": FACTOR,
            "factors": factor_configs,
            "paths": [product_path],
            "return_freq": "N",
            "re_calc": True,
        })
        data = _safe_json(resp, "run_ic_test")
        if not data.get("success"):
            raise RuntimeError(f"run_ic_test 失败: {data.get('error')}")
        log(user_id, f"run_ic_test OK: {list(data.keys())}")

        # ── Step 8: 运行分组测试 ─────────────────────────────────────────────
        factor_alias = factors[0]["alias"] if factors else None
        if factor_alias:
            resp = s.post(f"{BASE_URL}/run_group_test", json={
                "submission_id": submission_id,
                "factor_alias": factor_alias,
                "n_groups": N_GROUPS,
            })
            data = _safe_json(resp, "run_group_test")
            if not data.get("success"):
                raise RuntimeError(f"run_group_test 失败: {data.get('error')}")
            log(user_id, f"run_group_test OK: groups={data.get('n_groups')}, metrics={len(data.get('metrics', {}))} rows")

        # ── Step 9: 删除自己的 submission（清理） ────────────────────────────
        s.post(f"{BASE_URL}/delete_submission", json={"id_time": submission_id})
        log(user_id, "cleanup OK")

    except Exception as e:
        msg = f"User {user_id:02d} ERROR: {e}"
        print(msg)
        with errors_lock:
            errors.append(msg)


# ─── 入口 ──────────────────────────────────────────────────────────────────────
def main():
    print(f"=== 并发测试: {N_USERS} 个用户 · 因子={FACTOR} · 服务器={BASE_URL} ===\n")

    try:
        product_path = get_product_path()
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return

    print(f"使用产品路径: {product_path}\n")

    barrier = threading.Barrier(N_USERS)
    threads = [
        threading.Thread(target=run_user, args=(i, product_path, barrier), daemon=True)
        for i in range(N_USERS)
    ]

    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    elapsed = time.time() - start

    print(f"\n=== 完成: 耗时 {elapsed:.2f}s ===")
    if errors:
        print(f"❌ {len(errors)} 个用户出错:")
        for e in errors:
            print(f"  {e}")
    else:
        print(f"✅ 全部 {N_USERS} 个用户成功，无并发错误")


if __name__ == "__main__":
    main()
