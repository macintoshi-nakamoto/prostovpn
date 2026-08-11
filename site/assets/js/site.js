/* Оживление страниц: появление при прокрутке, построчный заголовок,
   курсор, меню и копирование.

   Ни одной внешней библиотеки. Не из принципа: сайт, который продаёт
   приватность, не должен тянуть скрипт с чужого домена, а сто килобайт
   анимационного движка ради четырёх эффектов — плохой обмен.

   Ни один эффект не является условием читаемости. Класс `js` ставится
   скриптом, и всё, что прячется до появления, прячется только этим
   классом: без JavaScript страница показывает всё сразу. */

(() => {
  "use strict";

  const root = document.documentElement;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.add("js");

  // ── Построчный заголовок ──────────────────────────────────────────────
  // Разбиваем по словам и собираем строки по фактическим переносам: делить
  // по символам красиво ровно до первого экранного диктора, который
  // прочитает заголовок по буквам.

  function splitLines(el) {
    const text = el.textContent.trim();
    el.setAttribute("aria-label", text);

    const words = text.split(/\s+/);
    el.textContent = "";
    const spans = words.map((word, i) => {
      const span = document.createElement("span");
      span.className = "split-word";
      span.textContent = i === words.length - 1 ? word : word + " ";
      span.setAttribute("aria-hidden", "true");
      el.appendChild(span);
      return span;
    });

    // Группируем по вертикальной позиции — это и есть настоящие строки.
    const lines = [];
    let currentTop = null;
    for (const span of spans) {
      const top = Math.round(span.offsetTop);
      if (currentTop === null || Math.abs(top - currentTop) > 4) {
        lines.push([]);
        currentTop = top;
      }
      lines[lines.length - 1].push(span);
    }

    el.textContent = "";
    lines.forEach((line, index) => {
      const outer = document.createElement("span");
      outer.className = "split-line";
      outer.setAttribute("aria-hidden", "true");
      const inner = document.createElement("span");
      inner.style.setProperty("--delay", `${index * 80}ms`);
      line.forEach((span) => inner.appendChild(span));
      outer.appendChild(inner);
      el.appendChild(outer);
    });
    el.classList.add("split");
  }

  if (!reduced) {
    document.querySelectorAll("[data-split]").forEach(splitLines);
  }

  // ── Появление при прокрутке ───────────────────────────────────────────

  const targets = [...document.querySelectorAll("[data-reveal], [data-split]")];

  if (reduced || !("IntersectionObserver" in window)) {
    targets.forEach((el) => el.classList.add("in"));
  } else {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("in");
          observer.unobserve(entry.target);
        }
      },
      // Порог небольшой, а отступ снизу отрицательный: элемент проявляется,
      // когда действительно вошёл в кадр, а не когда коснулся края.
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );
    targets.forEach((el) => observer.observe(el));
  }

  // ── Шапка ─────────────────────────────────────────────────────────────

  const top = document.querySelector(".top");
  if (top) {
    const onScroll = () => top.classList.toggle("scrolled", window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  const toggle = document.querySelector(".nav-toggle");
  const nav = document.querySelector(".nav");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    nav.addEventListener("click", (event) => {
      if (event.target.tagName === "A") nav.classList.remove("open");
    });
  }

  // ── Курсор ────────────────────────────────────────────────────────────
  // Только для мыши. На тач-экране курсора нет, и рисовать его там — это
  // кружок, который дёргается вслед за нажатиями.

  if (!reduced && window.matchMedia("(pointer: fine)").matches) {
    const dot = document.createElement("div");
    dot.className = "cursor";
    dot.setAttribute("aria-hidden", "true");
    document.body.appendChild(dot);

    let x = 0;
    let y = 0;
    let cx = 0;
    let cy = 0;

    window.addEventListener(
      "mousemove",
      (event) => {
        x = event.clientX;
        y = event.clientY;
        dot.classList.add("on");
      },
      { passive: true },
    );

    // Догоняющее движение: курсор чуть отстаёт от указателя — от этого
    // страница ощущается «тяжелее», чем при точном совпадении.
    const follow = () => {
      cx += (x - cx) * 0.16;
      cy += (y - cy) * 0.16;
      dot.style.transform = `translate(${cx}px, ${cy}px) translate(-50%, -50%)`;
      requestAnimationFrame(follow);
    };
    requestAnimationFrame(follow);

    const hot = "a, button, .plan, input, select, textarea, [data-hot]";
    document.addEventListener("mouseover", (event) => {
      if (event.target.closest(hot)) dot.classList.add("hot");
    });
    document.addEventListener("mouseout", (event) => {
      if (event.target.closest(hot)) dot.classList.remove("hot");
    });
  }

  // ── Копирование ───────────────────────────────────────────────────────

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;

    const value = button.getAttribute("data-copy");
    if (!value) return;

    const label = button.textContent;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Буфер обмена недоступен без https или без разрешения — старый
      // способ через скрытое поле работает и там.
      const field = document.createElement("textarea");
      field.value = value;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      try {
        document.execCommand("copy");
      } catch {
        return;
      } finally {
        field.remove();
      }
    }

    button.textContent = "Скопировано";
    button.classList.add("done");
    setTimeout(() => {
      button.textContent = label;
      button.classList.remove("done");
    }, 1800);
  });

  // Год в подвале — чтобы он не устарел молча.
  document.querySelectorAll("[data-year]").forEach((el) => {
    el.textContent = String(new Date().getFullYear());
  });
})();
