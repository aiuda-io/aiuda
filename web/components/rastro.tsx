"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SECTION_LABELS, isSection } from "@/lib/sections";

// El Rastro recuerda el camino real que recorriste para llegar a donde estás.
// No son migas de jerarquía: son tus pasos, cada uno clickeable. Así nunca
// sientes que "no sabes cómo llegaste aquí" ni cómo regresar.

type RastroValue = {
  trail: string[];
  labelFor: (href: string) => string;
  setLabel: (href: string, label: string) => void;
  direction: "forward" | "back";
};

const RastroContext = createContext<RastroValue | null>(null);

// Reconcilia el rastro cuando cambia la ruta:
//  - Sección de primer nivel (destino del menú): reinicia a [Resumen, sección].
//  - Detalle: continúa el camino. Si ya estabas en esa página, recorta hasta
//    ahí (regresaste); si no, la agrega al final.
function reconcile(prev: string[], p: string): string[] {
  if (p === "/") return ["/"];
  if (isSection(p)) return ["/", p];
  const idx = prev.indexOf(p);
  if (idx >= 0) return prev.slice(0, idx + 1);
  return [...(prev.length ? prev : ["/"]), p];
}

function sameTrail(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((h, i) => h === b[i]);
}

export function RastroProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [trail, setTrail] = useState<string[]>(() => reconcile([], pathname));
  const [lastPath, setLastPath] = useState<string>(pathname);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const [labels, setLabels] = useState<Record<string, string>>({});

  // Sincroniza el rastro con la ruta durante el render (patrón recomendado de
  // React para derivar estado de un cambio, sin useEffect ni un render de
  // retraso). De paso define la dirección del viaje: si la ruta ya estaba en el
  // rastro, regresaste (atrás); si no, te metiste (adelante).
  if (pathname !== lastPath) {
    setLastPath(pathname);
    setDirection(trail.indexOf(pathname) >= 0 ? "back" : "forward");
    setTrail((prev) => {
      const next = reconcile(prev, pathname);
      return sameTrail(prev, next) ? prev : next;
    });
  }

  const setLabel = useCallback((href: string, label: string) => {
    setLabels((prev) => (prev[href] === label ? prev : { ...prev, [href]: label }));
  }, []);

  const labelFor = useCallback(
    (href: string) => labels[href] ?? SECTION_LABELS[href] ?? "Detalle",
    [labels],
  );

  const value = useMemo<RastroValue>(
    () => ({ trail, labelFor, setLabel, direction }),
    [trail, labelFor, setLabel, direction],
  );

  return <RastroContext.Provider value={value}>{children}</RastroContext.Provider>;
}

// Una página de detalle declara su etiqueta humana: usePageTrail("Factura M-107").
// No-op si no hay provider (ej. /entrar).
export function usePageTrail(label: string | undefined | null) {
  const ctx = useContext(RastroContext);
  const pathname = usePathname();
  useEffect(() => {
    if (ctx && label) ctx.setLabel(pathname, label);
  }, [ctx, pathname, label]);
}

// Rutas que traen su PROPIA navegación maestro-detalle (lista + hilo con su
// regreso): ahí el "Volver" global estorba y pelea con el alto fijo del panel.
// El hilo vive en /conversaciones?id=... (misma ruta que la lista).
const SELF_NAV_SUBTREES = ["/conversaciones"];

// El paso anterior del camino: a dónde regresa "Volver" de verdad. Solo en páginas de
// DETALLE: en un destino de menú (sección) o en el Resumen no hay "de dónde venías" honesto
// —ahí manda la barra lateral, no un "volver" que apunte falsamente a Resumen.
export function useRastroBack(): { href: string; label: string } | null {
  const ctx = useContext(RastroContext);
  const pathname = usePathname();
  if (!ctx || ctx.trail.length < 2) return null;
  if (pathname === "/" || isSection(pathname)) return null;
  if (SELF_NAV_SUBTREES.some((p) => pathname.startsWith(p))) return null;
  const href = ctx.trail[ctx.trail.length - 2];
  return { href, label: ctx.labelFor(href) };
}

// Botón "Volver" explícito y correcto (regresa a donde venías, no a un padre
// fijo). Pensado para quien no es técnico: etiqueta clara, no solo una flecha.
export function RastroBack({ className = "" }: { className?: string }) {
  const back = useRastroBack();
  if (!back) return null;
  return (
    <Link
      href={back.href}
      className={`inline-flex items-center gap-1 text-cuerpo font-medium text-accent-ink transition-colors hover:underline ${className}`}
    >
      <span aria-hidden className="text-cuerpo leading-none">‹</span>
      Volver a {back.label}
    </Link>
  );
}

// Transición de página sobria: el contenido llega con peso (fade + 6px) en la
// dirección del viaje. El topbar, el sidebar y el "Volver" quedan anclados.
export function PageTransition({ children }: { children: React.ReactNode }) {
  const ctx = useContext(RastroContext);
  const pathname = usePathname();
  const dir = ctx?.direction ?? "forward";
  return (
    <div key={pathname} className={dir === "back" ? "page-enter-back" : "page-enter-fwd"}>
      {children}
    </div>
  );
}
