// ================================================
// HOT PORTION GRILL – SERVICE WORKER v1
// Scoped to /fastfood/
// ================================================

const CACHE_NAME = 'hotportion-cache-v1';
const OFFLINE_URL = '/fastfood/offline.html';

// Core files to cache during install
const urlsToCache = [
  '/fastfood/sandbox.html',
  '/fastfood/offline.html'
];

// --- INSTALL ---
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Caching Hot Portion core files');
        return cache.addAll(urlsToCache);
      })
      .then(() => self.skipWaiting())
  );
});

// --- ACTIVATE (clean up old caches) ---
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name))
        );
      })
      .then(() => {
        console.log('[SW] Hot Portion SW activated!');
        return self.clients.claim();
      })
  );
});

// --- FETCH (smart routing) ---
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // --- A. Page navigations (network first, fallback to offline) ---
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => response)
        .catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  // --- B. External CDNs (Tailwind, FontAwesome) – Stale-While-Revalidate ---
  if (
    url.hostname === 'cdn.tailwindcss.com' ||
    url.hostname === 'cdnjs.cloudflare.com'
  ) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        const fetchPromise = fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(CACHE_NAME).then((cache) =>
                cache.put(request, networkResponse.clone())
              );
            }
            return networkResponse;
          })
          .catch(() => {});
        return cachedResponse || fetchPromise;
      })
    );
    return;
  }

  // --- C. Your own assets (Cache First, then network) ---
  if (request.method !== 'GET') {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith(
    (async () => {
      const cachedResponse = await caches.match(request);
      if (cachedResponse) {
        // Update cache in background (stale-while-revalidate)
        fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(CACHE_NAME).then((cache) =>
                cache.put(request, networkResponse)
              );
            }
          })
          .catch(() => {});
        return cachedResponse;
      }

      try {
        const networkResponse = await fetch(request);
        if (networkResponse && networkResponse.status === 200) {
          const clone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return networkResponse;
      } catch (error) {
        return new Response('Asset not found', { status: 404 });
      }
    })()
  );
});
