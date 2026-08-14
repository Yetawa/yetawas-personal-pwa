// 行业轮动页 Service Worker —— 纯网络策略
// 不缓存任何资源，所有请求直连网络，保证页面/数据永远是最新的。
// 旧 v1(v2) 用 cache-first/network-first 仍会喂旧缓存，导致「刷新看不到更新」，
// 故彻底改为纯网络：不注册 fetch 拦截器，浏览器默认网络行为；skipWaiting 立即激活接管。
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
// 不监听 fetch —— 浏览器按默认纯网络处理，绝不会返回任何旧缓存
