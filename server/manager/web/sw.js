const CACHE = "tr-shell-v3";
let cacheUpdates = Promise.resolve();
function remember(request, response) {
  cacheUpdates = cacheUpdates.catch(() => undefined).then(async () => {
    const cache = await caches.open(CACHE);
    await cache.put(request, response);
    const path = new URL(request.url).pathname;
    const prior = (await cache.keys()).filter(key => key.url !== request.url && new URL(key.url).pathname === path);
    // Retain current plus one prior version, serialized to avoid concurrent deletion.
    await Promise.all(prior.slice(0, -1).map(key => cache.delete(key)));
  });
  return cacheUpdates;
}
const SHELL = [
  "/app",
  "/research-static/vendor/web-app/loader.js",
  "/research-static/vendor/web-app/desktop.js",
  "/research-static/vendor/web-app/desktop.css",
  "/research-static/vendor/web-app/mobile.js",
  "/research-static/vendor/web-app/mobile.css",
  "/research-static/vendor/web-app/manifest.webmanifest",
  "/research-static/styles/app.css"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL.map(url => new Request(url, { cache: "reload" })))).catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key.startsWith("tr-shell-") && key !== CACHE).map((key) => caches.delete(key)),
  )));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;
  if (url.pathname === "/app" || url.pathname === "/app/" || url.pathname.startsWith("/research-static/vendor/web-app/") ||
      url.pathname === "/research-static/styles/app.css") {
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) event.waitUntil(remember(request, response.clone()));
      return response;
    }).catch(() => caches.match(request)));
  }
});
