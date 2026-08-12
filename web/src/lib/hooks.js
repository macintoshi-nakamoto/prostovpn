import { useEffect, useRef, useState } from "react";

/**
 * Переводит элемент в «появился»: вариант движения переезжает из
 * [data-reveal] в [data-revealed], и CSS проигрывает свои кадры.
 *
 * Вариант обязан сохраниться в значении атрибута — по нему выбирается
 * анимация. Пустое значение оставило бы элемент видимым, но без движения.
 */
export function markRevealed(node) {
  const variant = node.getAttribute("data-reveal") || node.getAttribute("data-revealed") || "up";
  node.removeAttribute("data-reveal");
  node.setAttribute("data-revealed", variant);
}

/**
 * Появление при прокрутке.
 *
 * Ставит на элемент [data-reveal] сразу и переносит вариант в
 * [data-revealed], когда элемент входит в область видимости, — CSS доводит
 * анимацию. Один IntersectionObserver на элемент, срабатывает один раз:
 * повторно прятать уже показанное при обычной прокрутке незачем. Заново
 * проигрывает только переход по пункту меню, см. lib/anchors.js.
 */
export function useReveal(options = {}) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;

    // Уважаем системную настройку «меньше движения».
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      markRevealed(node);
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            markRevealed(entry.target);
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: options.threshold ?? 0.15, rootMargin: options.rootMargin ?? "0px 0px -8% 0px" },
    );

    observer.observe(node);

    /*
    Картинка, которая ещё не загрузилась, занимает нулевую высоту.

    У `.art-img` задана только ширина, высота — auto, и до загрузки коробка
    получается 104×0. Доля пересечения у пустой коробки всегда 0, порог 0.05 её
    не берёт, и элемент навсегда остаётся с [data-reveal], то есть с
    opacity: 0. Отсюда и брались «иногда не показывается»: успела картинка
    загрузиться до прохода наблюдателя — видно, не успела — нет.

    Поэтому на загрузке перевешиваем наблюдение заново: у элемента уже есть
    настоящий размер, и наблюдатель сразу присылает первое уведомление с
    честной долей.
    */
    const onLoad = () => {
      if (!node.hasAttribute("data-reveal")) return;
      observer.unobserve(node);
      observer.observe(node);
    };
    if (node.tagName === "IMG" && !node.complete) {
      node.addEventListener("load", onLoad);
    }

    return () => {
      node.removeEventListener("load", onLoad);
      observer.disconnect();
    };
  }, [options.threshold, options.rootMargin]);

  return ref;
}

/**
 * Прокручен ли документ ниже порога.
 *
 * Шапка лендинга по нему становится из прозрачной белой — как в макете.
 */
export function useScrolled(threshold = 40) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);

  return scrolled;
}

/** Система уважает «меньше движения» — тогда никаких эффектов вообще. */
export function prefersReducedMotion() {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

/**
 * Параллакс: элемент едет медленнее (или быстрее) страницы.
 *
 * Считаем в rAF, а не на каждое событие прокрутки: обработчик срабатывает
 * десятки раз за кадр, и запись transform из него дёргает раскладку. Здесь
 * же за кадр происходит ровно одна запись, и только пока элемент на экране.
 *
 * @param speed сдвиг в долях от прокрутки: 0.2 — отстаёт, -0.2 — обгоняет
 */
export function useParallax(speed = 0.15, { rotate = 0 } = {}) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node || prefersReducedMotion()) return undefined;

    let frame = 0;
    let visible = false;

    const apply = () => {
      frame = 0;
      const rect = node.getBoundingClientRect();
      /*
      На телефоне размах вдвое меньше. Прокрутка пальцем быстрая и рывками,
      и тот же сдвиг, что хорош на широком экране, читается там дёрганьем, а
      объект успевает уехать далеко от своего места.
      */
      const scale = window.innerWidth < 700 ? 0.5 : 1;
      // Ноль в тот момент, когда центр элемента совпал с центром экрана:
      // так объект не «прыгает» при появлении, а проходит через своё место.
      const fromCenter = rect.top + rect.height / 2 - window.innerHeight / 2;
      const shift = -fromCenter * speed * scale;
      const turn = rotate ? ` rotate(${(-fromCenter * rotate * scale) / 100}deg)` : "";
      node.style.transform = `translate3d(0, ${shift.toFixed(1)}px, 0)${turn}`;
    };

    const request = () => {
      if (!visible || frame) return;
      frame = requestAnimationFrame(apply);
    };

    const observer = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        if (visible) request();
      },
      { rootMargin: "20% 0px" },
    );
    observer.observe(node);

    window.addEventListener("scroll", request, { passive: true });
    window.addEventListener("resize", request);
    request();

    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", request);
      window.removeEventListener("resize", request);
      if (frame) cancelAnimationFrame(frame);
      node.style.transform = "";
    };
  }, [speed, rotate]);

  return ref;
}

/**
 * Наклон карточки за курсором — объём без тяжёлых библиотек.
 *
 * Углы небольшие: карточка должна отзываться, а не вращаться каруселью.
 */
export function useTilt(max = 7) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node || prefersReducedMotion()) return undefined;
    // На тач-экранах наклон бессмыслен: курсора нет, а обработчик мешает.
    if (window.matchMedia?.("(hover: none)").matches) return undefined;

    let frame = 0;
    let next = null;

    const draw = () => {
      frame = 0;
      if (!next) return;
      const { x, y } = next;
      node.style.setProperty("--tilt-x", `${(-y * max).toFixed(2)}deg`);
      node.style.setProperty("--tilt-y", `${(x * max).toFixed(2)}deg`);
      node.style.setProperty("--glow-x", `${(50 + x * 50).toFixed(1)}%`);
      node.style.setProperty("--glow-y", `${(50 + y * 50).toFixed(1)}%`);
    };

    const onMove = (e) => {
      const rect = node.getBoundingClientRect();
      next = {
        x: (e.clientX - rect.left) / rect.width - 0.5,
        y: (e.clientY - rect.top) / rect.height - 0.5,
      };
      if (!frame) frame = requestAnimationFrame(draw);
    };

    const onLeave = () => {
      next = { x: 0, y: 0 };
      if (!frame) frame = requestAnimationFrame(draw);
    };

    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerleave", onLeave);
    return () => {
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [max]);

  return ref;
}

/** Прячет выпадающее меню по клику мимо него и по Escape. */
export function useDismiss(open, onClose) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);
  return ref;
}
