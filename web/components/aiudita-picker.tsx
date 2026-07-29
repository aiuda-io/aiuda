"use client";

import { useEffect, useRef, useState } from "react";
import type { AiuditaConfig, AiuditasCatalog, AiuditaSpec } from "@/lib/api";
import { AiuditaIcon, aiuditaTipo } from "@/components/aiudita-icon";
import { removeAiudita, setAiudita } from "@/lib/ayudantes-store";
import { perfilColor } from "@/lib/perfiles";

/**
 * Picker de aiuditas estilo paleta de comandos: busca, filtra por perfil o por "solo listas",
 * y agrega/quita con un toque. Reemplaza el muro de grillas repetido por cada perfil. Se
 * alimenta del catálogo y muta el store (setAiudita/removeAiudita); como el ayudante es
 * reactivo, `activos` se actualiza en vivo y el + cambia a check sin recargar. Cierra con Esc
 * o clic fuera; la animación respeta prefers-reduced-motion (clases cmd-* de globals.css).
 */
export function AiuditaPicker({
  ayudanteId,
  catalog,
  activos,
  onClose,
}: {
  ayudanteId: string;
  catalog: AiuditasCatalog;
  activos: Record<string, AiuditaConfig>;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  // "all" | "listas" | slug de perfil
  const [filtro, setFiltro] = useState<string>("all");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Perfiles con al menos una aiudita (para los chips de filtro).
  const perfilesConItems = catalog.perfiles.filter((p) =>
    catalog.aiuditas.some((a) => a.perfil === p.slug),
  );

  const query = q.trim().toLowerCase();
  const coincide = (a: AiuditaSpec) => {
    if (filtro === "listas" && !a.live) return false;
    if (filtro !== "all" && filtro !== "listas" && a.perfil !== filtro) return false;
    if (query && !`${a.label} ${a.linea}`.toLowerCase().includes(query)) return false;
    return true;
  };

  // Agrupado por perfil (orden del catálogo); dentro de cada grupo, las listas primero.
  const grupos = perfilesConItems
    .map((p) => ({
      perfil: p,
      items: catalog.aiuditas
        .filter((a) => a.perfil === p.slug && coincide(a))
        .sort((a, b) => Number(b.live) - Number(a.live)),
    }))
    .filter((g) => g.items.length > 0);

  const toggle = (spec: AiuditaSpec) =>
    spec.id in activos ? removeAiudita(ayudanteId, spec.id) : setAiudita(ayudanteId, spec.id, {});

  return (
    <div
      className="cmd-backdrop fixed inset-0 z-50 flex justify-center bg-ink/25 px-4"
      style={{ paddingTop: "min(14vh, 80px)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Agregar aiuditas"
        className="cmd-panel flex w-full max-w-xl flex-col rounded-xl border border-line bg-surface shadow-[0_24px_60px_-34px_rgba(13,45,62,0.45)]"
        style={{ maxHeight: "72vh" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Búsqueda */}
        <div className="flex items-center gap-2.5 border-b border-line px-4 py-3">
          <svg viewBox="0 0 14 14" className="h-3.5 w-3.5 shrink-0 text-ink-3" fill="none">
            <circle cx="6" cy="6" r="4.2" stroke="currentColor" strokeWidth="1.3" />
            <path d="m9.5 9.5 2.7 2.7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar aiudita · cotizar, agendar, conciliar…"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-ink-3"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="shrink-0 rounded border border-line bg-panel px-1 text-[10px] text-ink-3">
            Esc
          </kbd>
        </div>

        {/* Filtros */}
        <div className="flex flex-wrap gap-1.5 border-b border-line px-4 py-2.5">
          <FiltroChip activo={filtro === "all"} onClick={() => setFiltro("all")}>
            Todas
          </FiltroChip>
          {perfilesConItems.map((p) => (
            <FiltroChip key={p.slug} activo={filtro === p.slug} onClick={() => setFiltro(p.slug)}>
              {p.name}
            </FiltroChip>
          ))}
          <FiltroChip activo={filtro === "listas"} onClick={() => setFiltro("listas")}>
            Solo listas
          </FiltroChip>
        </div>

        {/* Filas */}
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {grupos.length === 0 ? (
            <p className="px-4 py-10 text-center text-[12px] text-ink-3">
              {query ? `Sin aiuditas para «${q.trim()}».` : "Sin aiuditas en este filtro."}
            </p>
          ) : (
            grupos.map((g) => (
              <div key={g.perfil.slug}>
                <p className="px-4 pb-1 pt-3 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                  {g.perfil.name}
                </p>
                {g.items.map((spec) => (
                  <PickerRow
                    key={spec.id}
                    spec={spec}
                    activa={spec.id in activos}
                    onToggle={() => toggle(spec)}
                  />
                ))}
              </div>
            ))
          )}
          <div className="h-2" />
        </div>

        {/* Pie honesto */}
        <div className="border-t border-line px-4 py-2.5 text-[11.5px] leading-relaxed text-ink-3">
          Toca el + para equipar una aiudita. Las «por conectar» se guardan listas para cuando
          conectes su fuente; nada se envía sin tu aprobación.
        </div>
      </div>
    </div>
  );
}

function FiltroChip({
  activo,
  onClick,
  children,
}: {
  activo: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={activo}
      className={`rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
        activo
          ? "bg-ink text-surface"
          : "border border-line text-ink-2 hover:border-line-strong hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

/** Una fila del picker: icono de la aiudita, nombre + línea, estado y el botón +/check.
 *  Las "por conectar" quedan atenuadas pero visibles y agregables. */
function PickerRow({
  spec,
  activa,
  onToggle,
}: {
  spec: AiuditaSpec;
  activa: boolean;
  onToggle: () => void;
}) {
  const tipo = aiuditaTipo(spec.id, spec.lectura);
  const color = perfilColor(spec.perfil);
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={activa}
      className={`group flex w-full items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-accent-soft/50 ${
        spec.live ? "" : "opacity-60"
      }`}
    >
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
        style={{ background: `${color}1f`, color }}
      >
        <AiuditaIcon id={spec.id} tipo={tipo} className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-ink">{spec.label}</span>
        <span className="block truncate text-[11.5px] text-ink-3">{spec.linea}</span>
      </span>
      <span
        className="hidden shrink-0 items-center gap-1.5 text-[11px] font-semibold sm:inline-flex"
        style={{ color: spec.live ? "var(--color-ok)" : "var(--color-ink-3)" }}
      >
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: spec.live ? "var(--color-ok)" : "var(--color-line-strong)" }}
        />
        {spec.live ? "Lista" : "Por conectar"}
      </span>
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors ${
          activa
            ? "bg-accent text-surface"
            : "border border-line text-ink-3 group-hover:border-accent group-hover:text-accent-ink"
        }`}
        aria-hidden
      >
        <svg
          viewBox="0 0 16 16"
          className="h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {activa ? <path d="M3.5 8.5 6.5 11.5 12.5 4.5" /> : <path d="M8 3.5v9M3.5 8h9" />}
        </svg>
      </span>
    </button>
  );
}
