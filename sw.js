// 行业轮动页 Service Worker —— 离线缓存
// 策略：页面与日更快照(sector_data.json) 用 network-first，保证更新即时可见；
//       其余静态资源用 cache-first；/api/* 实时接口始终走网络。
const CACHE = "sector-v2";
const ASSETS = ["/", "/sector", "/sector_dashboard.html", "/arb", "/index.html"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS).catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

// 需要「每次都拿最新」的资源：页面本身 + 日更快照 JSON
function isFreshFirst(url) {
  const p = url.pathname;
  return p === "/" || p === "/sector" || p === "/sector_dashboard.html" ||
         p === "/arb" || p === "/index.html" || p === "/sector_data.json";
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // 实时接口始终走网络
  if (url.pathname.startsWith("/api/")) return;

  if (isFreshFirst(url)) {
    // network-first：先试网络拿最新，失败再回退缓存（离线可用）
    e.respondWith(
      fetch(req).then((r) => {
        if (r && r.status === 200 && (r.type === "basic" || r.type === "default")) {
          const cp = r.clone();
          caches.open(CACHE).then((c) => c.put(req, cp));
        }
        return r;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // 其余静态资源：cache-first
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
