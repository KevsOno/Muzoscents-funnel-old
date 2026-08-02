// sw.js – Flat Root Structure (NO /kdstore/ folder)
const CACHE_NAME = 'kevs-cache-v1';

// ✅ FIXED: Only cache YOUR local files during install. 
// NO external CDNs here (they go in the fetch handler below).
const urlsToCache = [
  '/kdstore.html',   // Your main app
  '/offline.html'    // Your offline fallback
];

// --- INSTALL ---
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Caching Kevs Market core files');
        return cache.addAll(urlsToCache);
      })
      .then(() => self.skipWaiting())
  );
});

// --- ACTIVATE ---
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      );
    }).then(() => {
      console.log('Old caches cleared, Kevs Market SW activated!');
      return self.clients.claim();
    })
  );
});

// --- FETCH (SMART ROUTING) ---
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  // 1. HANDLE PAGE NAVIGATIONS (e.g., refreshing /kdstore/product/123)
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(response => response)
        .catch(() => {
          // If network fails, show your branded offline page
          return caches.match('/offline.html');
        })
    );
    return;
  }

  // 2. HANDLE EXTERNAL CDNs (Tailwind & FontAwesome) - CACHE FIRST, UPDATE LATER
  if (url.hostname === 'cdn.tailwindcss.com' || url.hostname === 'cdnjs.cloudflare.com') {
    event.respondWith(
      caches.match(request).then(cachedResponse => {
        // Return cached version instantly if available
        if (cachedResponse) {
          // Update the cache in the background (stale-while-revalidate)
          fetch(request).then(networkResponse => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(CACHE_NAME).then(cache => cache.put(request, networkResponse));
            }
          });
          return cachedResponse;
        }
        // If not in cache, fetch from network
        return fetch(request).then(networkResponse => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then(cache => cache.put(request, networkResponse.clone()));
          }
          return networkResponse;
        });
      })
    );
    return;
  }

  // 3. HANDLE YOUR OWN ASSETS (images, icons, JS) - Cache falling back to network
  event.respondWith(
    caches.match(request).then(cachedResponse => {
      return cachedResponse || fetch(request).then(networkResponse => {
        // Cache new assets dynamically as the user browses
        if (networkResponse && networkResponse.status === 200 && request.method === 'GET') {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, responseClone));
        }
        return networkResponse;
      });
    })
  );
});
