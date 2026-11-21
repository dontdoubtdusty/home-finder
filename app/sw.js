// Service worker: makes the app installable and lets it open offline.
// Listing data is cached separately by Firestore's offline cache.
// Bump VERSION whenever app files change so phones pick up the update.
const VERSION = "hf-v1";
const SHELL = [
  "./", "index.html", "styles.css", "app.js", "firebase-config.js", "manifest.webmanifest",
  "icons/icon-192.png", "icons/icon-512.png",
];
const CDN_HOSTS = ["cdnjs.cloudflare.com", "www.gstatic.com"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  // Only app files and pinned library versions; never Firestore/Auth traffic or map tiles.
  if (!sameOrigin && !CDN_HOSTS.includes(url.hostname)) return;

  // Network first for our own files (so updates show up), falling back to cache offline.
  if (sameOrigin) {
    e.respondWith(
      fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
        return res;
      }).catch(() => caches.match(req).then((r) => r || caches.match("index.html")))
    );
    return;
  }
  // Versioned CDN files never change: cache first.
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      // Classic <script>/<link> loads are opaque (no CORS) but still cacheable.
      if (res.ok || res.type === "opaque") {
        const copy = res.clone();
        caches.open(VERSION).then((c) => c.put(req, copy));
      }
      return res;
    }))
  );
});
