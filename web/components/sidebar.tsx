"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAyudantes } from "@/lib/ayudantes-store";
import { menu, oficiosDe, puertaDe } from "@/lib/sections";

/** El menú: una lista plana, sin grupos ni modos. Los renglones y sus nombres
 *  salen de lib/sections.ts, igual que los del buscador.
 *  Eventos: "aiuda-escritura" y "agents-changed" recuentan el globo;
 *  "toggle-sidebar" lo abre y lo cierra en teléfono. */

// Iconos de línea, 18px, un solo trazo. Callados: acompañan la palabra, no la
// reemplazan (el menú nunca se colapsa a solo iconos).
function svg(children: ReactNode) {
  return (
    <svg
      viewBox="0 0 18 18"
      className="h-[18px] w-[18px] shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.35"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}
const ICONS: Record<string, ReactNode> = {
  hoy: svg(<><path d="M3 9.5h2.6l.9 1.8h5l.9-1.8H15" /><path d="M3.4 9.5 4.8 4.2h8.4L14.6 9.5V14H3.4z" /></>),
  cartera: svg(<><path d="M5 2.6h5l3 3V15.4H5z" /><path d="M10 2.6v3h3" /><path d="M7.4 9.4h3.2M7.4 12h3.2" /></>),
  mensajes: svg(<path d="M3 4.4h12v7.4H8.2L5 14.2v-2.4H3z" />),
  clientes: svg(<><circle cx="6.6" cy="6.2" r="2.1" /><path d="M2.7 14c0-2.1 1.7-3.4 3.9-3.4S10.5 12 10.5 14" /><path d="M11.6 5.3a1.9 1.9 0 0 1 0 3.7M12.4 13.6c.9-.4 2.6-.9 2.6-2.5 0-1-.8-1.8-1.8-2.1" /></>),
  ayudantes: svg(<><rect x="4" y="5.6" width="10" height="8.2" rx="2.4" /><path d="M9 5.6V3.4" /><path d="M7.2 9.4v.9M10.8 9.4v.9" /></>),
  productos: svg(<><path d="M9 2.7 15 5.6v6.8L9 15.3 3 12.4V5.6z" /><path d="M3 5.6 9 8.5l6-2.9M9 8.5v6.8" /></>),
  agenda: svg(<><rect x="3" y="4.2" width="12" height="10.6" rx="1.6" /><path d="M3 7.6h12M6 2.6v2.6M12 2.6v2.6" /></>),
  ajustes: svg(<><path d="M3 5.6h7.2M13.4 5.6H15M3 12.4h1.6M7.8 12.4H15" /><circle cx="11.8" cy="5.6" r="1.6" /><circle cx="6.2" cy="12.4" r="1.6" /></>),
};

export function Sidebar() {
  const pathname = usePathname();
  const [pending, setPending] = useState<number | null>(null);
  const { ayudantes } = useAyudantes();
  const [mobileOpen, setMobileOpen] = useState(false);

  const load = useCallback(() => {
    // El mismo número que el encabezado "Por aprobar (n)" de Hoy: lo cuenta el
    // servidor (`espera_tu_ok`), no esta pantalla.
    api.cartera().then((c) => setPending(c.espera_tu_ok)).catch(() => setPending(null));
  }, []);

  useEffect(() => {
    load();
    setMobileOpen(false);
  }, [load, pathname]);

  useEffect(() => {
    const refresh = () => load();
    const toggle = () => setMobileOpen((v) => !v);
    // Tras una escritura el globo se vuelve a contar. Con un respiro: el server
    // confirma el cambio justo después de responder, y varias escrituras seguidas
    // se juntan en una sola consulta.
    let espera: ReturnType<typeof setTimeout> | undefined;
    const trasEscritura = () => {
      clearTimeout(espera);
      espera = setTimeout(load, 600);
    };
    window.addEventListener("agents-changed", refresh);
    window.addEventListener("aiuda-escritura", trasEscritura);
    window.addEventListener("toggle-sidebar", toggle);
    return () => {
      clearTimeout(espera);
      window.removeEventListener("agents-changed", refresh);
      window.removeEventListener("aiuda-escritura", trasEscritura);
      window.removeEventListener("toggle-sidebar", toggle);
    };
  }, [load]);

  // En teléfono el menú es un panel encima: Escape lo cierra.
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMobileOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  // Productos y Agenda solo existen si hay un ayudante que haga ese trabajo.
  const items = menu(oficiosDe(ayudantes));
  // La puerta encendida: también en rutas hijas, pestañas y redirecciones.
  const puerta = puertaDe(pathname);

  const nav = (
    <>
      <div className="flex h-16 items-center px-6">
        <Link href="/" aria-label="aiuda, ir a Hoy" className="flex items-baseline gap-1.5">
          <span className="wordmark">aiuda</span>
          <span className="h-1.5 w-1.5 rounded-full bg-brand" />
        </Link>
      </div>

      <nav aria-label="Menú" className="flex-1 overflow-y-auto px-3 pb-4 pt-3">
        <ul className="space-y-0.5">
          {items.map((it) => {
            const active = puerta === it.href;
            const globo = it.href === "/" && pending != null && pending > 0 ? pending : null;
            return (
              <li key={it.href}>
                <Link
                  href={it.href}
                  aria-current={active ? "page" : undefined}
                  className={`group flex h-10 items-center gap-3 rounded-lg px-3 text-cuerpo ${
                    active
                      ? "bg-fill font-semibold text-ink"
                      : "font-medium text-ink-2 hover:bg-fill/60 hover:text-ink"
                  }`}
                >
                  <span className={active ? "text-ink" : "text-ink-3 group-hover:text-ink-2"}>
                    {ICONS[it.icono ?? ""]}
                  </span>
                  <span className="flex-1 truncate">{it.label}</span>
                  {globo != null && (
                    <span
                      className="tnum text-apoyo font-semibold text-accent-ink"
                      aria-label={`${globo} por aprobar`}
                    >
                      {globo}
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );

  return (
    <>
      {/* Escritorio: una columna fija sobre el mismo lienzo que el contenido. La
          separa una raya fina, no un cambio de fondo. */}
      <aside className="sticky top-[var(--franja,0px)] z-20 hidden h-[calc(100vh-var(--franja,0px))] w-60 shrink-0 flex-col border-r border-line lg:flex">
        {nav}
      </aside>

      {/* Teléfono: el mismo menú, encima. Cabe entero en una pantalla. */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Cerrar menú"
            onClick={() => setMobileOpen(false)}
            className="cmd-backdrop absolute inset-0 bg-ink/25"
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[82vw] flex-col bg-bg shadow-lg">
            {nav}
            {/* En teléfono la barra superior no tiene espacio para el manual. */}
            <a
              href="/manual/index.html"
              className="mx-3 mb-4 flex h-10 items-center rounded-lg px-3 text-cuerpo font-medium text-ink-2 hover:bg-fill/60 hover:text-ink"
            >
              Manual
            </a>
          </aside>
        </div>
      )}
    </>
  );
}
