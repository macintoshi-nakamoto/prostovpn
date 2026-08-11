import { useEffect, useRef, useState } from "react";

/**
 * Появление при прокрутке.
 *
 * Ставит на элемент [data-reveal] сразу и снимает его на [data-revealed],
 * когда элемент входит в область видимости, — CSS доводит анимацию. Один
 * IntersectionObserver на элемент, срабатывает один раз: повторно прятать
 * уже показанное незачем.
 */
export function useReveal(options = {}) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;

    // Уважаем системную настройку «меньше движения».
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      node.removeAttribute("data-reveal");
      node.setAttribute("data-revealed", "");
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.removeAttribute("data-reveal");
            entry.target.setAttribute("data-revealed", "");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: options.threshold ?? 0.15, rootMargin: options.rootMargin ?? "0px 0px -8% 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
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
