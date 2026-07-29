"use client";

import { useEffect, useRef } from "react";

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
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      opener?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const max = size === "lg" ? "max-w-lg" : size === "sm" ? "max-w-sm" : "max-w-md";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="modal-scrim absolute inset-0 bg-ink/30" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`modal-in relative flex max-h-[calc(100dvh-2rem)] w-full flex-col overflow-hidden rounded-2xl border border-line bg-surface outline-none ${max}`}
        style={{ boxShadow: "0 24px 60px -20px oklch(0.3 0.04 235 / 0.32)" }}
      >
        {(title || subtitle) && (
          <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line px-5 py-3.5">
            <div className="min-w-0">
              {title && (
                <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
              )}
              {subtitle && <p className="mt-0.5 truncate text-[12px] text-ink-3">{subtitle}</p>}
            </div>
            <button
              onClick={onClose}
              aria-label="Cerrar"
              className="-mr-1.5 -mt-0.5 shrink-0 rounded-md px-1.5 py-0.5 text-[19px] leading-none text-ink-3 transition-colors hover:bg-panel hover:text-ink"
            >
              &times;
            </button>
          </header>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
      <style>{`
        @keyframes modalIn { from { transform: translateY(10px) scale(.985); opacity: 0; } to { transform: none; opacity: 1; } }
        @keyframes modalScrimIn { from { opacity: 0; } to { opacity: 1; } }
        .modal-in { animation: modalIn .2s cubic-bezier(.2,.8,.2,1) both; }
        .modal-scrim { animation: modalScrimIn .16s ease-out both; }
        @media (prefers-reduced-motion: reduce) { .modal-in, .modal-scrim { animation: none; } }
      `}</style>
    </div>
  );
}
