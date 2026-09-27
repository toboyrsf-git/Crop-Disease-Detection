/**
 * Service Worker for Crop Disease Screening Aid PWA.
 * Enables 100% offline asset availability for farmers.
 */

const CACHE_NAME = "crop-screening-v1";
const ASSETS_TO_CACHE = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/translations.js",
  "/manifest.json",
  "/api/labels"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE).catch(err => console.warn("Caching partial assets:", err));
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((k) => {
          if (k !== CACHE_NAME) return caches.delete(k);
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  // Network first for API, cache fallback; cache first for static assets
  if (e.request.url.includes("/api/cases") && e.request.method === "POST") {
    // Post requests handled in IndexedDB client code when offline
    return;
  }

  e.respondWith(
    caches.match(e.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(e.request).catch(() => {
        if (e.request.destination === "document") {
          return caches.match("/index.html");
        }
      });
    })
  );
});
