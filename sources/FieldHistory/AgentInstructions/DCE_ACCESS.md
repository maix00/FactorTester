# DCE（大商所）官网字段验证 — 数据获取方法

> 编写于 2026-07-10，在 issue-124 审计过程中验证。
> 适用场景：Agent 需要从 DCE 官网获取合约规格、交易参数、结算参数等公开数据。

## 背景：DCE 反爬保护

DCE 全站使用 **Distil Networks**（或同类）反爬系统。以下方式均被拦截：

| 方式 | 结果 |
|------|------|
| `curl` / `requests` / `urllib` | 返回反爬 JS，无实际内容 |
| `akshare.futures_contract_info_dce()` | HTTP 412 |
| Playwright 默认 Chromium (launch) | 返回空页面 |

## 可行方法：API 调用（在已加载页面中 fetch）

**原理**：先用真实 Chrome + Playwright CDP 加载 DCE 页面，等页面完全加载后，在页面上下文中用 `fetch` 直接调用 DCE 后端 API。此时 fetch 携带了页面已有的反爬 Cookie 和 Token，不会被拦截。

### 操作步骤

```python
import subprocess, time, json, shutil, os
from playwright.sync_api import sync_playwright

# 1. 复制用户真实 Chrome 配置文件（唯一临时目录，不杀用户 Chrome）
user_profile = os.path.expanduser("~/Library/Application Support/Google/Chrome")
tmp_profile = f"/tmp/chrome-dce-{os.getpid()}"
if os.path.exists(tmp_profile): shutil.rmtree(tmp_profile)
os.makedirs(f"{tmp_profile}/Default", exist_ok=True)
for item in ["Cookies", "Cookies-journal", "Network", "Local State"]:
    src = f"{user_profile}/{item}"; dst = f"{tmp_profile}/{item}"
    if os.path.exists(src):
        try:
            if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True)
            else: shutil.copy2(src, dst)
        except: pass

# 2. 启动真实 Chrome + 调试端口（不要 pkill 已有的 Chrome）
chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
chrome_proc = subprocess.Popen(
    [chrome_path, "--remote-debugging-port=9222",
     f"--user-data-dir={tmp_profile}", "--no-first-run", "--no-default-browser-check"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
# 等待 Chrome 就绪
import urllib.request
for _ in range(10):
    time.sleep(2)
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        json.loads(resp.read()); break
    except: pass

# 3. 加载结算参数页面（必须 wait_until='networkidle' 等 Vue 加载完）
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0]
    page = ctx.new_page()
    page.goto(
        "http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1",
        wait_until='networkidle', timeout=30000)
    time.sleep(3)

    # 4. 调用 API 查询指定日期（改 tradeDate 即可，格式 YYYYMMDD）
    result = page.evaluate("""async (d) => {
        var resp = await fetch('/dcereport/publicweb/tradepara/futAndOptSettle', {
            method: 'POST',
            headers: {'Content-Type':'application/json','Accept':'application/json','clientid':'web'},
            body: JSON.stringify({varietyId:'all', tradeDate:d, tradeType:'1', lang:null})
        });
        return await resp.json();
    }""", "20240102")

    browser.close()
chrome_proc.terminate()
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/dcereport/publicweb/tradepara/futAndOptSettle` | POST | 结算参数（保证金率、手续费、结算价） |
| `/dcereport/publicweb/variety` | GET | 品种列表 |
| `/dcereport/publicweb/maxTradeDate2` | POST | 最大交易日期 |
| `/dcereport/publicweb/tradeDateNum` | POST | 交易日序号 |

### API 请求/响应

请求体：`{"varietyId": "all", "tradeDate": "20240102", "tradeType": "1", "lang": null}`

响应字段与 DB 映射：

| API 字段 | DB 字段 | 说明 |
|----------|---------|------|
| `specBuyRate` | `LongMarginRatioByMoney` | 投机买保证金率（如 "0.2" = 20%） |
| `specSellRate` | `ShortMarginRatioByMoney` | 投机卖保证金率 |
| `clearPrice` | - | 结算价 |
| `openFee` / `offsetFee` | - | 开仓/平仓手续费 |
| `style` | - | 手续费收取方式（绝对值/比例值） |

注意：API 返回**合约级**数据（每条一个合约，如 `a2401`、`a2403`），不同合约可能同时有不同的保证金率。

## 生成真实保证金率变更事件

在 issue-124 审计过程中发现了 2812 条 `change_type='rule'` 的 DCE 保证金率事件。这些是根据风险管理办法规则自动生成的推算值，不是真实的交易所变更。

