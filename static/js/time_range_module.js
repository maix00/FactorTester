// 时间范围模块功能

function initTimeRangeModule(factorFamilyAlias) {
    var startDateInput = document.getElementById('start_date');
    var startTimeInput = document.getElementById('start_time');
    var endDateInput = document.getElementById('end_date');
    var endTimeInput = document.getElementById('end_time');
    var tradingDayCheckbox = document.getElementById('is_trading_day');
    var timezoneSelect = document.getElementById('timezone_select');
    var confirmBtn = document.getElementById('confirm_time_btn');
    var statusSpan = document.getElementById('confirm_time_status');
    
    if (!confirmBtn) return;
    
    function updateCurrentSettings() {
        var startDate = startDateInput.value;
        var endDate = endDateInput.value;
        
        var isValid = startDate <= endDate;
        
        if (isValid) {
            confirmBtn.disabled = false;
            confirmBtn.style.background = '#0078d4';
            if (statusSpan) {
                statusSpan.innerText = '点击确定按钮更新因子计算的时间范围';
                statusSpan.style.color = '#888';
            }
        } else {
            confirmBtn.disabled = true;
            confirmBtn.style.background = '#ccc';
            if (statusSpan) {
                statusSpan.innerText = '⚠️ 起始时间必须 ≤ 终末时间';
                statusSpan.style.color = '#d40000';
            }
        }
    }
    
    function confirmTimeRange() {
        var data = {
            factor_family_alias: factorFamilyAlias,
            start_date: startDateInput.value,
            start_time: startTimeInput.value,
            end_date: endDateInput.value,
            end_time: endTimeInput.value,
            is_trading_day: tradingDayCheckbox ? tradingDayCheckbox.checked : false,
            timezone: timezoneSelect ? timezoneSelect.value : 'Asia/Shanghai'
        };
        
        if (statusSpan) {
            statusSpan.innerText = '保存中...';
            statusSpan.style.color = '#0078d4';
        }
        
        fetch('/set_time_range', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            if (statusSpan) {
                if (data.success) {
                    statusSpan.innerText = '✓ 已保存，时间范围已更新';
                    statusSpan.style.color = '#28a745';
                    setTimeout(function() {
                        if (statusSpan.innerText === '✓ 已保存，时间范围已更新') {
                            statusSpan.innerText = '';
                        }
                    }, 3000);
                } else {
                    statusSpan.innerText = '保存失败: ' + (data.error || '未知错误');
                    statusSpan.style.color = '#d40000';
                }
            }
        })
        .catch(err => {
            if (statusSpan) {
                statusSpan.innerText = '网络错误: ' + err.message;
                statusSpan.style.color = '#d40000';
            }
        });
    }
    
    // 绑定事件
    if (startDateInput) startDateInput.addEventListener('change', updateCurrentSettings);
    if (endDateInput) endDateInput.addEventListener('change', updateCurrentSettings);
    if (confirmBtn) confirmBtn.addEventListener('click', confirmTimeRange);
    
    updateCurrentSettings();
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    var timeModule = document.getElementById('time_range_module');
    if (timeModule && window.timeRangeModuleConfig) {
        initTimeRangeModule(window.timeRangeModuleConfig.alias);
    }
});