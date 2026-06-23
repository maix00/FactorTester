// static/js/factor_main.js - 只保留时间范围模块

document.addEventListener('DOMContentLoaded', function() {
    // ========== 时间范围模块 ==========
    const startDate = document.getElementById('start_date');
    const endDate = document.getElementById('end_date');
    const confirmBtn = document.getElementById('confirm_time_btn');
    const statusSpan = document.getElementById('confirm_time_status');
    
    if (confirmBtn && startDate && endDate) {
        function updateStatus() {
            if (startDate.value <= endDate.value) {
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
            const data = {
                factor_family_alias: document.querySelector('.section').getAttribute('data-factor-alias'),
                page_uuid: window._pageUuid || '',
                start_date: startDate.value,
                start_time: document.getElementById('start_time')?.value || '00:00',
                end_date: endDate.value,
                end_time: document.getElementById('end_time')?.value || '00:00',
                is_trading_day: document.getElementById('is_trading_day')?.checked || false,
                timezone: document.getElementById('timezone_select')?.value || 'Asia/Shanghai'
            };
            
            if (statusSpan) {
                statusSpan.innerText = '更新中...';
                statusSpan.style.color = '#0078d4';
            }

            window._confirmedTimeData = data;
            document.dispatchEvent(new CustomEvent('pageTimeRangeChanged', { detail: data }));
            if (statusSpan) {
                statusSpan.innerText = '✓ 页面时间范围已更新';
                statusSpan.style.color = '#28a745';
                setTimeout(() => {
                    if (statusSpan.innerText === '✓ 页面时间范围已更新') {
                        statusSpan.innerText = '';
                    }
                }, 3000);
                }
        }
        
        startDate.addEventListener('change', updateStatus);
        endDate.addEventListener('change', updateStatus);
        confirmBtn.addEventListener('click', confirmTimeRange);
        updateStatus();
    }
});
