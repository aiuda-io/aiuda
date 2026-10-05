"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAyudantes } from "@/lib/ayudantes-store";
import { Avatar } from "@/components/avatar";
import { normalizeAppearance } from "@/lib/look";

/** Navegación por TRABAJO (no por agente): un icono por item.
 *  Estilo Supabase: control Expandido/Colapsado/Hover.
 *  Eventos: "agents-changed" refresca; "toggle-sidebar" abre/cierra en móvil. */

type Mode = "expanded" | "collapsed" | "hover";
const MODE_LABEL: Record<Mode, string> = {
  expanded: "Expandido",
  collapsed: "Colapsado",
  hover: "Al pasar el mouse",
};

// --- Iconos de línea (18px), monocromáticos ---
function svg(children: ReactNode) {
  return (
    <svg
      viewBox="0 0 18 18"
      className="h-[18px] w-[18px] shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}
const ICONS: Record<string, ReactNode> = {
  home: svg(<><path d="M3 8.2 9 3l6 5.2" /><path d="M4.8 7.5V15h8.4V7.5" /></>),
  inbox: svg(<><path d="M3 9.5h2.6l.9 1.8h5l.9-1.8H15" /><path d="M3.4 9.5 4.8 4.2h8.4L14.6 9.5V14H3.4z" /></>),
  doc: svg(<><path d="M5 2.6h5l3 3V15.4H5z" /><path d="M10 2.6v3h3" /></>),
  calCheck: svg(<><rect x="3" y="4.2" width="12" height="10.6" rx="1.6" /><path d="M3 7.6h12M6 2.6v2.6M12 2.6v2.6" /><path d="m6.6 11 1.5 1.5L11 9.6" /></>),
  chat: svg(<><path d="M3 4.4h12v7.4H8.2L5 14.2v-2.4H3z" /></>),
  users: svg(<><circle cx="6.6" cy="6.2" r="2.1" /><path d="M2.7 14c0-2.1 1.7-3.4 3.9-3.4S10.5 12 10.5 14" /><path d="M11.6 5.3a1.9 1.9 0 0 1 0 3.7M12.4 13.6c.9-.4 2.6-.9 2.6-2.5 0-1-.8-1.8-1.8-2.1" /></>),
  box: svg(<><path d="M9 2.7 15 5.6v6.8L9 15.3 3 12.4V5.6z" /><path d="M3 5.6 9 8.5l6-2.9M9 8.5v6.8" /></>),
  calendar: svg(<><rect x="3" y="4.2" width="12" height="10.6" rx="1.6" /><path d="M3 7.6h12M6 2.6v2.6M12 2.6v2.6" /></>),
  target: svg(<><circle cx="9" cy="9" r="5.4" /><circle cx="9" cy="9" r="2.2" /></>),
  upload: svg(<><path d="M9 11.4V3.4M5.7 6.7 9 3.4l3.3 3.3" /><path d="M3.6 12.4V15h10.8v-2.6" /></>),
  share: svg(<><circle cx="5" cy="9" r="1.7" /><circle cx="13" cy="4.6" r="1.7" /><circle cx="13" cy="13.4" r="1.7" /><path d="m6.5 8.2 5-2.6M6.5 9.8l5 2.6" /></>),
  plug: svg(<><path d="M7 2.6v2.8M11 2.6v2.8" /><path d="M5.6 5.4h6.8V9a3.4 3.4 0 0 1-6.8 0z" /><path d="M9 12.4v3" /></>),
  gear: svg(<><circle cx="9" cy="9" r="2.2" /><path d="M9 2.7v2.1M9 13.2v2.1M2.7 9h2.1M13.2 9h2.1M4.5 4.5l1.5 1.5M12 12l1.5 1.5M13.5 4.5 12 6M6 12l-1.5 1.5" /></>),
  key: svg(<><circle cx="6" cy="9" r="2.9" /><path d="M8.7 8.4h6.3M13.2 8.4v2M15 8.4v1.6" /></>),
  chart: svg(<><path d="M3 14.6V3.4M3 14.6h12" /><path d="M6 12V9M9 12V6M12 12V8" /></>),
  team: svg(<><circle cx="6.4" cy="6.6" r="2" /><circle cx="11.6" cy="6.6" r="2" /><path d="M2.8 13.6c0-1.9 1.6-3 3.6-3 .9 0 1.7.2 2.3.7M9.3 11.3c.6-.5 1.4-.7 2.3-.7 2 0 3.6 1.1 3.6 3" /></>),
  panel: svg(<><rect x="3" y="3.5" width="12" height="11" rx="1.6" /><path d="M7 3.5v11" /></>),
  reconcile: svg(<><path d="M3 6.6h9M9.6 4.2 12 6.6 9.6 9" /><path d="M15 11.4H6M8.4 9l-2.4 2.4L8.4 13.8" /></>),
  phone: svg(<><rect x="5.6" y="2.4" width="6.8" height="13.2" rx="1.6" /><path d="M7.8 4.2h2.4" /><path d="M9 13.4h.01" /></>),
  cpu: svg(<><rect x="5" y="5" width="8" height="8" rx="1.4" /><path d="M7.4 5V3M10.6 5V3M7.4 15v-2M10.6 15v-2M5 7.4H3M5 10.6H3M15 7.4h-2M15 10.6h-2" /></>),
  repeat: svg(<><path d="M4 7.2A5 5 0 0 1 13.6 6.4" /><path d="M13.8 3.4v3h-3" /><path d="M14 10.8A5 5 0 0 1 4.4 11.6" /><path d="M4.2 14.6v-3h3" /></>),
  dot: svg(<circle cx="9" cy="9" r="2.4" fill="currentColor" stroke="none" />),
};
const ICON_FOR: Record<string, string> = {
  "/": "home",
  "/centro": "panel",
  "/rutinas": "repeat",
  "/facturas": "doc",
  "/promesas": "calCheck",
  "/conversaciones": "chat",
  "/clientes": "users",
  "/productos": "box",
  "/citas": "calendar",
  "/conciliacion": "reconcile",
  "/importar": "upload",
  "/integraciones": "plug",
  "/proveedor": "cpu",
  "/aparatos": "phone",
  "/configuracion": "gear",
};
const iconFor = (href: string): ReactNode => ICONS[ICON_FOR[href] ?? "dot"];

// Vistas subsumidas por otras superficies: se ocultan de la nav derivada para no
// duplicar. Las rutas siguen vivas (p.ej. /aprobaciones redirige al Centro de mando).
// /aprobaciones vive dentro de Centro de mando. /conciliacion y /promesas SÍ vuelven al
// menú: son 899 y 200 líneas de pantalla que el dueño no podía alcanzar desde ningún
// lado (solo por un enlace del Resumen), y son justo el trabajo que sus ayudantes hacen
// contra sus integraciones. "Consolidado en el Centro" acabó significando "escondido".
const CONSOLIDADO = new Set(["/aprobaciones"]);

// El menú muestra lo que el dueño puede DECIDIR, en sus palabras. "Proveedor de IA"
// era jerga: lo que él eligió es qué inteligencia usa su negocio.
const PLATFORM: { href: string; label: string }[] = [
  { href: "/configuracion", label: "General" },
  { href: "/integraciones", label: "Integraciones" },
  { href: "/proveedor", label: "Tu IA" },
  { href: "/importar", label: "Importar datos" },
  { href: "/aparatos", label: "Tus aparatos" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [pending, setPending] = useState<number | null>(null);
  const { ayudantes, loading: cargandoAyudantes } = useAyudantes();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("expanded");
  const [hovering, setHovering] = useState(false);
  const [controlOpen, setControlOpen] = useState(false);

  // Preferencia leída tras montar (evita mismatch de hidratación SSR/cliente).
  useEffect(() => {
    const saved = window.localStorage.getItem("aiuda-sidebar-mode");
    if (saved === "expanded" || saved === "collapsed" || saved === "hover") setMode(saved);
  }, []);
  function pickMode(m: Mode) {
    setMode(m);
    setControlOpen(false);
    try {
      window.localStorage.setItem("aiuda-sidebar-mode", m);
    } catch {
      /* sin localStorage: no pasa nada */
    }
  }

  const load = useCallback(() => {
    api.cartera().then((c) => setPending(c.pending_approvals)).catch(() => setPending(null));
  }, []);

  useEffect(() => {
    load();
    setMobileOpen(false);
  }, [load, pathname]);

  useEffect(() => {
    const refresh = () => load();
    const toggle = () => setMobileOpen((v) => !v);
    window.addEventListener("agents-changed", refresh);
    window.addEventListener("toggle-sidebar", toggle);
    return () => {
      window.removeEventListener("agents-changed", refresh);
      window.removeEventListener("toggle-sidebar", toggle);
    };
  }, [load]);

  // Los datos del NEGOCIO están siempre: son suyos, no de un ayudante. Antes esta lista
  // se derivaba de un roster de agentes de fábrica, así que si esa petición fallaba (o si
  // el dueño no tenía "activado" al agente correcto) su propia cartera desaparecía del
  // menú. CONSOLIDADO en Centro de mando: /aprobaciones, /conciliacion y /promesas siguen
  // vivas como deep-links, solo no repiten en el menú.
  const dataItems = useMemo(
    () =>
      [
        { href: "/facturas", label: "Facturas" },
        { href: "/conciliacion", label: "Conciliación" },
        { href: "/promesas", label: "Promesas de pago" },
        { href: "/conversaciones", label: "Conversaciones" },
        { href: "/clientes", label: "Clientes" },
      ].filter((it) => !CONSOLIDADO.has(it.href)),
    [],
  );

  const isActive = (href: string) =>
    pathname === href || (href !== "/" && pathname.startsWith(href + "/"));

  const expanded = mode === "expanded" || (mode === "hover" && hovering);

  function renderItem(
    opts: { href: string; label: string; owner?: string; badge?: number | null },
    exp: boolean,
  ) {
    const { href, label, badge } = opts;
    const active = isActive(href);
    return (
      <Link
        href={href}
        title={!exp ? label : undefined}
        aria-current={active ? "page" : undefined}
        className={`group flex h-9 items-center rounded-lg text-cuerpo ${
          exp ? "gap-3 px-2.5" : "justify-center px-0"
        } ${
          active
            ? "bg-surface font-semibold text-ink shadow-sm"
            : "font-medium text-ink-2 hover:bg-fill-strong/70 hover:text-ink"
        }`}
      >
        <span
          className={`relative flex shrink-0 items-center ${
            active ? "text-accent" : "text-ink-3 group-hover:text-ink-2"
          }`}
        >
          {iconFor(href)}
          {!exp && badge != null && badge > 0 && (
            <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-accent ring-1 ring-panel" />
          )}
        </span>
        {exp && <span className="flex-1 truncate">{label}</span>}
        {exp && badge != null && badge > 0 && (
          <span className="tnum text-apoyo font-semibold text-accent-ink">{badge}</span>
        )}
      </Link>
    );
  }

  const renderDivider = (label: string, exp: boolean) =>
    exp ? (
      <p className="eyebrow mb-1.5 px-2.5">{label}</p>
    ) : (
      <div className="mx-2 my-2 h-px bg-line-strong/60" />
    );

  function renderNav(exp: boolean, withControl: boolean) {
    return (
      <>
        <div className={`flex h-14 items-center ${exp ? "px-[22px]" : "justify-center"}`}>
          <Link href="/" title="aiuda" className="flex items-baseline gap-1.5">
            {exp && (
              <span className="wordmark">aiuda</span>
            )}
            <span className="h-1.5 w-1.5 rounded-full bg-brand" />
          </Link>
        </div>

        <nav className={`flex flex-1 flex-col overflow-y-auto pb-4 pt-2 ${exp ? "gap-5 px-3" : "gap-1 px-2"}`}>
          <ul className="space-y-px">
            <li>{renderItem({ href: "/centro", label: "Centro de mando", badge: pending }, exp)}</li>
            <li>{renderItem({ href: "/", label: "Resumen" }, exp)}</li>
            <li>{renderItem({ href: "/actividad", label: "Actividad" }, exp)}</li>
          </ul>

          {dataItems.length > 0 && (
            <div>
              {renderDivider("Tu negocio", exp)}
              <ul className="space-y-px">
                {dataItems.map((it) => (
                  <li key={it.href}>{renderItem({ href: it.href, label: it.label }, exp)}</li>
                ))}
              </ul>
            </div>
          )}

          <div>
            {renderDivider("Tu equipo", exp)}
            {exp ? (
              <>
                <div className="flex flex-wrap items-center gap-2.5 px-2.5 pt-1">
                  {ayudantes.map((a) => (
                    <Link
                      key={a.id}
                      href={`/ayudantes/detalle?id=${a.id}`}
                      title={`${a.name} · ${Object.keys(a.aiuditas).length} aiuditas`}
                      className={`rounded-full ring-2 ring-offset-2 ring-offset-panel hover:opacity-80 ${
                        isActive(`/ayudantes/detalle?id=${a.id}`) ? "ring-accent" : "ring-transparent"
                      }`}
                    >
                      <Avatar name={a.name} size={28} {...normalizeAppearance(a.appearance)} />
                    </Link>
                  ))}
                  <Link
                    href="/ayudantes"
                    title="Crear un ayudante"
                    className="flex h-7 w-7 items-center justify-center rounded-full bg-fill-strong text-cuerpo font-medium text-ink-2 hover:bg-line-strong hover:text-ink"
                  >
                    +
                  </Link>
                </div>
                <Link
                  href="/ayudantes"
                  className={`mb-1 mt-2.5 block px-2.5 text-apoyo ${
                    isActive("/ayudantes")
                      ? "font-semibold text-ink"
                      : "text-ink-3 hover:text-ink"
                  }`}
                >
                  {cargandoAyudantes
                    ? "…"
                    : ayudantes.length === 0
                      ? "Crear tu primer ayudante"
                      : `${ayudantes.length} ayudante${ayudantes.length === 1 ? "" : "s"} · ver equipo`}
                </Link>
              </>
            ) : (
              <Link
                href="/ayudantes"
                title={`Tu equipo · ${ayudantes.length} ayudantes`}
                className={`flex h-9 items-center justify-center rounded-lg ${
                  isActive("/ayudantes")
                    ? "bg-surface text-accent shadow-sm"
                    : "text-ink-3 hover:bg-fill-strong/70 hover:text-ink"
                }`}
              >
                {ICONS.team}
              </Link>
            )}
            <ul className="mt-1 space-y-px">
              <li>{renderItem({ href: "/rutinas", label: "Rutinas" }, exp)}</li>
            </ul>
          </div>

          <div>
            {renderDivider("Configuración", exp)}
            <ul className="space-y-px">
              {PLATFORM.map((it) => (
                <li key={it.href}>{renderItem(it, exp)}</li>
              ))}
            </ul>
          </div>
        </nav>

        {withControl && (
          <div className="relative px-3 pb-1">
            {controlOpen && (
              <>
                <button
                  className="fixed inset-0 z-30 cursor-default"
                  aria-label="Cerrar"
                  onClick={() => setControlOpen(false)}
                />
                <div className="absolute bottom-full left-3 z-40 mb-1 w-52 rounded-xl bg-surface p-1.5 shadow-md">
                  <p className="eyebrow px-2 py-1">
                    Control del menú
                  </p>
                  {(["expanded", "collapsed", "hover"] as Mode[]).map((m) => (
                    <button
                      key={m}
                      onClick={() => pickMode(m)}
                      className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left text-cuerpo text-ink-2 hover:bg-fill hover:text-ink"
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${mode === m ? "bg-accent" : "border border-line-strong"}`}
                      />
                      {MODE_LABEL[m]}
                    </button>
                  ))}
                </div>
              </>
            )}
            <button
              onClick={() => setControlOpen((v) => !v)}
              title="Control del menú"
              className={`flex h-9 items-center rounded-lg text-apoyo text-ink-3 hover:bg-fill-strong/70 hover:text-ink ${
                exp ? "w-full gap-3 px-2.5" : "w-full justify-center"
              }`}
            >
              {ICONS.panel}
              {exp && <span className="truncate">{MODE_LABEL[mode]}</span>}
            </button>
          </div>
        )}

        {exp && (
          <a
            href="https://hanova.mx"
            className="flex items-center gap-2 px-[22px] pb-4 pt-1 text-rotulo text-ink-3 hover:text-ink"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/hanova-icon-blue.svg" alt="" className="h-3 w-3 opacity-60 grayscale" />
            Un proyecto de Hanova Consulting
          </a>
        )}
      </>
    );
  }

  return (
    <>
      {/* Escritorio: ancho reservado por modo; en hover, el panel expandido flota. */}
      <aside
        onMouseEnter={() => mode === "hover" && setHovering(true)}
        onMouseLeave={() => setHovering(false)}
        className={`sticky top-0 z-20 hidden h-screen shrink-0 lg:block ${
          mode === "expanded" ? "w-60" : "w-14"
        }`}
      >
        <div
          className={`flex h-screen flex-col bg-panel ${expanded ? "w-60" : "w-14"} ${
            mode === "hover" && hovering ? "absolute left-0 top-0 z-40 shadow-lg" : ""
          }`}
        >
          {renderNav(expanded, true)}
        </div>
      </aside>

      {/* Móvil: drawer siempre expandido */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Cerrar menú"
            onClick={() => setMobileOpen(false)}
            className="absolute inset-0 bg-ink/20"
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col bg-panel shadow-lg">
            {renderNav(true, false)}
          </aside>
        </div>
      )}
    </>
  );
}
