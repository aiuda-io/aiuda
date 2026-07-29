"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Tag } from "@/lib/api";
import { toast } from "@/components/toast";
import { useConfirm } from "@/components/ui";

// Los fondos suaves y el tinta azul salen de los tokens del tema (mismo color, ya no
// literal, así respetan el tema). Los tintas verde/ámbar/rojo y los pares morado/rosa/
// gris no tienen token equivalente exacto, así que quedan como literal para no correr
// el color.
export const TAG_COLORS: Record<string, { bg: string; fg: string }> = {
  azul: { bg: "var(--color-accent-soft)", fg: "var(--color-accent-ink)" },
  verde: { bg: "var(--color-ok-soft)", fg: "oklch(0.5 0.12 161)" },
  ambar: { bg: "var(--color-warn-soft)", fg: "oklch(0.55 0.13 68)" },
  rojo: { bg: "var(--color-danger-soft)", fg: "oklch(0.55 0.18 27)" },
  morado: { bg: "oklch(0.95 0.03 300)", fg: "oklch(0.5 0.13 300)" },
  rosa: { bg: "oklch(0.95 0.03 350)", fg: "oklch(0.55 0.15 350)" },
  gris: { bg: "oklch(0.94 0.005 230)", fg: "oklch(0.46 0.02 232)" },
};

export const PALETTE = ["azul", "verde", "ambar", "rojo", "morado", "rosa", "gris"];

function colorOf(color: string) {
  return TAG_COLORS[color] ?? TAG_COLORS.gris;
}

export function TagChip({
  tag,
  onRemove,
  small,
}: {
  tag: Tag;
  onRemove?: () => void;
  small?: boolean;
}) {
  const c = colorOf(tag.color);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-medium ${small ? "px-1.5 py-px text-[10.5px]" : "px-2 py-0.5 text-[11.5px]"}`}
      style={{ background: c.bg, color: c.fg }}
    >
      {tag.name}
      {onRemove && (
        <button onClick={onRemove} aria-label={`Quitar ${tag.name}`} className="-mr-0.5 leading-none opacity-70 hover:opacity-100">
          &times;
        </button>
      )}
    </span>
  );
}

export function TagPicker({
  allTags,
  selectedIds,
  onToggle,
  onCreate,
}: {
  allTags: Tag[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  onCreate: (name: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [creating, setCreating] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  async function create() {
    const name = draft.trim();
    if (!name || creating) return;
    setCreating(true);
    try {
      await onCreate(name);
      setDraft("");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded-full border border-dashed border-line-strong px-2 py-0.5 text-[11.5px] font-medium text-ink-3 transition-colors hover:border-accent hover:text-accent-ink"
      >
        + Etiqueta
      </button>
      {open && (
        <div className="absolute left-0 top-full z-20 mt-1.5 w-56 rounded-lg border border-line bg-surface p-2 shadow-[0_4px_24px_rgba(13,45,62,0.12)]">
          <div className="max-h-48 space-y-0.5 overflow-y-auto">
            {allTags.length === 0 && (
              <p className="px-1.5 py-2 text-[11.5px] text-ink-3">Aún no hay etiquetas. Crea la primera.</p>
            )}
            {allTags.map((t) => {
              const on = selectedIds.includes(t.id);
              const c = colorOf(t.color);
              return (
                <button
                  key={t.id}
                  onClick={() => onToggle(t.id)}
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[12px] transition-colors hover:bg-panel/60"
                >
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: c.fg }} />
                  <span className="flex-1 text-ink">{t.name}</span>
                  {on && (
                    <svg viewBox="0 0 12 12" className="h-3 w-3 text-accent-ink" fill="none">
                      <path d="m2.5 6.5 2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </button>
              );
            })}
          </div>
          <div className="mt-1.5 flex gap-1.5 border-t border-line/60 pt-1.5">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && create()}
              placeholder="Nueva etiqueta…"
              className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
            />
            <button
              onClick={create}
              disabled={!draft.trim() || creating}
              className="rounded-md bg-accent px-2 py-1 text-[11.5px] font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
            >
              Crear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function TagManager() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const { confirm, dialog } = useConfirm();

  useEffect(() => {
    api.tags().then(setTags).catch(() => {});
  }, []);

  async function add() {
    const name = draft.trim();
    if (!name || busy) return;
    setBusy(true);
    try {
      const tag = await api.createTag(name);
      setTags((prev) => [...prev, tag]);
      setDraft("");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function recolor(tag: Tag) {
    const next = PALETTE[(PALETTE.indexOf(tag.color) + 1) % PALETTE.length];
    const updated = await api.updateTag(tag.id, { color: next }).catch(() => null);
    if (updated) setTags((prev) => prev.map((t) => (t.id === tag.id ? updated : t)));
  }

  async function remove(tag: Tag) {
    if (
      !(await confirm({
        title: `Eliminar "${tag.name}"`,
        message: "La etiqueta se quita de todos los clientes que la tienen. No borra a los clientes.",
      }))
    )
      return;
    await api.deleteTag(tag.id).catch(() => {});
    setTags((prev) => prev.filter((t) => t.id !== tag.id));
  }

  return (
    <div className="px-5 py-4">
      {dialog}
      <ul className="space-y-1.5">
        {tags.length === 0 && (
          <li className="text-[12.5px] text-ink-3">Aún no hay etiquetas. Crea la primera abajo.</li>
        )}
        {tags.map((t) => (
          <li key={t.id} className="flex items-center gap-2.5 border-b border-line/50 py-1.5 last:border-0">
            <button onClick={() => recolor(t)} title="Cambiar color">
              <TagChip tag={t} />
            </button>
            <span className="tnum text-[11.5px] text-ink-3">
              {t.count ?? 0} {t.count === 1 ? "cliente" : "clientes"}
            </span>
            <button
              onClick={() => remove(t)}
              className="ml-auto text-[12px] text-ink-3 transition-colors hover:text-danger"
            >
              Eliminar
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex max-w-sm gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="Nueva etiqueta (ej. VIP, Mayoreo, Moroso)…"
          className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
        />
        <button
          onClick={add}
          disabled={!draft.trim() || busy}
          className="rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
        >
          Crear
        </button>
      </div>
      <p className="mt-2 text-[11px] text-ink-3">Toca una etiqueta para cambiar su color. Las etiquetas son del negocio y se asignan en cada cliente.</p>
    </div>
  );
}
