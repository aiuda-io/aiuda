"use client";

import { useEffect, useRef, useState } from "react";

// Notificaciones no bloqueantes (reemplazan alert()). Basadas en eventos para
// que cualquier componente las dispare sin pasar props ni provider:
//   import { toast } from "@/components/toast";
//   toast("Listo", "success");

export type ToastVariant = "success" | "error" | "info";

type ToastItem = { id: number; message: string; variant: ToastVariant };

export function toast(message: string, variant: ToastVariant = "info") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("aiuda-toast", { detail: { message, variant } }));
}

const ICON: Record<ToastVariant, string> = { success: "M2.5 6.5 5 9l4.5-5", error: "M3 3l6 6M9 3l-6 6", info: "M6 5.5v3M6 3.5h.01" };
const COLOR: Record<ToastVariant, string> = { success: "text-ok", error: "text-danger", info: "text-accent-ink" };

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  useEffect(() => {
    const onToast = (e: Event) => {
      const { message, variant } = (e as CustomEvent).detail as {
        message: string;
        variant: ToastVariant;
      };
      const id = nextId.current++;
      setItems((prev) => [...prev, { id, message, variant }]);
      setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 4000);
    };
    window.addEventListener("aiuda-toast", onToast);
    return () => window.removeEventListener("aiuda-toast", onToast);
  }, []);

  // La live-region se renderiza SIEMPRE (aunque esté vacía): así existe en el DOM
  // antes de que llegue un toast y el lector de pantalla puede anunciarlo. Los toasts
  // de error usan role="alert" (asertivo, se anuncia de inmediato); los demás, polite.
  return (
    // z-[70]: por encima de TODO lo que se superpone (drawers, tour, asistente de
    // primer arranque en z-[60]). Un aviso que queda tapado es un aviso perdido.
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed right-4 top-4 z-[70] flex w-[calc(100%-2rem)] max-w-xs flex-col gap-2"
    >
      {items.map((t) => (
        <div
          key={t.id}
          role={t.variant === "error" ? "alert" : "status"}
          className="toast-in pointer-events-auto flex items-start gap-2.5 rounded-lg border border-line bg-surface px-3.5 py-2.5 shadow-[0_4px_24px_rgba(13,45,62,0.12)]"
        >
          <svg viewBox="0 0 12 12" className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${COLOR[t.variant]}`} fill="none">
            <path d={ICON[t.variant]} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p className="flex-1 text-[12.5px] leading-snug text-ink">{t.message}</p>
          <button
            onClick={() => setItems((prev) => prev.filter((x) => x.id !== t.id))}
            aria-label="Cerrar"
            className="-mr-1 -mt-0.5 shrink-0 px-1 text-[14px] leading-none text-ink-3 hover:text-ink"
          >
            &times;
          </button>
        </div>
      ))}
      <style>{`
        @keyframes toastIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        .toast-in { animation: toastIn .2s cubic-bezier(.2,.8,.2,1) both; }
        @media (prefers-reduced-motion: reduce) { .toast-in { animation: none; } }
      `}</style>
    </div>
  );
}
