// Brain Service Worker —— 离线缓存与 PWA 支持
// 版本号：每次前端发版需更新（构建时由 CI 注入 git short hash 更佳）
const CACHE_VERSION = 'v2-20260721';
const CACHE_NAME = `brain-${CACHE_VERSION}`;
const STATIC_ASSETS = [
  '/',
  '/graph',
  '/manifest.webmanifest',
  '/favicon.svg',
  '/icon-192.png',
  '/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // 只缓存同源请求
  if (url.origin !== self.location.origin) return;
  // API 请求不缓存（实时数据）
  if (url.pathname.startsWith('/api/')) return;

  // 网络优先，失败回退缓存
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200 && response.type === 'basic') {
          const respClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, respClone));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match('/')))
  );
});
