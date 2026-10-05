"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAyudantes } from "@/lib/ayudantes-store";
import { type Destino, dentroDe, destinos, oficiosDe } from "@/lib/sections";

// ── Tipos ─────────────────────────────────────────────────────────────────────

type SearchItem = {
  label: string;
  sublabel: string;
  href: string;
  /** Sale de la consola (el manual): navegación completa, no del router. */
  fuera?: boolean;
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

// ── API pública ───────────────────────────────────────────────────────────────

/** Abre el command palette desde cualquier parte del árbol. */
export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Minúsculas y sin acentos: "telefono" encuentra "Teléfono y equipo". */
const plano = (t: string) =>
  t
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");

/** Los destinos de la consola que casan con lo escrito. La lista y los nombres
 *  son los de lib/sections.ts, los mismos del menú. Sin texto, van todos: el
 *  buscador abierto es también el mapa de la consola. */
function irA(q: string, lista: Destino[]): SearchGroup | null {
  const palabras = plano(q).split(/\s+/).filter(Boolean);
  const matches = lista.filter((d) => {
    const texto = plano(`${d.label} ${dentroDe(d)} ${d.claves ?? ""}`);
    return palabras.every((w) => texto.includes(w));
  });
  if (!matches.length) return null;
  // Primero los que casan por su nombre; después los que casan por lo que traen.
  const porNombre = (d: Destino) => (palabras.length && plano(d.label).includes(palabras[0]) ? 0 : 1);
  matches.sort((x, y) => porNombre(x) - porNombre(y));
  return {
    title: "Ir a",
    items: matches.map((d) => ({
      label: d.label,
      sublabel: dentroDe(d),
      href: d.href,
      fuera: d.fuera,
    })),
  };
}


// ── Componente ────────────────────────────────────────────────────────────────

export function CommandPalette() {
  const router = useRouter();
  const { ayudantes } = useAyudantes();
  // Productos y Agenda se listan con la misma condición que en el menú. Se guarda
  // como texto para que la lista no cambie de identidad en cada render.
  const oficios = oficiosDe(ayudantes).join(",");
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

    const lista = destinos(oficiosDe(ayudantes));
    const local = () => {
      const g = irA(query, lista);
      return g ? [g] : [];
    };

    if (query.trim().length < 2) {
      // Sin texto suficiente para preguntarle al servidor: solo los destinos.
      setGroups(local());
      setSelectedIdx(0);
      return;
    }

    // Los destinos casan al instante; lo del servidor llega un momento después
    // y se acomoda debajo sin borrar lo que ya estaba.
    setGroups((prev) => [...local(), ...prev.filter((g) => g.title !== "Ir a")]);
    setSelectedIdx(0);

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        // api.search adjunta la sesión local; un fetch crudo puede quedar fuera del
        // workspace y degradarse en silencio a "solo páginas".
        const data: SearchResult = await api.search(query).catch(() => ({ groups: [] }));
        // Llegó tarde: hay una búsqueda más nueva en curso, descarta esta respuesta.
        if (runId !== runIdRef.current) return;
        // Los destinos van primero: quien escribe "pagos" quiere la pantalla.
        // Los títulos y las rutas ya vienen del servidor con los nombres de la consola.
        setGroups([...local(), ...data.groups]);
        setSelectedIdx(0);
      } finally {
        if (runId === runIdRef.current) setLoading(false);
      }
    }, 150);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // `oficios` resume a `ayudantes`: es lo único de ellos que cambia la lista.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, oficios, open]);

  // ── Items planos para navegación ───────────────────────────────────────────

  const allItems: SearchItem[] = groups.flatMap((g) => g.items);

  // ── Navegación por teclado ─────────────────────────────────────────────────

  const navigate = useCallback(
    (item: SearchItem) => {
      // El manual es una página aparte, fuera del router de la consola.
      if (item.fuera) window.location.href = item.href;
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

  // Con flechas, el resultado activo se mantiene a la vista (la lista de destinos
  // ya no cabe entera en el panel).
  useEffect(() => {
    if (!open) return;
    document.getElementById(`cmd-opt-${selectedIdx}`)?.scrollIntoView({ block: "nearest" });
  }, [open, selectedIdx]);

  // ── Render ─────────────────────────────────────────────────────────────────

  if (!open) return null;

  // Índice global acumulado para saber qué ítem está seleccionado
  let runningIdx = 0;

  const hasResults = groups.length > 0;
  const showEmpty = query.trim().length > 0 && !loading && !hasResults;
  // Id del resultado activo, para que el lector de pantalla anuncie sobre qué está
  // parado sin mover el foco fuera del input (patrón combobox + aria-activedescendant).
  const activeOptionId = hasResults && allItems[selectedIdx] ? `cmd-opt-${selectedIdx}` : undefined;

  return (
    <div
      className="cmd-backdrop fixed inset-0 z-50 flex items-start justify-center bg-ink/25 px-4"
      style={{ paddingTop: "min(16vh, 96px)" }}
      onMouseDown={(e) => {
        // Cierra solo si click directo sobre el backdrop
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Buscador de la consola"
        className="cmd-panel flex w-full max-w-xl flex-col overflow-hidden rounded-2xl bg-surface shadow-lg"
        style={{ maxHeight: "min(70vh, 560px)" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Input */}
        <div className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-5">
          <svg viewBox="0 0 14 14" className="h-4 w-4 shrink-0 text-ink-3" fill="none" aria-hidden="true">
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
            placeholder="Buscar pantalla, cliente o folio"
            className="h-full min-w-0 flex-1 bg-transparent text-cuerpo text-ink outline-none placeholder:text-ink-3 focus-visible:shadow-none"
            autoComplete="off"
            spellCheck={false}
          />
          {loading && (
            <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-line border-t-accent" />
          )}
          <kbd className="shrink-0 font-sans text-rotulo text-ink-3">Esc</kbd>
        </div>

        {/* Resultados */}
        <div
          id="cmd-listbox"
          role="listbox"
          aria-label="Resultados"
          className="overflow-y-auto"
          style={{ flex: 1 }}
        >
          {/* Sin resultados */}
          {showEmpty && (
            <p className="px-5 py-8 text-center text-cuerpo text-ink-3">
              Nada con «{query.trim()}»
            </p>
          )}

          {/* Grupos */}
          {hasResults &&
            groups.map((group) => {
              const groupStart = runningIdx;
              runningIdx += group.items.length;

              return (
                <div key={group.title}>
                  <p className="eyebrow px-5 pb-1.5 pt-4">
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
                        className={`flex w-full items-baseline gap-3 px-5 py-2 text-left ${
                          isSelected ? "bg-fill" : ""
                        }`}
                      >
                        <span
                          className={`flex-1 truncate text-cuerpo text-ink ${
                            isSelected ? "font-medium" : ""
                          }`}
                        >
                          {item.label}
                        </span>
                        {item.sublabel && (
                          <span
                            className="tnum shrink-0 text-apoyo text-ink-3"
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
