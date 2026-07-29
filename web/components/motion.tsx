"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/** ¿El usuario pidió menos movimiento? Los primitivos lo respetan (además del reset
 *  global en globals.css). */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return reduced;
}

/** Una cifra que cuenta hasta su valor al aparecer (y al cambiar). Da el pulso "vivo"
 *  de un dashboard premium. Con reduced-motion muestra el valor de una vez. */
export function AnimatedNumber({
  value,
  format = (n) => String(Math.round(n)),
  duration = 650,
  className,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(0);
  const from = useRef(0);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    if (reduced) {
      setDisplay(value);
      from.current = value;
      return;
    }
    const start = performance.now();
    const origin = from.current;
    const delta = value - origin;
    if (delta === 0) return;
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cúbico
      setDisplay(origin + delta * eased);
      if (t < 1) {
        raf.current = requestAnimationFrame(tick);
      } else {
        from.current = value;
      }
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [value, duration, reduced]);

  return <span className={className}>{format(display)}</span>;
}

/** Expandir/colapsar suave con el truco de grid 0fr→1fr (sin medir alturas en JS,
 *  robusto). Con reduced-motion el reset global lo vuelve instantáneo. */
export function Collapse({
  open,
  children,
  className,
}: {
  open: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${className ?? ""}`}
      style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
    >
      <div className="min-h-0 overflow-hidden">{children}</div>
    </div>
  );
}
