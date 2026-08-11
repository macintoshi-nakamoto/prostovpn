import { useReveal } from "../lib/hooks";

/**
 * Обёртка «появиться при прокрутке».
 *
 * delay сдвигает старт, чтобы соседние элементы всплывали каскадом, а не
 * все разом. Тег настраивается — секции оборачиваем в section, карточки в
 * div, и семантика не ломается.
 */
export function Reveal({ children, delay = 0, as: Tag = "div", className, style, ...rest }) {
  const ref = useReveal();
  return (
    <Tag
      ref={ref}
      data-reveal=""
      className={className}
      style={{ transitionDelay: delay ? `${delay}ms` : undefined, ...style }}
      {...rest}
    >
      {children}
    </Tag>
  );
}
