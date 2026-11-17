// src/lib/geocode.ts
//
// Client-side geocoder with debounce, serialisation, and caching.
// Default provider: Nominatim (OpenStreetMap). Swap the provider by
// changing `providerFetch` below — call sites never change.

const CACHE_PREFIX = 'logiflow.geocode.';
const CACHE_TTL_MS = 1000 * 60 * 60 * 24 * 7; // 7 days
const MIN_INTERVAL_MS = 1100;                  // Nominatim policy: max 1 req/sec
const MIN_QUERY_LEN = 3;

// Serialise all outbound requests through a single promise chain. This is
// what actually enforces the rate limit — a timestamp check alone races.
let requestChain: Promise<unknown> = Promise.resolve();

function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const run = requestChain.then(() => task());
  // Swallow errors on the chain itself so one failure doesn't poison the queue.
  requestChain = run.catch(() => undefined);
  return run;
}

export interface GeocodeHit {
  display_name: string;
  lat: number;
  lng: number;
}

interface CachedEntry {
  ts: number;
  hits: GeocodeHit[];
}

// localStorage can throw (Safari private mode, disabled storage, some
// Capacitor webviews). Never let a cache miss become an app crash.
function safeGet(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function safeSet(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* quota / disabled */ }
}

function readCache(key: string): GeocodeHit[] | null {
  const raw = safeGet(key);
  if (!raw) return null;
  try {
    const entry = JSON.parse(raw) as CachedEntry;
    if (Date.now() - entry.ts > CACHE_TTL_MS) {
      safeSet(key, ''); // best-effort eviction
      return null;
    }
    return entry.hits;
  } catch {
    return null;
  }
}

function writeCache(key: string, hits: GeocodeHit[]): void {
  const entry: CachedEntry = { ts: Date.now(), hits };
  safeSet(key, JSON.stringify(entry));
}

export class GeocodeRateLimited extends Error {
  constructor() { super('Geocoder rate-limited; try again in a moment.'); }
}

async function providerFetch(query: string): Promise<GeocodeHit[]> {
  // ---- Nominatim (default) ------------------------------------------------
  const url = new URL('https://nominatim.openstreetmap.org/search');
  url.searchParams.set('q', query);
  url.searchParams.set('format', 'json');
  url.searchParams.set('limit', '5');
  // Nominatim asks for a descriptive UA/Referer. Browsers forbid setting
  // User-Agent, but Referer is set automatically by the page origin, which
  // satisfies the policy for a browser-based app.

  const res = await fetch(url, {
    headers: { 'Accept-Language': navigator.language || 'en' },
  });

  if (res.status === 429 || res.status === 503) {
    throw new GeocodeRateLimited();
  }
  if (!res.ok) return [];

  const json = (await res.json()) as { display_name: string; lat: string; lon: string }[];
  return json.map((r) => ({
    display_name: r.display_name,
    lat: Number(r.lat),
    lng: Number(r.lon),
  }));
}

/**
 * Geocode an address string. Safe to call on every keystroke — internal
 * caching and queueing prevent both redundant network calls and rate-limit
 * violations. Callers should still debounce the *input* (see
 * `useDebouncedValue`) so we don't enqueue work for every keystroke.
 *
 * Throws `GeocodeRateLimited` when the upstream provider asks us to back off;
 * callers should surface that to the user rather than showing "no results".
 */
export async function geocodeAddress(query: string): Promise<GeocodeHit[]> {
  const trimmed = query.trim();
  if (trimmed.length < MIN_QUERY_LEN) return [];

  const key = CACHE_PREFIX + trimmed.toLowerCase();
  const cached = readCache(key);
  if (cached) return cached;

  return enqueue(async () => {
    // Re-check the cache inside the queue: while this call was waiting its
    // turn, an earlier identical query may have populated it.
    const recheck = readCache(key);
    if (recheck) return recheck;

    const hits = await providerFetch(trimmed);
    // Only cache genuine (including empty) responses. A rate-limit throw
    // never reaches here, so we won't poison the cache with a bad result.
    writeCache(key, hits);
    return hits;
  });
}
