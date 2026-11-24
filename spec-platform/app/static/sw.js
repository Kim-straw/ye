// 서비스 워커: 앱 뒤에서 돌아가는 작은 비서.
// 화면 뼈대(CSS, 아이콘, 시작 화면)는 폰에 저장해 두고, 데이터 페이지는 항상 서버에서 새로 받음.
// 인터넷이 끊기면 '오프라인' 안내를 보여 줌.
// 서버가 잠들어 있어 화면 이동이 SPLASH_AFTER_MS보다 오래 걸리면, 저장해 둔 시작 화면(/static/splash.html)을 대신 보여 줌.
//   - 실제로 기다릴 때만 보임(빠른 페이지는 그대로). GET 화면 이동에만 적용(POST·폼 제출·/api·/static·/healthz 제외).
//   - 시작 화면은 /healthz를 확인하다가 서버가 깨어나면 같은 주소를 다시 불러옴.
const CACHE = "specroad-v15";
const SHELL = ["/static/style.css", "/static/progress.js", "/static/icon.svg", "/static/icon-192.png", "/static/splash.html"];
const SPLASH_AFTER_MS = 1500;
const AWAKE_GRACE_MS = 30000;  // 서버가 깨어 있는 것을 방금 확인했으면 이 시간 동안은 시작 화면을 띄우지 않음(다시 불러올 때 시작 화면이 반복되는 것 방지)
let lastAwake = 0;

const offline = () => new Response(
  '<meta charset="utf-8"><meta name="viewport" content="width=device-width"><p style="font-family:sans-serif;padding:2rem">인터넷 연결이 끊겼습니다. 연결 후 다시 시도해 주세요.</p>',
  { headers: { "Content-Type": "text/html; charset=utf-8" } }
);

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

// 화면 이동: 서버 응답과 타이머를 경주시켜, 타이머가 먼저 끝나면 시작 화면을 보여 줌
function navigateWithSplash(req) {
  const network = fetch(req);
  if (Date.now() - lastAwake < AWAKE_GRACE_MS) {
    return network.then((r) => { lastAwake = Date.now(); return r; }).catch(offline);
  }
  return new Promise((resolve) => {
    let done = false;
    network
      .then((r) => { if (!done) { done = true; lastAwake = Date.now(); resolve(r); } })
      .catch(() => { if (!done) { done = true; resolve(offline()); } });
    setTimeout(() => {
      if (done) return;
      caches.match("/static/splash.html").then((hit) => {
        if (done || !hit) return;  // 시작 화면이 저장돼 있지 않으면 그냥 서버 응답을 기다림
        done = true;
        resolve(hit);
      });
    }, SPLASH_AFTER_MS);
  });
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;  // POST(로그인·폼 제출)는 건드리지 않음
  const path = new URL(req.url).pathname;
  if (path.startsWith("/static/")) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
    return;
  }
  if (path === "/healthz") {  // 시작 화면이 서버를 확인하는 요청: 응답이 오면 '깨어 있음'으로 기록만 함
    e.respondWith(fetch(req).then((r) => { if (r.ok) lastAwake = Date.now(); return r; }));
    return;
  }
  if (req.mode === "navigate" && !path.startsWith("/api/")) {
    e.respondWith(navigateWithSplash(req));
  }
});
