const CACHE = "tr-shell-v1";
const SHELL = [
  "/app",
  "/static/vendor/web-app/loader.js",
  "/static/vendor/web-app/desktop.js",
  "/static/vendor/web-app/desktop.css",
  "/static/vendor/web-app/mobile.js",
  "/static/vendor/web-app/mobile.css",
  "/static/vendor/web-app/manifest.webmanifest",
  "/static/styles/app.css"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)),
  )));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;
  if (url.pathname === "/app" || url.pathname.startsWith("/static/vendor/web-app/") ||
      url.pathname === "/static/styles/app.css") {
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) caches.open(CACHE).then((cache) => cache.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request)));
  }
});
