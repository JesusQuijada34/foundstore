const SHELL_CACHE = "foundstore-shell-v2";
const DATA_CACHE = "foundstore-data-v2";
const SHELL = ["/", "/manifest.webmanifest", "/favicon.ico"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(SHELL_CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("foundstore-") && key !== SHELL_CACHE && key !== DATA_CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.cache === "no-store") return;
  if (url.pathname === "/api/v1/catalog") {
    event.respondWith(caches.open(DATA_CACHE).then(async cache => {
      const cached = await cache.match(request);
      const network = fetch(request).then(response => {
        if (response.ok) cache.put(request, response.clone());
        return response;
      }).catch(() => cached);
      return cached || network;
    }));
    return;
  }
  if (url.pathname === "/" || url.pathname === "/manifest.webmanifest" || url.pathname === "/favicon.ico") {
    event.respondWith(caches.open(SHELL_CACHE).then(async cache => {
      const cached = await cache.match(request);
      const network = fetch(request).then(response => {
        if (response.ok) cache.put(request, response.clone());
        return response;
      });
      return cached || network;
    }));
  }
});
