// Трамплин для добавления ключа в AmneziaVPN из мини-аппа Telegram.
// Вебвью Telegram глушит кастомные схемы, поэтому мини-апп открывает эту
// страницу во внешнем браузере. Дальше — по платформе: Android понимает
// vpn://-деплинк, а AmneziaVPN на iOS схему не регистрирует вовсе
// (amnezia-client#1067), там рабочий путь — ключ через буфер обмена.
// Ключ передаётся во фрагменте (#…): он не уходит на сервер и не
// попадает в логи. Язык приходит из мини-аппа параметром ?l=.
(function () {
  "use strict";

  var url = "";
  try {
    url = decodeURIComponent((window.location.hash || "").slice(1));
  } catch (e) {}
  // Только схема Амнезии: страница не должна работать открытым редиректором.
  var valid = /^vpn:\/\/[A-Za-z0-9+/=_-]+$/.test(url);

  var en = /(^|[?&])l=en(&|$)/.test(window.location.search);
  var ios = /iPhone|iPad|iPod/i.test(navigator.userAgent);
  var $ = function (id) { return document.getElementById(id); };
  var STORE = "https://apps.apple.com/app/amneziavpn/id1600529900";

  var T = en
    ? {
        docTitle: "Prosto VPN — add the key to AmneziaVPN",
        opening: "Opening AmneziaVPN…",
        openingSub: "Confirm opening the app. If no prompt appeared, tap the button below.",
        iosTitle: "Add the key to AmneziaVPN",
        iosSub: "1. Copy the key with the button below.\n2. Open AmneziaVPN and tap “+” — the app will pick the key up from the clipboard.",
        open: "Open AmneziaVPN",
        iosOpen: "AmneziaVPN in the App Store",
        copy: "Copy the key",
        copied: "Copied — now open AmneziaVPN",
        note: 'No app yet? Install it from <a href="' + STORE + '">App&nbsp;Store</a> or <a href="https://play.google.com/store/apps/details?id=org.amnezia.vpn">Google&nbsp;Play</a> and come back to this page.',
        badTitle: "The link is incomplete",
        badSub: "Open this page from the Prosto VPN app again — the key was not passed along.",
      }
    : {
        docTitle: "Prosto VPN — ключ для AmneziaVPN",
        opening: "Открываем AmneziaVPN…",
        openingSub: "Подтвердите открытие приложения. Если запрос не появился — нажмите кнопку ниже.",
        iosTitle: "Добавьте ключ в AmneziaVPN",
        iosSub: "1. Скопируйте ключ кнопкой ниже.\n2. Откройте AmneziaVPN и нажмите «+» — приложение подхватит ключ из буфера обмена.",
        open: "Открыть AmneziaVPN",
        iosOpen: "AmneziaVPN в App Store",
        copy: "Скопировать ключ",
        copied: "Скопировано — откройте AmneziaVPN",
        note: 'Нет приложения? Установите из <a href="' + STORE + '">App&nbsp;Store</a> или <a href="https://play.google.com/store/apps/details?id=org.amnezia.vpn">Google&nbsp;Play</a> и вернитесь на эту страницу.',
        badTitle: "Ссылка неполная",
        badSub: "Откройте эту страницу из кабинета Prosto VPN ещё раз — ключ не передался.",
      };

  document.documentElement.lang = en ? "en" : "ru";
  document.title = T.docTitle;
  $("note").innerHTML = T.note;

  if (!valid) {
    $("em").textContent = "🤔";
    $("title").textContent = T.badTitle;
    $("sub").textContent = T.badSub;
    $("open").className += " hide";
    $("copy").className += " hide";
    return;
  }

  var copyKey = function () {
    var done = function () {
      $("copy").textContent = T.copied;
      setTimeout(function () { $("copy").textContent = T.copy; }, 2200);
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
  };

  $("copy").addEventListener("click", copyKey);

  if (ios) {
    // На iOS vpn:// некому обработать — Safari скажет «адрес недействителен».
    // Правильный путь: ключ в буфер → открыть приложение → импорт из буфера.
    $("title").textContent = T.iosTitle;
    $("sub").textContent = T.iosSub;
    $("sub").style.textAlign = "left";
    var openBtn = $("open");
    openBtn.textContent = T.iosOpen;
    // Копирование здесь главное действие — меняем кнопки ролями и местами.
    openBtn.className = "btn alt";
    $("copy").className = "btn";
    openBtn.parentNode.insertBefore($("copy"), openBtn);
    openBtn.addEventListener("click", function () {
      window.location.href = STORE;
    });
  } else {
    $("title").textContent = T.opening;
    $("sub").textContent = T.openingSub;
    var go = function () { window.location.href = url; };
    $("open").textContent = T.open;
    $("open").addEventListener("click", go);
    // Автопопытка: Android покажет диалог открытия приложения, а браузеры,
    // требующие жеста, проигнорируют — для них кнопка выше.
    setTimeout(go, 350);
  }

  // Браузер может вернуть уже открытую вкладку и сменить только #фрагмент —
  // страница при этом не перезагружается, поэтому перечитываем сами.
  window.addEventListener("hashchange", function () {
    window.location.reload();
  });
})();
