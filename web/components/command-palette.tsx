"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

// ── Tipos ─────────────────────────────────────────────────────────────────────

type SearchItem = {
  label: string;
  sublabel: string;
  href: string;
  /** Acción local en vez de navegar (ej. reabrir la guía de bienvenida). */
  run?: () => void;
};

type SearchGroup = {
  title: string;
  items: SearchItem[];
};

type SearchResult = {
  groups: SearchGroup[];
};

// ── Constantes ────────────────────────────────────────────────────────────────

const OPEN_EVENT = "open-command-palette";

const PAGES: { label: string; href: string }[] = [
  // Aprobaciones, Promesas y Conciliación viven dentro de Centro de mando (bandeja
  // unificada); no se listan aparte. Sus rutas siguen vivas para deep-links.
  { label: "Centro de mando", href: "/centro" },
  { label: "Resumen", href: "/" },
  { label: "Facturas", href: "/facturas" },
  { label: "Conversaciones", href: "/conversaciones" },
  { label: "Clientes", href: "/clientes" },
  { label: "Prospectos", href: "/prospectos" },
  { label: "Buscar negocios (DENUE)", href: "/prospectos/buscar" },
  { label: "Productos", href: "/productos" },
  { label: "Agenda", href: "/citas" },
  { label: "Tus ayudantes", href: "/ayudantes" },
  { label: "Rutinas", href: "/rutinas" },
  { label: "Importar datos", href: "/importar" },
  { label: "Integraciones", href: "/integraciones" },
  { label: "Organigrama de integraciones", href: "/integraciones?vista=organigrama" },
  { label: "SAT · Bóveda fiscal", href: "/sat" },
  { label: "Proveedor de IA", href: "/proveedor" },
  { label: "Configuración", href: "/configuracion" },
  { label: "API", href: "/desarrolladores" },
  { label: "Perfil", href: "/perfil" },
];

// ── API pública ───────────────────────────────────────────────────────────────

/** Abre el command palette desde cualquier parte del árbol. */
export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fuzzyPages(q: string): SearchGroup | null {
  if (!q.trim()) return null;
  const lower = q.toLowerCase();
  const matches = PAGES.filter((p) => p.label.toLowerCase().includes(lower));
  if (!matches.length) return null;
  return {
    title: "Ir a",
    items: matches.map((p) => ({ label: p.label, sublabel: p.href, href: p.href })),
  };
}

// Acciones locales (no navegan). La guía de bienvenida es one-shot al entrar;
// este es su camino de regreso (lib/onboarding.ts).
const ACTIONS: { label: string; sublabel: string; keywords: string; run: () => void }[] = [];

function fuzzyActions(q: string): SearchGroup | null {
  const lower = q.trim().toLowerCase();
  if (!lower) return null;
  const matches = ACTIONS.filter(
    (a) => a.label.toLowerCase().includes(lower) || a.keywords.includes(lower),
  );
  if (!matches.length) return null;
  return {
    title: "Ayuda",
    items: matches.map((a) => ({ label: a.label, sublabel: a.sublabel, href: "", run: a.run })),
  };
}

