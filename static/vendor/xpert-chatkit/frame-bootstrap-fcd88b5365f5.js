// Loaded before the upstream module. All SDK requests stay on this page's
// scoped Manager adapter; no cloud credentials are sent into the iframe.
(() => {
  const key = new URL(location.href).searchParams.get('ft_channel');
  if (!key || parent === window || parent.location.origin !== location.origin) {
    throw new Error('Xpert UI requires its same-origin FactorTester host');
  }
  // React owns these slots; the Manager owns the controls and their lifecycle.
  window.addEventListener("ft-drawer-close", () => parent.FTXpertTransport.close(key));
  const mounted = new WeakSet();
  const mount = () => document.querySelectorAll('[data-ft-host-control]').forEach(slot => {
    if (mounted.has(slot)) return;
    mounted.add(slot);
    parent.FTXpertTransport.mountControls(key, slot.dataset.ftHostControl, slot);
  });
  new MutationObserver(mount).observe(document.documentElement, {childList: true, subtree: true});
  mount();
  window.fetch = async (input, init = {}) => {
    const request = new Request(input, init);
    const url = new URL(request.url);
    if (url.origin !== location.origin || !url.pathname.startsWith('/ft-profile-bridge/')) {
      throw new Error('Xpert UI external API access is disabled');
    }
    const response = await parent.FTXpertTransport.fetch(key, request.url, {
      method: request.method, body: ['GET', 'HEAD'].includes(request.method) ? undefined :
        // Keep the original File objects. WebKit's multipart round trip can
        // parse a non-ASCII filename part as text and discard its file identity.
        init.body instanceof FormData ? init.body :
        request.headers.get('content-type')?.includes('multipart/form-data') ? await request.formData() : await request.text(),
      signal: request.signal,
    });
    return new Response(response.body, {status: response.status, headers: [...response.headers]});
  };
})();
// WebKit can chain wheel input out of an iframe even with overscroll containment.
window.addEventListener('wheel', event => {
  const axis = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? 'y' : 'x';
  const delta = axis === 'y' ? event.deltaY : event.deltaX;
  if (!delta || event.ctrlKey) return;
  for (const node of event.composedPath()) {
    if (!(node instanceof HTMLElement)) continue;
    const style = getComputedStyle(node);
    const overflow = axis === 'y' ? style.overflowY : style.overflowX;
    if (!/(auto|scroll)/.test(overflow)) continue;
    const position = axis === 'y' ? node.scrollTop : node.scrollLeft;
    const extent = axis === 'y' ? node.scrollHeight - node.clientHeight : node.scrollWidth - node.clientWidth;
    if (extent > 0 && (delta < 0 ? position > 0 : position < extent - 1)) return;
  }
  event.preventDefault();
}, {passive: false});
