"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { openCommandPalette } from "@/components/command-palette";
import { api, type WorkspaceInfo } from "@/lib/api";

function Lupa({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 14 14" className={className} fill="none" aria-hidden="true">
      <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.3" />
      <path d="m9.5 9.5 2.7 2.7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

/** La barra superior: de quién es esto, el buscador y el manual. Nada más.
 *  No trae márgenes laterales: los pone el contenedor de `shell.tsx`, para que la
 *  barra y el contenido compartan exactamente los mismos bordes. */
export function Topbar() {
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  // Mientras workspace() resuelve NO se dice "aiuda": placeholder neutro, sin flash.
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    api
      .workspace()
      .then(setWorkspace)
      .catch(() => {})
      .finally(() => setResolved(true));
  }, []);

  const cargando = !resolved && !workspace;
  const businessName = workspace?.business_name ?? (cargando ? "" : "aiuda");

  return (
    <header className="flex h-16 shrink-0 items-center gap-2">
      {/* Menú, solo en teléfono */}
      <button
        aria-label="Abrir menú"
        onClick={() => window.dispatchEvent(new Event("toggle-sidebar"))}
        className="-ml-2.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-fill lg:hidden"
      >
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" aria-hidden="true">
          <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>

      {/* El negocio: su nombre, y un clic lleva a sus datos. */}
      {cargando ? (
        <span className="inline-block h-3 w-28 animate-pulse rounded bg-line" />
      ) : (
        <Link
          href="/configuracion?seccion=negocio"
          title="Ajustes del negocio"
          className="min-w-0 truncate text-cuerpo font-semibold text-ink hover:text-accent-ink"
        >
          {businessName}
        </Link>
      )}

      {/* Buscador: campo completo desde tableta; en teléfono, solo la lupa. */}
      <button
        onClick={openCommandPalette}
        className="ml-auto hidden h-9 w-64 shrink-0 cursor-pointer items-center gap-2.5 rounded-lg px-3 text-left text-ink-3 ring-1 ring-inset ring-line-strong hover:text-ink-2 hover:ring-field sm:flex"
      >
        <Lupa className="h-3.5 w-3.5 shrink-0" />
        <span className="text-cuerpo">Buscar</span>
        <kbd className="ml-auto font-sans text-rotulo">⌘K</kbd>
      </button>
      <button
        onClick={openCommandPalette}
        aria-label="Buscar"
        className="-mr-2.5 ml-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:bg-fill sm:hidden"
      >
        <Lupa className="h-4 w-4" />
      </button>

      {/* El manual viaja DENTRO de aiuda (lo arma web/scripts/manual.mjs desde
          docs/): mandar al dueño a un sitio web para entender por qué algo no
          funciona contradice todo lo demás. `index.html` explícito, para que abra
          igual en el export estático y con `next dev`; y misma ventana, porque en
          la app de escritorio un target="_blank" no abre nada. En teléfono vive al
          pie del menú. */}
      <a
        href="/manual/index.html"
        className="hidden shrink-0 pl-4 text-cuerpo font-medium text-ink-2 hover:text-ink sm:inline"
      >
        Manual
      </a>
    </header>
  );
}
