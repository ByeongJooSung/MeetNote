// MeetNote service worker: 오프라인에서도 앱이 열리도록 정적 파일만 캐시합니다.
// API(/jobs, /health, /diarize 등)는 절대 캐시하지 않고 항상 서버로 보냅니다.
const CACHE = 'meetnote-v3';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png'];
const STATIC = /\.(html|js|css|png|svg|ico|webmanifest|woff2?|ttf)$/i;
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const same = url.origin === location.origin;
  // API 및 동적 경로: 네트워크 전용
  if (same && (/^\/(jobs|health|diarize|api)(\/|$)/.test(url.pathname) || req.headers.get('accept')?.includes('application/json'))) return;
  if (same && /\/config\.js$/.test(url.pathname)) { e.respondWith(fetch(req).catch(() => caches.match(req))); return; }
  const cacheable = (same && (url.pathname === '/' || url.pathname.endsWith('/') || STATIC.test(url.pathname)))
    || /cdnjs\.cloudflare\.com|cdn\.jsdelivr\.net|fonts\.(googleapis|gstatic)\.com/.test(url.host);
  if (!cacheable) return;
  const put = res => { if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); } return res; };
  // 앱 파일(같은 주소): 네트워크 우선 → 배포하면 바로 새 버전. 오프라인일 때만 캐시
  if (same) { e.respondWith(fetch(req, { cache: 'no-cache' }).then(put).catch(() => caches.match(req).then(hit => hit || caches.match('./index.html')))); return; }
  // CDN 라이브러리·글꼴: 캐시 우선
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(put)));
});
