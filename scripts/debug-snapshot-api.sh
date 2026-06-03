#!/bin/bash
# [DEBUG-snapshot] 直接测试 /get_group_snapshot API
# 用法: bash scripts/debug-snapshot-api.sh

BASE="${1:-http://localhost:8000}"

echo "=== 测试 /get_group_snapshot ==="

# 1. 获取所有提交，找到最新的分组测试提交
echo "--- 获取提交列表 ---"
SUBS=$(curl -s -b /tmp/cookies.txt -c /tmp/cookies.txt "$BASE/api/submissions" 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
if isinstance(data, list):
    subs = [s for s in data if s.get('module') == 'single_factor_test' and s.get('test_type') == 'group']
    if subs:
        print(subs[-1].get('id',''))
")
echo "submission_id=$SUBS"

if [ -z "$SUBS" ]; then
    echo "❌ 没有找到分组测试提交，请先运行一次分组测试"
    exit 1
fi

# 2. 获取分组结果概览，找一个 timestamp
echo "--- 获取分组结果 ---"
RESULT=$(curl -s -b /tmp/cookies.txt "$BASE/get_group_result?submission_id=$SUBS" 2>/dev/null)
TIMESTAMPS=$(echo "$RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
groups = data.get('groups', [])
if groups:
    ts = groups[0].get('timestamps', [])
    if ts:
        print(ts[0])
" 2>/dev/null)
echo "timestamp=$TIMESTAMPS"

if [ -z "$TIMESTAMPS" ]; then
    echo "❌ 无法获取时间戳"
    echo "$RESULT" | python3 -m json.tool 2>/dev/null | head -30
    exit 1
fi

# 3. 调用 snapshot API
echo "--- 调用 snapshot API ---"
SNAP=$(curl -s -b /tmp/cookies.txt -X POST "$BASE/get_group_snapshot" \
    -H 'Content-Type: application/json' \
    -d "{\"submission_id\": $SUBS, \"timestamp_ms\": $TIMESTAMPS}" 2>/dev/null)

echo "$SNAP" | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data.get('success'):
    groups = data.get('groups', [])
    print(f'✅ 成功! {len(groups)} 组, has_prev={data.get(\"has_prev\")}, has_next={data.get(\"has_next\")}')
    for g in groups:
        prods = g.get('products', [])
        print(f'  {g[\"name\"]}: {len(prods)} 产品, turnover={g.get(\"turnover_rate\")}')
        if prods:
            p0 = prods[0]
            print(f'    首产品: name={p0.get(\"name\")}, amount={p0.get(\"amount\")}, pending_exit={p0.get(\"pending_exit\")}')
else:
    print(f'❌ 失败: {data.get(\"error\")}')
    if data.get('traceback'):
        print(data['traceback'][:500])
"
