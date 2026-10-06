"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { lockScroll } from "@/lib/scroll-lock";

// Pop-up centrado para un momento FOCALIZADO: confirmar una acción, un alta corta. Es el
// complemento del Drawer lateral (que es para HOJEAR/editar un detalle): el Modal bloquea
// y pide una decisión. Mismo acabado premium: profundidad por sombra, entrada con peso,
// focus-trap mínimo, Esc y scrim para cerrar.
export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
  /** `sm` para un confirm; `md` para un alta con más cuerpo. */
  size?: "sm" | "md" | "lg";
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    const opener = document.activeElement as HTMLElement | null;

    const focusables = () =>
      panel
        ? Array.from(
            panel.querySelectorAll<HTMLElement>(
              'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])',
            ),
          ).filter((el) => el.offsetParent !== null)
        : [];

    (focusables()[0] ?? panel)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
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
    const soltarScroll = lockScroll();
    return () => {
      window.removeEventListener("keydown", onKey);
      soltarScroll();
      opener?.focus?.();
    };
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;

  const max = size === "lg" ? "max-w-lg" : size === "sm" ? "max-w-sm" : "max-w-md";

  // Portal a <body>, igual que el Drawer: fuera del ancestro con `transform`, el velo
  // cubre toda la ventana, menú lateral y barra de arriba incluidos.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-capa-modal
    >
      <div className="modal-scrim absolute inset-0 bg-ink/20" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`modal-in relative flex max-h-[calc(100dvh-2rem)] w-full flex-col overflow-hidden rounded-2xl bg-surface shadow-lg outline-none ${max}`}
      >
        {(title || subtitle) && (
          <header className="flex shrink-0 items-start justify-between gap-3 px-6 pb-1 pt-5">
            <div className="min-w-0">
              {title && (
                <h2 className="text-seccion font-semibold text-ink">{title}</h2>
              )}
              {subtitle && <p className="mt-0.5 truncate text-cuerpo text-ink-3">{subtitle}</p>}
            </div>
            <button
              onClick={onClose}
              aria-label="Cerrar"
              className="-mr-2 -mt-1.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-ink-3 hover:bg-fill hover:text-ink"
            >
              <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
                <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </header>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-4">{children}</div>
      </div>
      <style>{`
        @keyframes modalIn { from { transform: translateY(10px) scale(.985); opacity: 0; } to { transform: none; opacity: 1; } }
        @keyframes modalScrimIn { from { opacity: 0; } to { opacity: 1; } }
        .modal-in { animation: modalIn .22s cubic-bezier(.22,1,.36,1) both; }
        .modal-scrim { animation: modalScrimIn .16s ease-out both; }
        @media (prefers-reduced-motion: reduce) { .modal-in, .modal-scrim { animation: none; } }
      `}</style>
    </div>,
    document.body,
  );
}
