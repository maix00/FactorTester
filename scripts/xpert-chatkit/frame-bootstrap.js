// Loaded before the upstream module. All SDK requests stay on this page's
// scoped Manager adapter; no cloud credentials are sent into the iframe.
(() => {
  const key = new URL(location.href).searchParams.get('ft_channel');
  if (!key || parent === window || parent.location.origin !== location.origin) {
    throw new Error('Xpert UI requires its same-origin FactorTester host');
  }
  window.fetch = async (input, init = {}) => {
    const request = new Request(input, init);
    const url = new URL(request.url);
    if (url.origin !== location.origin || !url.pathname.startsWith('/ft-profile-bridge/')) {
      throw new Error('Xpert UI external API access is disabled');
    }
    const response = await parent.FTXpertTransport.fetch(key, request.url, {
      method: request.method, body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.text(),
      signal: request.signal,
    });
    return new Response(response.body, {status: response.status, headers: [...response.headers]});
  };
})();
