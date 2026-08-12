// 行业轮动页 Service Worker —— 离线缓存（cache-first，失效回源）
const CACHE = "sector-v1";
const ASSETS = ["/", "/sector", "/sector_dashboard.html", "/arb", "/index.html"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS).catch(() => {})));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // API 与实时接口始终走网络（保证数据新鲜）
  if (url.pathname.startsWith("/api/")) return;
  e.respondWith(
    caches.match(req).then((cached) => {
      const net = fetch(req)
        .then((r) => {
          if (r && r.status === 200 && (r.type === "basic" || r.type === "default")) {
            const cp = r.clone();
            caches.open(CACHE).then((c) => c.put(req, cp));
          }
          return r;
        })
        .catch(() => cached);
      return cached || net;
    })
  );
});
