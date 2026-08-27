// Трамплин для запуска AmneziaVPN из мини-аппа Telegram: вебвью глушит
// кастомные схемы, поэтому мини-апп открывает эту страницу во внешнем
// браузере (openLink), а уже отсюда дёргается vpn://-ссылка. Ключ передаётся
// во фрагменте (#…) — он не уходит на сервер и не попадает в логи.
(function () {
  "use strict";

  var url = "";
  try {
    url = decodeURIComponent((window.location.hash || "").slice(1));
  } catch (e) {}
  // Только схема Амнезии: страница не должна работать открытым редиректором.
  var valid = /^vpn:\/\/[A-Za-z0-9+/=_-]+$/.test(url);

  var en = (navigator.language || "").slice(0, 2).toLowerCase() !== "ru";
  var $ = function (id) { return document.getElementById(id); };

  if (en) {
    document.documentElement.lang = "en";
    document.title = "Prosto VPN — open in AmneziaVPN";
    $("title").textContent = "Opening AmneziaVPN…";
    $("sub").textContent = "Confirm opening the app. If no prompt appeared, tap the button below.";
    $("open").textContent = "Open AmneziaVPN";
    $("copy").textContent = "Copy the key";
    $("note").innerHTML = 'No app yet? Install it from <a href="https://apps.apple.com/app/amneziavpn/id1600529900">App&nbsp;Store</a> or <a href="https://play.google.com/store/apps/details?id=org.amnezia.vpn">Google&nbsp;Play</a> and come back to this page.';
  }

  if (!valid) {
    $("em").textContent = "🤔";
    $("title").textContent = en ? "The link is incomplete" : "Ссылка неполная";
    $("sub").textContent = en
      ? "Open this page from the Prosto VPN app again — the key was not passed along."
      : "Откройте эту страницу из кабинета Prosto VPN ещё раз — ключ не передался.";
    $("open").className += " hide";
    $("copy").className += " hide";
    return;
  }

  var go = function () {
    window.location.href = url;
  };

  $("open").addEventListener("click", go);

  $("copy").addEventListener("click", function () {
    var done = function () {
      $("copy").textContent = en ? "Copied" : "Скопировано";
      setTimeout(function () {
        $("copy").textContent = en ? "Copy the key" : "Скопировать ключ";
      }, 1500);
    };
    var legacy = function () {
      var area = document.createElement("textarea");
      area.value = url;
      document.body.appendChild(area);
      area.select();
      try { document.execCommand("copy"); done(); } catch (e) {}
      document.body.removeChild(area);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, legacy);
    } else {
      legacy();
    }
  });

  // Автопопытка сразу после загрузки: Safari покажет запрос «Открыть в…»,
  // а браузеры, требующие жеста, проигнорируют — для них кнопка выше.
  setTimeout(go, 350);

  // Браузер может вернуть уже открытую вкладку и сменить только #фрагмент —
  // страница при этом не перезагружается, поэтому ключ перечитывается руками.
  window.addEventListener("hashchange", function () {
    window.location.reload();
  });
})();
