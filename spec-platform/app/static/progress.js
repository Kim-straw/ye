// 페이지 이동 진행 막대: 링크·버튼을 누르면 화면 맨 위 얇은 줄이 차오르고, 새 페이지가 뜨면 사라짐.
// 원리: 서버가 화면을 통째로 새로 보내는 구조라, "누른 순간 ~ 새 화면 도착" 사이에만 막대를 보여 주면 됨.
// 새 페이지가 뜨면 이 문서가 통째로 바뀌므로 막대도 자연히 사라짐. 입력값(비밀번호 등)은 전혀 읽지 않음.
(function () {
  var bar = document.createElement("div");
  bar.className = "loadbar";
  bar.setAttribute("aria-hidden", "true");
  document.body.appendChild(bar);

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var showTimer = null, tickTimer = null, giveUpTimer = null, value = 0;
  var SHOW_DELAY = 150;      // 이보다 빨리 끝나면 막대를 아예 안 보여 줌 (번쩍임 방지)
  var GIVE_UP = 90000;       // 이동이 취소되는 등 아무 일도 없으면 90초 뒤 숨김 (서버 깨우는 시간 약 50초보다 길게)

  function set(v) { value = v; bar.style.transform = "scaleX(" + v + ")"; }

  function start() {
    if (showTimer || tickTimer || bar.classList.contains("on")) return;
    showTimer = setTimeout(function () {
      showTimer = null;
      bar.classList.add("on");
      if (reduce) { set(0.85); return; }           // 움직임 줄이기: 차오르지 않고 고정된 줄만
      set(0.08);
      tickTimer = setInterval(function () {        // 남은 거리의 일부씩 차올라서 점점 느려지고 90% 근처에서 멈춤
        set(value + (0.9 - value) * 0.06);
      }, 200);
    }, SHOW_DELAY);
    giveUpTimer = setTimeout(stop, GIVE_UP);
  }

  function stop() {
    clearTimeout(showTimer); clearInterval(tickTimer); clearTimeout(giveUpTimer);
    showTimer = tickTimer = giveUpTimer = null;
    bar.classList.remove("on");
    set(0);
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    if ((a.target && a.target !== "_self") || a.hasAttribute("download")) return;
    var raw = a.getAttribute("href") || "";
    if (raw.charAt(0) === "#") return;
    var url;
    try { url = new URL(a.href, location.href); } catch (err) { return; }
    if (url.origin !== location.origin) return;     // 외부 사이트, mailto:, tel: 은 제외
    if (url.hash && url.pathname === location.pathname && url.search === location.search) return;  // 같은 화면 안의 # 이동
    start();
  });

  document.addEventListener("submit", function (e) {
    // 브라우저가 입력 검사(필수 칸 등)에서 막으면 submit 이벤트 자체가 오지 않음
    var form = e.target;
    if (e.defaultPrevented || (form.target && form.target !== "_self")) return;
    start();
  });

  // 뒤로 가기로 예전 화면이 그대로 돌아올 때(bfcache) 막대가 걸린 채로 남지 않게
  window.addEventListener("pageshow", stop);
})();