// ── Componente ────────────────────────────────────────────────────────────────

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [groups, setGroups] = useState<SearchGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guarda de run-id (como useApi): solo la búsqueda MÁS reciente pinta resultados;
  // una respuesta lenta de una consulta vieja ya no pisa a la nueva.
  const runIdRef = useRef(0);

  // ── Abrir / cerrar ─────────────────────────────────────────────────────────

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setGroups([]);
    setSelectedIdx(0);
  }, []);

  const openPalette = useCallback(() => {
    setOpen(true);
    setQuery("");
    setGroups([]);
    setSelectedIdx(0);
    // autofocus en el siguiente tick
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  // Escucha evento global (para topbar u otros)
  useEffect(() => {
    const handler = () => openPalette();
    window.addEventListener(OPEN_EVENT, handler);
    return () => window.removeEventListener(OPEN_EVENT, handler);
  }, [openPalette]);

  // ⌘K / Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (open) close();
        else openPalette();
      }
      if (e.key === "Escape" && open) {
        close();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, close, openPalette]);

  // ── Fetch con debounce ─────────────────────────────────────────────────────

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    // Cada cambio de query invalida cualquier búsqueda en vuelo.
    const runId = ++runIdRef.current;

    if (query.trim().length < 2) {
      // Solo mostrar páginas y acciones mientras no hay texto suficiente
      const locals = query.trim()
        ? [fuzzyPages(query), fuzzyActions(query)].filter((g): g is SearchGroup => g !== null)
        : [];
      setGroups(locals);
      setSelectedIdx(0);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        // api.search adjunta la sesión local; un fetch crudo puede quedar fuera del
        // workspace y degradarse en silencio a "solo páginas".
        const data: SearchResult = await api.search(query).catch(() => ({ groups: [] }));
        // Llegó tarde: hay una búsqueda más nueva en curso, descarta esta respuesta.
        if (runId !== runIdRef.current) return;
        const locals = [fuzzyPages(query), fuzzyActions(query)].filter(
          (g): g is SearchGroup => g !== null,
        );
        setGroups([...data.groups, ...locals]);
        setSelectedIdx(0);
      } catch {
        if (runId !== runIdRef.current) return;
        const locals = [fuzzyPages(query), fuzzyActions(query)].filter(
          (g): g is SearchGroup => g !== null,
        );
        setGroups(locals);
        setSelectedIdx(0);
      } finally {
        if (runId === runIdRef.current) setLoading(false);
      }
    }, 150);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  // ── Items planos para navegación ───────────────────────────────────────────

  const allItems: SearchItem[] = groups.flatMap((g) => g.items);

  // ── Navegación por teclado ─────────────────────────────────────────────────

  const navigate = useCallback(
    (item: SearchItem) => {
      if (item.run) item.run();
      else router.push(item.href);
      close();
    },
    [router, close],
  );

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, allItems.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = allItems[selectedIdx];
        if (item) navigate(item);
      } else if (e.key === "Tab") {
        // Atrapa el foco dentro del palette: el input es el único destino real
        // (los resultados se recorren con flechas y aria-activedescendant).
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, allItems, selectedIdx, navigate]);

  // ── Render ─────────────────────────────────────────────────────────────────

  if (!open) return null;

  // Índice global acumulado para saber qué ítem está seleccionado
  let runningIdx = 0;

  const hasResults = groups.length > 0;
  const showEmpty = query.trim().length >= 2 && !loading && !hasResults;
  // Id del resultado activo, para que el lector de pantalla anuncie sobre qué está
  // parado sin mover el foco fuera del input (patrón combobox + aria-activedescendant).
  const activeOptionId = hasResults && allItems[selectedIdx] ? `cmd-opt-${selectedIdx}` : undefined;

  return (
    <div
      className="cmd-backdrop fixed inset-0 z-50 flex justify-center bg-ink/25 px-4"
      style={{ paddingTop: "min(20vh, 96px)" }}
      onMouseDown={(e) => {
        // Cierra solo si click directo sobre el backdrop
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Buscador de la consola"
        className="cmd-panel w-full max-w-xl rounded-lg border border-line bg-surface shadow"
        style={{ maxHeight: "60vh", display: "flex", flexDirection: "column" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Input */}
        <div className="flex items-center gap-2.5 border-b border-line px-4 py-3">
          <svg viewBox="0 0 14 14" className="h-3.5 w-3.5 shrink-0 text-ink-3" fill="none">
            <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.3" />
            <path d="m9.5 9.5 2.7 2.7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={hasResults}
            aria-controls="cmd-listbox"
            aria-activedescendant={activeOptionId}
            aria-autocomplete="list"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar cliente, folio, conversación…"
            className="min-w-0 flex-1 bg-transparent text-cuerpo text-ink outline-none placeholder:text-ink-3"
            autoComplete="off"
            spellCheck={false}
          />
          {loading && (
            <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-line border-t-accent" />
          )}
          <kbd className="shrink-0 rounded border border-line bg-panel px-1 text-sello text-ink-3">
            Esc
          </kbd>
        </div>

        {/* Resultados */}
        <div
          id="cmd-listbox"
          role="listbox"
          aria-label="Resultados"
          className="overflow-y-auto"
          style={{ flex: 1 }}
        >
          {/* Estado inicial */}
          {!query.trim() && (
            <p className="px-4 py-6 text-center text-cuerpo text-ink-3">
              Escribe para buscar en todo tu negocio
            </p>
          )}

          {/* Sin resultados */}
          {showEmpty && (
            <p className="px-4 py-6 text-center text-cuerpo text-ink-3">
              Sin resultados para «{query.trim()}»
            </p>
          )}

          {/* Grupos */}
          {hasResults &&
            groups.map((group) => {
              const groupStart = runningIdx;
              runningIdx += group.items.length;

              return (
                <div key={group.title}>
                  <p className="px-4 pb-1 pt-3 text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
                    {group.title}
                  </p>
                  {group.items.map((item, itemIdx) => {
                    const globalIdx = groupStart + itemIdx;
                    const isSelected = globalIdx === selectedIdx;
                    return (
                      <button
                        key={`${group.title}-${globalIdx}`}
                        id={`cmd-opt-${globalIdx}`}
                        role="option"
                        aria-selected={isSelected}
                        tabIndex={-1}
                        type="button"
                        onMouseEnter={() => setSelectedIdx(globalIdx)}
                        onClick={() => navigate(item)}
                        className={`flex w-full items-baseline gap-3 px-4 py-2 text-left transition-colors ${
                          isSelected ? "bg-accent-soft" : "hover:bg-accent-soft/60"
                        }`}
                      >
                        <span
                          className={`flex-1 truncate text-cuerpo ${
                            isSelected ? "text-accent-ink" : "text-ink"
                          }`}
                        >
                          {item.label}
                        </span>
                        {item.sublabel && (
                          <span
                            className={`tnum shrink-0 text-apoyo ${
                              isSelected ? "text-accent-ink/70" : "text-ink-3"
                            }`}
                          >
                            {item.sublabel}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })}

          {/* Separador inferior para evitar que el último ítem quede pegado */}
          {hasResults && <div className="h-2" />}
        </div>
      </div>
    </div>
  );
}
