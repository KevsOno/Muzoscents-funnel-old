// =====================================================================
//  Kevs — Unified Service Worker (Market + POS)
// =====================================================================
//  Scope: BOTH storefront (kdstore) and POS (kdpos / kdsiginin)
//
//  Responsibilities:
//    • Precache app shells + branded offline page
//    • Network-first navigations with per-path fallback
//    • Stale-while-revalidate for CDN (Tailwind, FontAwesome, Dexie)
//    • Never cache API responses — return structured offline JSON
//    • Cache-first for same-origin static assets
//    • Background Sync:  retry pending orders
//    • Periodic Sync:    refresh customer orders (Kevs Market)
//    • Periodic Sync:    ask POS tab to refresh its offline catalog
//    • Push notifications + notification click
// =====================================================================

const CACHE_VERSION   = 'v5';
const CACHE_NAME      = `kevs-cache-${CACHE_VERSION}`;
const ORDER_CACHE_NAME = 'kevs-orders-v1';

// Shell pages precached at install time.
// Each fallback route is pre-warmed so offline navigations hit a real page.
const urlsToCache = [
  '/kdstore.html',
  '/kdpos',
  '/kdsiginin',
  '/offline.html'
];

// Third-party assets we want available offline.
// Tailwind → JS runtime, FontAwesome → CSS, jsDelivr → Dexie for the POS.
const CDN_HOSTS = [
  'cdn.tailwindcss.com',
  'cdnjs.cloudflare.com',
  'cdn.jsdelivr.net'
];

// Any path starting with these prefixes is considered an API call and is
// never served from cache. Must list POS + Market endpoints.
const API_PATH_PREFIXES = [
  '/inventory',
  '/pos',
  '/auth',
  '/loyalty',
  '/organisations',
  '/support',
  '/accounts',
  '/api/',
  '/webhook',
  '/fulfillment',
  '/delivery',
  '/track-order',
  '/sales',
  '/leads',
  '/analytics',
  '/intelligence',
  '/alerts',
  '/risk-scores',
  '/stock-limits',
  '/stock-transfers',
  '/products',
  '/suppliers',
  '/purchase-orders',
  '/grn',
  '/system-logs',
  '/dashboard',
  '/transfer-suggestions',
  '/hr',
  '/debug',
  '/admin'
];

const BACKEND_HOST = 'kevsono-kevs-digital-bos.hf.space';


// =====================================================================
//  IndexedDB helper (used by periodic sync for the customer order cache)
// =====================================================================
function openUserDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('KevsUserDB', 1);
    request.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('user')) {
        db.createObjectStore('user', { keyPath: 'id' });
      }
    };
    request.onsuccess = (e) => resolve(e.target.result);
    request.onerror   = (e) => reject(e.target.error);
  });
}

async function getUserFromDB(db) {
  const tx = db.transaction('user', 'readonly');
  const store = tx.objectStore('user');
  const request = store.get('current');
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror   = () => reject(request.error);
  });
}


// =====================================================================
//  INSTALL — precache app shells
// =====================================================================
self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // Use individual adds so one 404 doesn't kill the whole install.
    await Promise.all(
      urlsToCache.map(url =>
        cache.add(url).catch(err =>
          console.warn('[SW] precache miss:', url, err && err.message)
        )
      )
    );
    await self.skipWaiting();
  })());
});


// =====================================================================
//  ACTIVATE — clean up any cache that is not the current one
// =====================================================================
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter(name => name !== CACHE_NAME && name !== ORDER_CACHE_NAME)
        .map(name => caches.delete(name))
    );
    console.log('[SW] activated:', CACHE_NAME);
    await self.clients.claim();
  })());
});


// =====================================================================
//  FETCH — smart routing
// =====================================================================
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Never intercept non-GET (POST/PUT/DELETE/PATCH)
  if (request.method !== 'GET') return;

  // --- A. NAVIGATIONS — network-first with per-path fallback ---------
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request, url));
    return;
  }

  // --- B. CDN ASSETS — stale-while-revalidate ------------------------
  if (CDN_HOSTS.includes(url.hostname)) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  // --- C. API CALLS — network-only, JSON error when offline ----------
  if (url.hostname === BACKEND_HOST &&
      API_PATH_PREFIXES.some(p => url.pathname.startsWith(p))) {
    event.respondWith(
      fetch(request).catch(() => new Response(
        JSON.stringify({
          error: 'You are offline. Please check your connection.',
          offline: true
        }),
        {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        }
      ))
    );
    return;
  }

  // --- D. SAME-ORIGIN STATIC ASSETS — cache-first + bg revalidate -----
  if (url.origin === self.location.origin) {
    event.respondWith(cacheFirstWithRevalidate(request));
    return;
  }

  // Anything else: let the browser handle it.
});


// ---------------------------------------------------------------------
// Navigation: network-first, but fall back to the *right* shell for the
// requested path, then finally to the branded offline page.
// ---------------------------------------------------------------------
async function networkFirstNavigation(request, url) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    // 1) Exact match for this URL
    const exact = await cache.match(request);
    if (exact) return exact;

    // 2) Path-specific fallbacks
    if (url.pathname.startsWith('/kdpos')) {
      const pos = await cache.match('/kdpos');
      if (pos) return pos;
    }
    if (url.pathname.startsWith('/kdsiginin')) {
      const sigin = await cache.match('/kdsiginin');
      if (sigin) return sigin;
    }
    if (url.pathname.startsWith('/kdstore')) {
      const store = await cache.match('/kdstore.html');
      if (store) return store;
    }

    // 3) Last resort — branded offline page
    const offline = await cache.match('/offline.html');
    if (offline) return offline;

    // If even offline.html is missing, rethrow so the browser shows its
    // own network error. Should not happen because we precache it.
    throw err;
  }
}


