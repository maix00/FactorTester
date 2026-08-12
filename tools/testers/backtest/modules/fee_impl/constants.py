FEE_FIELDS = (
    "OpenRatioByMoney",
    "OpenRatioByVolume",
    "CloseRatioByMoney",
    "CloseRatioByVolume",
    "CloseTodayRatioByMoney",
    "CloseTodayRatioByVolume",
)

CUSTOM_FEE_FIELDS = (
    {"value": "OpenRatioByMoney", "label": "开仓费率", "unit": "ratio", "value_type": "number", "allow_time_range": True},
    {"value": "OpenRatioByVolume", "label": "开仓固定费", "unit": "currency/lot", "value_type": "number", "allow_time_range": True},
    {"value": "CloseRatioByMoney", "label": "平仓费率", "unit": "ratio", "value_type": "number", "allow_time_range": True},
    {"value": "CloseRatioByVolume", "label": "平仓固定费", "unit": "currency/lot", "value_type": "number", "allow_time_range": True},
    {"value": "CloseTodayRatioByMoney", "label": "平今费率", "unit": "ratio", "value_type": "number", "allow_time_range": True},
    {"value": "CloseTodayRatioByVolume", "label": "平今固定费", "unit": "currency/lot", "value_type": "number", "allow_time_range": True},
)
