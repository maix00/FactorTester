# GFEX（广期所）数据入库规范

## 数据获取

通过 akshare 获取（SSL 证书问题阻止直接 HTTP）：
```python
import akshare as ak
df = ak.futures_settle_gfex(date="20240102")
```

**字段映射：** `spec_buy_rate` → `LongMarginRatioByMoney` / `ShortMarginRatioByMoney`

## 版本引用

使用《广州期货交易所风险控制管理办法》。