// ---------------------------------------------------------------------
// CDN: return cache instantly; update in the background when online.
// ---------------------------------------------------------------------
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request)
    .then((response) => {
      // Opaque responses from no-cors fetches have status 0
      if (response && (response.status === 200 || response.type === 'opaque')) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  if (cached) return cached;
  const network = await fetchPromise;
  if (network) return network;

  // Both cache and network failed — return a harmless empty response so
  // the page doesn't crash on missing CSS/JS.
  if (request.destination === 'style') {
    return new Response('', { headers: { 'Content-Type': 'text/css' } });
  }
  if (request.destination === 'script') {
    return new Response('', { headers: { 'Content-Type': 'application/javascript' } });
  }
  return new Response('', { status: 504 });
}


// ---------------------------------------------------------------------
// Same-origin static assets: cache-first, refresh in the background.
// ---------------------------------------------------------------------
async function cacheFirstWithRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  if (cached) {
    // Fire-and-forget background refresh
    fetch(request)
      .then((response) => {
        if (response && response.status === 200) {
          cache.put(request, response.clone());
        }
      })
      .catch(() => {});
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response && response.status === 200) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('Asset not found', { status: 404 });
  }
}


// =====================================================================
//  MESSAGES — page ↔ SW coordination
// =====================================================================
self.addEventListener('message', (event) => {
  if (!event.data) return;

  // Let a waiting SW take over immediately
  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
    return;
  }

  // POS told us it finished downloading the catalog. Broadcast to all
  // open tabs so they can update their badge/counter.
  if (event.data.type === 'CATALOG_SYNCED') {
    self.clients.matchAll().then(clients => {
      clients.forEach(c => c.postMessage({
        type: 'CATALOG_SYNCED',
        count: event.data.count
      }));
    });
  }
});


// =====================================================================
//  BACKGROUND SYNC — retry queued orders when connectivity returns
// =====================================================================
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-orders') {
    event.waitUntil(
      fetch(`${location.origin}/api/retry-pending-orders`, { method: 'POST' })
        .then((response) => response.json())
        .then((data) => console.log('[SW] ✅ orders retried:', data))
        .catch((err) => console.warn('[SW] order retry failed:', err))
    );
  }
});


// =====================================================================
//  PUSH NOTIFICATIONS — hardened against malformed payloads
// =====================================================================
self.addEventListener('push', (event) => {
  let data = { body: 'Your delivery status has been updated.' };

  try {
    if (event.data) {
      data = event.data.json();
    }
  } catch (error) {
    try {
      data = { body: event.data.text() };
    } catch (_) {
      data = { body: 'Delivery status updated.' };
    }
  }

  const options = {
    body: data.body || 'Your delivery status has been updated.',
    icon:  '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    vibrate: [200, 100, 200],
    data: { url: data.url || '/kdstore.html?page=tracking' }
  };

  event.waitUntil(
    self.registration.showNotification('🚚 Kevs Market', options)
  );
});


// =====================================================================
//  PERIODIC SYNC
//  • update-orders    → refresh customer order cache for Kevs Market
//  • catalog-refresh  → ask every open POS tab to refresh its catalog
// =====================================================================
self.addEventListener('periodicsync', (event) => {
  if (event.tag === 'update-orders') {
    event.waitUntil(refreshCustomerOrders());
  }
  if (event.tag === 'catalog-refresh') {
    event.waitUntil(askClientsToRefreshCatalog());
  }
});

async function refreshCustomerOrders() {
  try {
    const db = await openUserDB();
    const userData = await getUserFromDB(db);
    if (!userData || !userData.token || !userData.email) {
      console.log('[SW] no user data – skipping order sync');
      return;
    }

    const response = await fetch(
      `${location.origin}/track-order?email=${encodeURIComponent(userData.email)}`,
      { headers: { 'Authorization': `Bearer ${userData.token}` } }
    );
    if (!response.ok) throw new Error('Fetch failed');
    const orders = await response.json();

    const cache = await caches.open(ORDER_CACHE_NAME);
    await cache.put(
      '/kdstore/api/orders-cache',
      new Response(JSON.stringify(orders), {
        headers: { 'Content-Type': 'application/json' }
      })
    );
    console.log('[SW] ✅ order cache updated for', userData.email);
  } catch (err) {
    console.warn('[SW] periodic order sync failed:', err);
  }
}

async function askClientsToRefreshCatalog() {
  const clients = await self.clients.matchAll({
    type: 'window',
    includeUncontrolled: true
  });
  clients.forEach(client => {
    client.postMessage({ type: 'REFRESH_CATALOG' });
  });
  console.log('[SW] asked', clients.length, 'client(s) to refresh catalog');
}


// =====================================================================
//  NOTIFICATION CLICK — open/focus the target URL
// =====================================================================
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const urlToOpen = (event.notification.data && event.notification.data.url) || '/kdstore.html';

  event.waitUntil(
    clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((windowClients) => {
        for (const client of windowClients) {
          if (client.url === urlToOpen && 'focus' in client) {
            return client.focus();
          }
        }
        if (clients.openWindow) {
          return clients.openWindow(urlToOpen);
        }
      })
  );
});