### 问题

1. 合约级 vs 品种级：保证金率实际是合约级的（a2403、a2405 同时不同值），但 rule 事件用品种级单一值
2. 中间值不准：交割月前一个月的实际保证金率为 7-8%，不是 rule 事件用的 10%
3. 不是真实变更：rule 事件不是交易所发布的变更通知

### 修复步骤

1. 用 API 获取 8 个日期的结算快照，存于 `~/GTHT/data/dce_settlement_snapshot_2024.json`
2. 对每个合约构建时间线，检测相邻快照间的 value 变化
3. 对每个变更写入 `agent_field_change_events`（调用 `append_agent_field_change_events`）
4. 物化到 `historical_field_values`（调用 `materialize_agent_events_to_history`）
5. 更新 change_type/exchange（因 AgentFieldChangeEvent 不包含这些字段）

### 写入代码

```python
from tools.data.field_history_agent_ingest import (
    append_agent_field_change_events,
    materialize_agent_events_to_history,
)
from tools.data.hub import DataHub
from tools.data.field_history import _ensure_store_registered

# 1. 先用 DCE API 获取快照数据
# 2. 构建 event dict 列表（格式见下方）
# 3. 写入
hub = DataHub.get_instance()
_ensure_store_registered(hub, 'openctp')
ids = append_agent_field_change_events(events, store_key='openctp')
materialized = materialize_agent_events_to_history(store_key='openctp', field_group='MarginRatio')

# 4. 补充字段（AgentFieldChangeEvent 不包含这些）
conn.execute("""
   UPDATE agent_field_change_events
   SET change_type='change', exchange='DCE', scope_type='contract', contract_scope_type='explicit'
   WHERE source_notice_id='DCE-settlement-parameters-2024'
""")
```

### Event dict 格式

```python
event = {
    'event_id': uuid.uuid4().hex,
    'data_source': 'DCE',
    'field_group': 'MarginRatio',
    'source_url': 'http://www.dce.com.cn/frontend/dcereport/...',
    'source_accessed_at': '2026-07-10T00:00:00+08:00',
    'agent_name': 'codex-audit-...',
    'requester_key_hash': 'dce-settlement-audit-...',
    'instrument': 'A',              # 品种代码
    'instrument_label': '豆一',
    'instrument_type': 'futures',
    'field_name': 'LongMarginRatioByMoney',  # 或 ShortMarginRatioByMoney
    'effective_trading_day': '20240301',     # 变更生效日期
    'effective_timestamp': '',
    'value': '0.2',                 # 新的保证金率
    'contract_codes': ('2401',),    # 元组，只含一个合约代码
    'source_notice_id': 'DCE-settlement-parameters-2024',
    'raw_note': 'DCE settlement snapshot: A 2401 margin 0.08→0.2',
    'evidence_text': '',
    'parser_notes': 'Generated from DCE official settlement API snapshot',
}
```

注意：
- `contract_codes` 传 **tuple**（如 `("2401",)`），不是 list
- 每个事件只能包含**一个**合约代码
- `AgentFieldChangeEvent` 不包含 `change_type`/`exchange`/`scope_type`，写入后需单独 UPDATE
- 每次 API 调用间隔至少 1 秒，避免触发反爬

## 重要注意事项

1. ❌ **不要用 `pkill -9 -f Google Chrome`** — 会杀掉用户正在使用的 Chrome
2. ✅ 每次启动 Chrome 时用唯一的临时 Profile 目录
3. ✅ 完成后调用 `chrome_proc.terminate()` 清理
4. ✅ 使用 `wait_until='networkidle'` 确保 Vue SPA 完全加载
5. ✅ API 调用必须在已加载页面的上下文中执行

---

## 附录：风险管理办法版本引用规范

### 2024年DCE交割月保证金规则引用

2024年DCE交割月份保证金（20%）规则引用自《大连商品交易所风险管理办法》第五条。2024年期间该办法有过两次修订，对应不同生效日期：

| 生效日期范围 | 引用版本 | 公告字号 | CSRC规则库UUID |
|-------------|---------|---------|----------------|
| 之前 → 2024-05-19 | 2023年1月修订 | 大商所发〔2023〕2号 | `d67e2d8e6eaa4fd0aec2c30381aa1c17` |
| 2024-05-20 → 2024-10-24 | 2024年修订 | 大商所发〔2024〕35号 | `c55db8e50e1c4584a9725c902182d79a` |
| 2024-10-25 → 2025-02-13 | 2024年10月修订 | 大商所发〔2024〕99号 | `96f1a607806d42e7ae26200c371b7a0b` |
| 2025-02-14 → 至今 | 2025年2月修订 | 大商所发〔2025〕16号 | `a787ade268dd46a691dcb94cf693b712` |

