import { useEffect, useRef, useState } from "react";
import { useParallax, prefersReducedMotion } from "../lib/hooks";
import "./hero-orbit.css";

/**
 * Объект в правой части героя.
 *
 * Появляется собранно и заметно: прилетает из глубины с поворотом и
 * размытием, за ним расходится волна-ореол, дальше медленно дышит и качается
 * от прокрутки. Курсор слегка отклоняет его — объект кажется висящим в
 * воздухе, а не наклеенным.
 *
 * Картинки может не быть на месте: файл кладут отдельно. Тогда блок молча
 * убирает себя — пустая рамка с крестиком в углу героя хуже, чем ничего.
 */
export function HeroOrbit({ src = "/assets/hero-orbit.png", alt = "" }) {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const parallax = useParallax(0.08, { rotate: 1.6 });
  const wrapRef = useRef(null);

  // Наклон за курсором по всей области героя, а не только по картинке:
  // объект отзывается ещё до того, как до него доводят мышь.
  useEffect(() => {
    const node = wrapRef.current;
    if (!node || prefersReducedMotion()) return undefined;
    if (window.matchMedia?.("(hover: none)").matches) return undefined;

    const hero = node.closest(".ld-hero") || document.body;
    let frame = 0;
    let target = { x: 0, y: 0 };

    const draw = () => {
      frame = 0;
      node.style.setProperty("--orbit-x", `${(target.x * 18).toFixed(1)}px`);
      node.style.setProperty("--orbit-y", `${(target.y * 14).toFixed(1)}px`);
      node.style.setProperty("--orbit-turn", `${(target.x * 5).toFixed(2)}deg`);
    };

    const onMove = (e) => {
      const rect = hero.getBoundingClientRect();
      target = {
        x: (e.clientX - rect.left) / rect.width - 0.5,
        y: (e.clientY - rect.top) / rect.height - 0.5,
      };
      if (!frame) frame = requestAnimationFrame(draw);
    };
    const onLeave = () => {
      target = { x: 0, y: 0 };
      if (!frame) frame = requestAnimationFrame(draw);
    };

    hero.addEventListener("pointermove", onMove);
    hero.addEventListener("pointerleave", onLeave);
    return () => {
      hero.removeEventListener("pointermove", onMove);
      hero.removeEventListener("pointerleave", onLeave);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  if (failed) return null;

  return (
    <div className="orbit" ref={parallax} aria-hidden={alt ? undefined : "true"}>
      <div className={`orbit-in${ready ? " orbit-ready" : ""}`} ref={wrapRef}>
        <span className="orbit-halo" />
        <span className="orbit-ring orbit-ring-1" />
        <span className="orbit-ring orbit-ring-2" />
        {/*
        WebP вчетверо легче того же PNG с прозрачностью, а герой — первое,
        что грузится. PNG остаётся запасным: <picture> сам выберет по силам
        браузера, и старый обойдётся без webp.
        */}
        <picture>
          <source srcSet={src.replace(/\.png$/, ".webp")} type="image/webp" />
          <img
            className="orbit-img"
            src={src}
            alt={alt}
            onLoad={() => setReady(true)}
            onError={() => setFailed(true)}
          />
        </picture>
      </div>
    </div>
  );
}
