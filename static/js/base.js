// static/js/base.js

function searchFactors() {
    var query = document.getElementById('search').value;
    if (query.trim()) {
        window.location.href = '?search=' + encodeURIComponent(query);
    } else {
        window.location.href = '?';
    }
}

function shutdownServer() {
    if (confirm('确定要关闭服务器吗？')) {
        fetch('/shutdown', {method: 'POST'}).then(function() {
            window.close();
        }).catch(function() {
            window.location.href = '/shutdown';
        });
    }
}

function pad(n) {
    n = parseInt(n);
    return n < 10 ? '0' + n : n.toString();
}

function formatNumber(value, decimals) {
    if (value === null || value === undefined || value === '') return '—';
    if (typeof value === 'number') {
        return decimals !== undefined ? value.toFixed(decimals) : (Number.isInteger(value) ? value : value.toFixed(6));
    }
    return String(value);
}

document.addEventListener('DOMContentLoaded', function() {
    var searchInput = document.getElementById('search');
    if (searchInput) {
        searchInput.addEventListener('keyup', function(e) {
            if (e.key === 'Enter') searchFactors();
        });
    }
});