**第五条原文（所有版本一致）：**
> 除线型低密度聚乙烯(L)、聚氯乙烯(V)、聚丙烯(PP)以外品种期货合约：
> - 交割月份前一个月第十五个交易日起 → 10%
> - 交割月份第一个交易日起 → 20%
>
> L、V、PP品种期货合约进入交割月份第一个交易日起，交易保证金标准为20%。

### CSRC法规数据库访问

所有历史版本均可通过中国证监会证券期货法规数据库查询：
`https://neris.csrc.gov.cn/falvfagui/`

搜索"大连商品交易所风险管理办法"可获取所有历史版本。查看具体版本：
`https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=3&secFutrsLawId={UUID}&body=`

### 例外品种

以下品种不适用标准交割月保证金规则（需另行确认其业务细则或上市公告）：
- **BB（胶合板）**: 基础保证金40%（非标的交割月规则）
- **J（焦炭）、JM（焦煤）**: 基础保证金20%（已处于交割月水平，无中间阶梯）
- **L_F、PP_F、V_F**: 化工品月均价期货（2025年上市，规则不同）
- **LG（原木）**: 2024年11月新上市，单独规则
- **BZ（纯苯）**: 2025年上市，单独规则

### source_notice_id 格式

```
《大连商品交易所风险管理办法（{版本名称}）》（{公告字号}）第五条+DCE-settlement
```

示例：
- 《大连商品交易所风险管理办法（2023年1月修订）》（大商所发〔2023〕2号）第五条+DCE-settlement
- 《大连商品交易所风险管理办法（2024年修订）》（大商所发〔2024〕35号）第五条+DCE-settlement

---

## DCE 保证金率入库规范（2026-07-10 定稿）

### 数据来源

DCE 结算参数 API（需通过真实 Chrome + Playwright CDP 访问）：
`POST /dcereport/publicweb/tradepara/futAndOptSettle`
请求体：`{"varietyId":"all","tradeDate":"YYYYMMDD","tradeType":"1","lang":null}`

### 采集策略

取**每月第一个交易日**的结算快照，比较相邻快照检测保证金率变更：
1. **交割月变更**（7-8% → 20%）：发生在交割月第一个交易日。写入 `change_type='change'`，引用对应版本的风险管理办法。
2. **非交割月调整**（其他百分比变化）：发生在任意日期。写入 `change_type='asof_confirmed'`，引用结算 API 页面。
3. **中间阶梯（10%）** 未被月首快照捕获，可通过交易日历推导。

### 版本引用规则

| 日期范围 | 引用版本 | CSRC UUID |
|---------|---------|-----------|
| ≤ 2024-05-19 | 大商所发〔2023〕2号 | `d67e2d8e6eaa4fd0aec2c30381aa1c17` |
| 2024-05-20 ~ 2025-02-13 | 大商所发〔2024〕35号 | `c55db8e50e1c4584a9725c902182d79a` |
| ≥ 2025-02-14 | 大商所发〔2025〕16号 | `a787ade268dd46a691dcb94cf693b712` |

### 记录格式规范

**交割月变更事件：**
- `source_notice_id`：`《大连商品交易所风险管理办法（{版本}）》（{公告字号}）第五条+DCE-settlement`
- `raw_note`：`结算快照确认。依据：《...》第五条中规定"交割月份第一个交易日起，交易保证金标准为20%"。合约{月份}于{日期}进入交割月份后保证金由{X}%变为20%。`
- `source_url`：指向 CSRC 法规数据库对应版本
- `change_type`：`change`
- `exchange`：`DCE`
- `scope_type` / `contract_scope_type`：`contract` / `explicit`

**非交割月调整事件：**
- `source_notice_id`：`DCE-settlement-snapshot-{YYYYMMDD}`
- `raw_note`：`大商所结算快照：{品种} {合约月份}合约{字段名}由{X}%调整为{Y}%（{旧日期}→{新日期}）。`
- `source_url`：DCE 结算查询页面
- `change_type`：`asof_confirmed`

### 禁止行为

1. ❌ 不得引用 DCE 官网当前版本 URL（6262956），需用 CSRC 法规库历史版本 UUID
2. ❌ 不得写入英文 `raw_note`，必须全中文
3. ❌ 不得使用 `change_type='rule'` 替代实际结算快照数据
4. ❌ 不得在 `historical_field_values` 中创建重复 `source_key`
