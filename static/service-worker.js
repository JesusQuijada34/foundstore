const SHELL_CACHE = "foundstore-shell-v3";
const DATA_CACHE = "foundstore-data-v3";
const STATIC_SHELL = ["/manifest.webmanifest", "/favicon.ico"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(SHELL_CACHE).then(cache => cache.addAll(STATIC_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => key.startsWith("foundstore-") && key !== SHELL_CACHE && key !== DATA_CACHE)
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || request.cache === "no-store") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never answer document navigations from a cache. The home and public profiles
  // are session- and URL-dependent, so a cached HTML document can show the wrong
  // account or an obsolete interface on mobile.
  if (request.mode === "navigate" || request.destination === "document") return;

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

  if (url.pathname === "/manifest.webmanifest" || url.pathname === "/favicon.ico") {
    event.respondWith(caches.open(SHELL_CACHE).then(async cache => {
      const cached = await cache.match(request);
      const network = fetch(request).then(response => {
        if (response.ok) cache.put(request, response.clone());
        return response;
      }).catch(() => cached);
      return cached || network;
    }));
  }
});
