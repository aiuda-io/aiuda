"use client";

import { useEffect, useRef } from "react";

// Panel lateral (derecha) para el detalle de un registro. Es EL gesto de detalle de la
// consola: preserva el contexto (el tablero/lista se queda detrás) mientras actúas. Acabado
// premium: profundidad por sombra, ancho por contenido (md/lg), entrada con peso y aire.
export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  /** `lg` para detalle con más cuerpo (la Mesa del Centro: mensaje + canal + acciones). */
  size?: "md" | "lg";
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    // A quién devolverle el foco al cerrar (el registro/botón que abrió el drawer).
    const opener = document.activeElement as HTMLElement | null;

    // Focusables visibles dentro del panel (focus-trap mínimo, sin dependencias).
    const focusables = () =>
      panel
        ? Array.from(
            panel.querySelectorAll<HTMLElement>(
              'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])',
            ),
          ).filter((el) => el.offsetParent !== null)
        : [];

    // Al abrir, lleva el foco al primer control del panel (el botón Cerrar) o al panel.
    (focusables()[0] ?? panel)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      // Cicla el foco dentro del drawer: Tab desde el último vuelve al primero y
      // Shift+Tab desde el primero salta al último.
      const els = focusables();
      if (els.length === 0) {
        e.preventDefault();
        panel?.focus();
        return;
      }
      const first = els[0];
      const last = els[els.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      // Devuelve el foco a donde estaba antes de abrir.
      opener?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <div className="drawer-scrim absolute inset-0 bg-ink/30" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`drawer-in relative ml-auto flex h-full w-full flex-col border-l border-line bg-surface outline-none ${
          size === "lg" ? "max-w-[600px]" : "max-w-md"
        }`}
        style={{ boxShadow: "0 12px 48px -12px oklch(0.3 0.04 235 / 0.24)" }}
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-cuerpo font-semibold tracking-tight text-ink">{title}</h2>
            {subtitle && <p className="mt-0.5 truncate text-cuerpo text-ink-3">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Cerrar"
            className="-mr-1.5 -mt-0.5 shrink-0 rounded-md px-1.5 py-0.5 text-titulo leading-none text-ink-3 transition-colors hover:bg-panel hover:text-ink"
          >
            &times;
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </div>
      <style>{`
        @keyframes drawerIn { from { transform: translateX(28px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        @keyframes drawerScrimIn { from { opacity: 0; } to { opacity: 1; } }
        .drawer-in { animation: drawerIn .26s cubic-bezier(.2,.8,.2,1) both; }
        .drawer-scrim { animation: drawerScrimIn .2s ease-out both; }
        @media (prefers-reduced-motion: reduce) { .drawer-in, .drawer-scrim { animation: none; } }
      `}</style>
    </div>
  );
}
