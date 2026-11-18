// 서비스 워커: 앱 뒤에서 돌아가는 작은 비서.
// 화면 뼈대(CSS, 아이콘)는 폰에 저장해 두고, 데이터 페이지는 항상 서버에서 새로 받음.
// 인터넷이 끊기면 '오프라인' 안내를 보여 줌.
const CACHE = "specroad-v11";
const SHELL = ["/static/style.css", "/static/progress.js", "/static/icon.svg", "/static/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  if (new URL(req.url).pathname.startsWith("/static/")) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
    return;
  }
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => new Response(
      '<meta charset="utf-8"><meta name="viewport" content="width=device-width"><p style="font-family:sans-serif;padding:2rem">인터넷 연결이 끊겼습니다. 연결 후 다시 시도해 주세요.</p>',
      { headers: { "Content-Type": "text/html; charset=utf-8" } }
    )));
  }
});
