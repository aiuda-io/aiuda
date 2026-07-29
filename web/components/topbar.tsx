"use client";

import { useEffect, useRef, useState } from "react";
import { openCommandPalette } from "@/components/command-palette";
import { api, type WorkspaceInfo } from "@/lib/api";

export function Topbar() {
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  // Mientras workspace() resuelve NO se dice "aiuda": placeholder neutro, sin flash.
  const [resolved, setResolved] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    api
      .workspace()
      .then(setWorkspace)
      .catch(() => {})
      .finally(() => setResolved(true));
  }, []);

  // Escape cierra el menú y devuelve el foco a su botón (mismo patrón que la
  // paleta de comandos y el picker de aiuditas).
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
        menuTriggerRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  // Mientras resuelve, nada de defaults que parpadeen ("aiuda" no es tu negocio).
  const cargando = !resolved && !workspace;
  const businessName = workspace?.business_name ?? (cargando ? "" : "aiuda");

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-panel/70 px-5">
      {/* Menú móvil */}
      <button
        aria-label="Abrir menú"
        onClick={() => window.dispatchEvent(new Event("toggle-sidebar"))}
        className="-ml-1 rounded-md p-1.5 text-ink-2 transition-colors hover:bg-line/50 lg:hidden"
      >
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
          <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>

      {/* Cuenta del negocio */}
      <div className="relative">
        <button
          ref={menuTriggerRef}
          onClick={() => setMenuOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          className="flex items-center gap-2 rounded-md px-2 py-1 text-[13px] font-medium text-ink transition-colors hover:bg-line/50"
        >
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-accent text-[10px] font-semibold text-surface">
            {businessName[0]?.toUpperCase() ?? ""}
          </span>
          {/* Truncado con tope: en 390px el header debe caber en UNA línea. */}
          {cargando ? (
            <span className="inline-block h-3 w-24 animate-pulse rounded bg-line" />
          ) : (
            <span className="max-w-[8.5rem] truncate sm:max-w-[16rem]">{businessName}</span>
          )}
          <svg viewBox="0 0 12 12" className="h-3 w-3 shrink-0 text-ink-3" fill="none">
            <path d="m3 4.5 3 3 3-3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        </button>
        {menuOpen && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
            <div
              role="menu"
              className="absolute left-0 top-full z-50 mt-1 w-56 overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-lg"
            >
              <div className="border-b border-line/60 px-3 py-2">
                <p className="truncate text-[12.5px] font-medium text-ink">{businessName}</p>
                <p className="truncate text-[11px] text-ink-3">Todo corre en esta computadora</p>
              </div>
              <a
                href="/configuracion"
                role="menuitem"
                className="block px-3 py-1.5 text-[12.5px] text-ink-2 transition-colors hover:bg-line/40 hover:text-ink"
              >
                Configuración del negocio
              </a>
              <a
                href="/perfil"
                role="menuitem"
                className="block px-3 py-1.5 text-[12.5px] text-ink-2 transition-colors hover:bg-line/40 hover:text-ink"
              >
                Datos del negocio
              </a>
            </div>
          </>
        )}
      </div>

      <span className="shrink-0 rounded border border-line px-1.5 py-px text-[10.5px] font-medium uppercase tracking-wide text-ink-3">
        local
      </span>

      {/* Búsqueda: campo completo en ≥sm; en móvil, solo la lupa (mismo ⌘K). */}
      <button
        onClick={openCommandPalette}
        className="ml-auto hidden w-72 cursor-pointer items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1.5 text-left text-ink-3 transition-colors hover:border-line-strong sm:flex"
      >
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" fill="none">
          <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.3" />
          <path d="m9.5 9.5 2.7 2.7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
        <span className="text-[12.5px]">Buscar cliente, folio…</span>
        <kbd className="ml-auto rounded border border-line bg-panel px-1 text-[10px] text-ink-3">
          ⌘K
        </kbd>
      </button>
      <button
        onClick={openCommandPalette}
        aria-label="Buscar"
        className="ml-auto shrink-0 rounded-md p-1.5 text-ink-2 transition-colors hover:bg-line/50 sm:hidden"
      >
        <svg viewBox="0 0 14 14" className="h-4 w-4" fill="none">
          <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.3" />
          <path d="m9.5 9.5 2.7 2.7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      </button>

      {/* El manual viaja DENTRO de aiuda (lo arma web/scripts/manual.mjs desde
          docs/): mandar al dueño a un sitio web para entender por qué algo no
          funciona contradice todo lo demás. Dos detalles que parecen manías:
          `index.html` explícito, para que abra igual en el export estático y con
          `next dev`; y misma ventana, porque en la app de escritorio un
          target="_blank" no abre nada y el enlace se sentiría muerto. */}
      <a
        href="/manual/index.html"
        className="hidden text-[12.5px] font-medium text-ink-2 transition-colors hover:text-ink sm:inline"
      >
        Manual
      </a>
    </header>
  );
}
