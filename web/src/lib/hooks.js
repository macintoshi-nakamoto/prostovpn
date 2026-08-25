import { useEffect, useRef, useState } from "react";

export function markRevealed(node) {
  const variant = node.getAttribute("data-reveal") || node.getAttribute("data-revealed") || "up";
  node.removeAttribute("data-reveal");
  node.setAttribute("data-revealed", variant);
}

export function useReveal(options = {}) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;

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

export function prefersReducedMotion() {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

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

      const scale = window.innerWidth < 700 ? 0.5 : 1;

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

export function useTilt(max = 7) {
  const ref = useRef(null);

  useEffect(() => {
    const node = ref.current;
    if (!node || prefersReducedMotion()) return undefined;

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
