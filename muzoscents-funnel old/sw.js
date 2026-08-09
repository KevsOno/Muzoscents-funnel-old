// ================================================
// KEVS MARKET – PRODUCTION SERVICE WORKER v3
// ================================================
// Supports: Offline page, Stale-While-Revalidate,
// Push Notifications, Background Sync, Periodic Sync
// ================================================

const CACHE_NAME = 'kevs-cache-v3';
const ORDER_CACHE_NAME = 'kevs-orders-v1';

// Cache your core app files during install (flat root structure)
const urlsToCache = [
  '/kdstore.html',   // Your main app
  '/offline.html'    // Your offline fallback
];

// --- IndexedDB helpers (needed for periodic sync) ---
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
        request.onerror = (e) => reject(e.target.error);
    });
}

async function getUserFromDB(db) {
    const tx = db.transaction('user', 'readonly');
    const store = tx.objectStore('user');
    const request = store.get('current');
    return new Promise((resolve, reject) => {
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

// --- 1. INSTALL ---
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches
            .open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Caching Kevs Market core files');
                return cache.addAll(urlsToCache);
            })
            .then(() => self.skipWaiting())
    );
});

// --- 2. ACTIVATE (Clean up old caches) ---
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME && name !== ORDER_CACHE_NAME)
                        .map((name) => caches.delete(name))
                );
            })
            .then(() => {
                console.log('[SW] Old caches cleared, Kevs Market SW activated!');
                return self.clients.claim();
            })
    );
});

// --- 3. FETCH (SMART ROUTING) ---
self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = new URL(request.url);

    // --- A. PAGE NAVIGATIONS (Network First, Fallback to Offline) ---
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then((response) => response)
                .catch(() => {
                    // If network fails, show your branded offline page
                    return caches.match('/offline.html');
                })
        );
        return;
    }

    // --- B. EXTERNAL CDNs (Tailwind & FontAwesome) - Stale-While-Revalidate ---
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
                    .catch(() => {
                        // Silently fail if network is down, we'll just use cache if available
                    });

                // Return cached version instantly, but update in background
                return cachedResponse || fetchPromise;
            })
        );
        return;
    }

    // --- C. API CALLS (NEVER CACHE – Always get fresh data) ---
    if (url.hostname === 'kevsono-kevs-digital-bos.hf.space') {
        event.respondWith(
            fetch(request).catch(() => {
                // Return a structured offline JSON error for APIs
                return new Response(
                    JSON.stringify({
                        error: 'You are offline. Please check your connection.',
                        offline: true,
                    }),
                    {
                        status: 503,
                        headers: { 'Content-Type': 'application/json' },
                    }
                );
            })
        );
        return;
    }

    // --- D. YOUR OWN ASSETS (Images, JS, CSS, Icons) - Cache First ---
    // Only cache GET requests and successful responses
    if (request.method !== 'GET') {
        event.respondWith(fetch(request));
        return;
    }

    event.respondWith(
        (async () => {
            const cachedResponse = await caches.match(request);
            if (cachedResponse) {
                // Update the cache in the background (stale-while-revalidate)
                fetch(request)
                    .then((networkResponse) => {
                        if (networkResponse && networkResponse.status === 200) {
                            caches.open(CACHE_NAME).then((cache) =>
                                cache.put(request, networkResponse)
                            );
                        }
                    })
                    .catch(() => {}); // Silently ignore background fetch errors
                return cachedResponse;
            }

            // If not in cache, fetch from network and cache it
            try {
                const networkResponse = await fetch(request);
                if (networkResponse && networkResponse.status === 200) {
                    const clone = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
                }
                return networkResponse;
            } catch (error) {
                // If the asset isn't in cache and network fails, just throw the error
                return new Response('Asset not found', { status: 404 });
            }
        })()
    );
});

// ================================================
// ADVANCED FEATURES (Push, Sync, Notifications)
// ================================================

// --- 1. BACKGROUND SYNC (Retry failed orders when back online) ---
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-orders') {
        event.waitUntil(
            fetch('https://kevsono-kevs-digital-bos.hf.space/api/retry-pending-orders')
                .then((response) => response.json())
                .then((data) => console.log('[SW] ✅ Order synced offline!', data))
                .catch((err) => console.warn('[SW] Sync failed:', err))
        );
    }
});

// --- 2. PUSH NOTIFICATIONS (Hardened against malformed JSON) ---
self.addEventListener('push', (event) => {
    let data = { body: 'Your delivery status has been updated.' };

    try {
        if (event.data) {
            // Attempt to parse as JSON
            data = event.data.json();
        }
    } catch (error) {
        // If it's plain text or malformed, use the raw text as the body
        try {
            data = { body: event.data.text() };
        } catch (_) {
            // Fallback if even text() fails
            data = { body: 'Delivery status updated.' };
        }
    }

    const options = {
        body: data.body || 'Your delivery status has been updated.',
        icon: '/icons/icon-192.png',
        badge: '/icons/icon-192.png',
        vibrate: [200, 100, 200],
        data: { url: data.url || '/kdstore.html?page=tracking' },
    };

    event.waitUntil(
        self.registration.showNotification('🚚 Kevs Market', options)
    );
});

// --- 3. PERIODIC SYNC (Fetch user's orders in the background) ---
self.addEventListener('periodicsync', (event) => {
    if (event.tag === 'update-orders') {
        event.waitUntil(
            (async () => {
                try {
                    // 1. Open IndexedDB and get user data
                    const db = await openUserDB();
                    const userData = await getUserFromDB(db);
                    if (!userData || !userData.token || !userData.email) {
                        console.log('[SW] No user data – skipping periodic sync');
                        return;
                    }

                    // 2. Fetch orders for this specific user
                    const response = await fetch(
                        `https://kevsono-kevs-digital-bos.hf.space/track-order?email=${encodeURIComponent(userData.email)}`,
                        {
                            headers: {
                                'Authorization': `Bearer ${userData.token}`
                            }
                        }
                    );
                    if (!response.ok) throw new Error('Fetch failed');
                    const orders = await response.json();

                    // 3. Store in order cache
                    const cache = await caches.open(ORDER_CACHE_NAME);
                    await cache.put(
                        '/kdstore/api/orders-cache',
                        new Response(JSON.stringify(orders), {
                            headers: { 'Content-Type': 'application/json' }
                        })
                    );
                    console.log('[SW] ✅ Periodic sync updated orders for', userData.email);
                } catch (err) {
                    console.warn('[SW] Periodic sync failed:', err);
                }
            })()
        );
    }
});

// --- 4. CLICK ON NOTIFICATION (Open app to tracking page) ---
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const urlToOpen = event.notification.data?.url || '/kdstore.html';

    event.waitUntil(
        clients
            .matchAll({ type: 'window', includeUncontrolled: true })
            .then((windowClients) => {
                // Check if there is already a window/tab open with the target URL
                for (let client of windowClients) {
                    if (client.url === urlToOpen && 'focus' in client) {
                        return client.focus();
                    }
                }
                // If not, open a new window
                if (clients.openWindow) {
                    return clients.openWindow(urlToOpen);
                }
            })
    );
});
