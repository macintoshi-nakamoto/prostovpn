(() => {
  "use strict";

  const root = document.documentElement;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.classList.add("js");

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

      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );
    targets.forEach((el) => observer.observe(el));
  }

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

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;

    const value = button.getAttribute("data-copy");
    if (!value) return;

    const label = button.textContent;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
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

  document.querySelectorAll("[data-year]").forEach((el) => {
    el.textContent = String(new Date().getFullYear());
  });
})();
