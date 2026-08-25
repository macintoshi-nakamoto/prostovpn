import { useEffect, useRef, useState } from "react";
import { useParallax, prefersReducedMotion } from "../lib/hooks";
import "./hero-orbit.css";

export function HeroOrbit({ src = "/assets/hero-orbit.png", alt = "" }) {
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const parallax = useParallax(0.08, { rotate: 1.6 });
  const wrapRef = useRef(null);

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
