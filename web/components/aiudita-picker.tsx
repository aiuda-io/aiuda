"use client";

import { useEffect, useRef, useState } from "react";
import type { AiuditaConfig, AiuditasCatalog, AiuditaSpec } from "@/lib/api";
import { AiuditaIcon, aiuditaTipo } from "@/components/aiudita-icon";
import { removeAiudita, setAiudita } from "@/lib/ayudantes-store";

/**
 * Elegir qué sabe hacer un ayudante: busca, filtra por oficio y pone o quita con un toque.
 * Se alimenta del catálogo del servidor; lo elegido se guarda al momento y la palomita
 * cambia sin recargar. Cierra con Esc o tocando fuera.
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
  // "all" | "listas" | slug del oficio
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
className="cmd-panel elev-lg flex w-full max-w-xl flex-col self-start rounded-2xl bg-surface"
        style={{ maxHeight: "72vh" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
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
            placeholder="Buscar: cotizar, agendar, conciliar"
            aria-label="Buscar aiudita"
            className="min-w-0 flex-1 bg-transparent text-cuerpo text-ink outline-none placeholder:text-ink-3"
            autoComplete="off"
            spellCheck={false}
          />
          <button type="button" onClick={onClose} className="btn btn-quiet btn-sm shrink-0">
            Listo
          </button>
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
            Las que ya funcionan
          </FiltroChip>
        </div>

        {/* Filas */}
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {grupos.length === 0 ? (
            <p className="px-4 py-10 text-center text-cuerpo text-ink-3">
              {query ? `Nada coincide con «${q.trim()}».` : "No hay ninguna aquí."}
            </p>
          ) : (
            grupos.map((g) => (
              <div key={g.perfil.slug}>
                <p className="eyebrow px-4 pb-1 pt-4">
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

        <div className="border-t border-line px-4 py-3 text-apoyo text-ink-3">
          Toca una para ponerla o quitarla. Las que todavía no funcionan se pueden dejar puestas:
          no hacen nada hasta que estén listas.
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
      className={`btn btn-sm ${activo ? "btn-elegida" : "btn-secondary"}`}
    >
      {children}
    </button>
  );
}

/** Una fila: su dibujo, nombre y qué hace, y la palomita si ya la tiene. Las que
 *  todavía no funcionan se ven más tenues, pero se pueden poner. */
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
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={activa}
      className="group flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-panel"
    >
      <span
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-fill p-2 text-ink-2 ${
          spec.live ? "" : "opacity-50"
        }`}
      >
        <AiuditaIcon id={spec.id} tipo={tipo} className="h-5 w-5" />
      </span>
      <span className={`min-w-0 flex-1 ${spec.live ? "" : "opacity-60"}`}>
        <span className="block truncate text-cuerpo font-medium text-ink">{spec.label}</span>
        <span className="block truncate text-apoyo text-ink-3">
          {spec.live ? spec.linea : `Todavía no funciona. ${spec.linea}`}
        </span>
      </span>
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors ${
          activa
            ? "bg-accent text-surface"
            : "bg-fill text-ink-3 group-hover:bg-fill-strong group-hover:text-ink"
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
