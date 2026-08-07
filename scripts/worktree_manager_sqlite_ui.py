"""Small Manager-owned UI enhancements for the embedded SQLite browser.

The database browser is a third-party application.  Keep its package intact and
decorate only the HTML returned by the Manager-owned WSGI adapter so worker
ports and future sqlite-web upgrades do not inherit client-specific behavior.
"""

from __future__ import annotations


_MARKER = "data-factor-tester-sqlite-ui"

_STYLE = """
<style data-factor-tester-sqlite-ui>
  /* Keep the database navigation usable without changing sqlite-web's routes. */
  #sidebar { min-width: 0; }
  #sidebar.ft-sqlite-sidebar {
    position: relative;
    flex: 0 0 var(--ft-sqlite-sidebar-width, 260px) !important;
    max-width: var(--ft-sqlite-sidebar-width, 260px) !important;
    width: var(--ft-sqlite-sidebar-width, 260px) !important;
  }
  #content.ft-sqlite-content {
    flex: 1 1 auto !important;
    max-width: none !important;
    width: auto !important;
  }
  .ft-sqlite-sidebar-resizer {
    position: absolute;
    z-index: 5;
    top: 0;
    right: -4px;
    bottom: 0;
    width: 8px;
    cursor: col-resize;
    touch-action: none;
  }
  .ft-sqlite-sidebar-resizer:hover,
  .ft-sqlite-sidebar-resizer:focus-visible {
    background: rgba(0, 123, 255, .22);
    outline: none;
  }
  body.ft-sqlite-resizing { cursor: col-resize; user-select: none; }
  #ft-sqlite-table-list {
    max-height: min(52vh, 560px);
    overflow: auto;
    border: 1px solid rgba(0, 0, 0, .08);
    border-radius: .25rem;
    padding: .2rem;
  }
  #ft-sqlite-table-list > ul {
    min-width: max-content;
    margin-bottom: 0;
  }
  #ft-sqlite-table-list .table-link > a,
  #sidebar #helper-tables a {
    display: block;
    min-width: max-content;
    white-space: nowrap;
  }
  #ft-sqlite-table-list summary {
    cursor: pointer;
    font-weight: 600;
    padding: .25rem .35rem .4rem;
    user-select: none;
  }
  #ft-sqlite-table-list summary::marker { color: #6c757d; }
  #ft-sqlite-table-list .ft-sqlite-helper-toggle {
    display: block;
    margin: .4rem .2rem;
  }
</style>
"""

_SCRIPT = """
<script data-factor-tester-sqlite-ui>
(function() {
  function enhanceTableNavigation() {
    var sidebar = document.getElementById('sidebar');
    var list = sidebar && sidebar.querySelector('ul.nav.flex-column.nav-pills');
    if (!list || document.getElementById('ft-sqlite-table-list')) return;

    sidebar.classList.add('ft-sqlite-sidebar');
    var content = document.getElementById('content');
    if (content) content.classList.add('ft-sqlite-content');
    var row = sidebar.parentElement;
    var initialWidth = parseInt(localStorage.getItem('ft-sqlite-sidebar-width') || '260', 10);
    var setWidth = function(width) {
      var maximum = row ? Math.max(320, row.clientWidth - 320) : 560;
      width = Math.max(200, Math.min(560, maximum, Math.round(width)));
      sidebar.style.setProperty('--ft-sqlite-sidebar-width', width + 'px');
      localStorage.setItem('ft-sqlite-sidebar-width', String(width));
    };
    setWidth(initialWidth);
    var resizer = document.createElement('div');
    resizer.className = 'ft-sqlite-sidebar-resizer';
    resizer.setAttribute('role', 'separator');
    resizer.setAttribute('aria-label', '调整数据表栏宽度');
    resizer.setAttribute('aria-orientation', 'vertical');
    resizer.tabIndex = 0;
    sidebar.appendChild(resizer);
    var resizing = false;
    resizer.addEventListener('pointerdown', function(event) {
      resizing = true;
      resizer.setPointerCapture(event.pointerId);
      document.body.classList.add('ft-sqlite-resizing');
      event.preventDefault();
    });
    resizer.addEventListener('pointermove', function(event) {
      if (resizing) setWidth(event.clientX - sidebar.getBoundingClientRect().left);
    });
    resizer.addEventListener('pointerup', function(event) {
      resizing = false;
      resizer.releasePointerCapture(event.pointerId);
      document.body.classList.remove('ft-sqlite-resizing');
    });
    resizer.addEventListener('keydown', function(event) {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        var current = parseInt(getComputedStyle(sidebar).width, 10);
        setWidth(current + (event.key === 'ArrowRight' ? 16 : -16));
        event.preventDefault();
      }
    });

    var details = document.createElement('details');
    details.id = 'ft-sqlite-table-list';
    details.open = localStorage.getItem('ft-sqlite-table-list-open') !== 'false';
    var summary = document.createElement('summary');
    summary.textContent = '数据表';
    details.appendChild(summary);
    list.parentNode.insertBefore(details, list);
    details.appendChild(list);
    details.addEventListener('toggle', function() {
      localStorage.setItem('ft-sqlite-table-list-open', details.open ? 'true' : 'false');
    });

    var helperToggle = document.getElementById('toggle-helper-tables');
    if (helperToggle) helperToggle.classList.add('ft-sqlite-helper-toggle');

    /* sqlite-web truncates labels for the narrow sidebar.  Its title attribute
       is the authoritative name; restore it and let the wrapper scroll. */
    sidebar.querySelectorAll('a[title]').forEach(function(link) {
      var fullName = link.getAttribute('title');
      if (!fullName) return;
      var marker = link.querySelector('sup');
      link.textContent = fullName;
      if (marker) link.appendChild(marker);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhanceTableNavigation);
  } else {
    enhanceTableNavigation();
  }
})();
</script>
"""


def decorate_sqlite_html(body: bytes, content_type: str) -> bytes:
    """Add Manager-only table navigation to an HTML sqlite-web response."""
    if not body or "text/html" not in content_type.lower():
        return body
    text = body.decode("utf-8", errors="replace")
    if _MARKER in text:
        return body
    if "</head>" in text:
        text = text.replace("</head>", _STYLE + "</head>", 1)
    if "</body>" in text:
        text = text.replace("</body>", _SCRIPT + "</body>", 1)
    return text.encode("utf-8")
