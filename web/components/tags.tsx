"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Tag } from "@/lib/api";
import { toast } from "@/components/toast";
import { useConfirm, PrimaryButton, SecondaryButton } from "@/components/ui";

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
  // Una etiqueta es un sello: contorno fino y su color solo en la marca de 6px. Antes
  // era una píldora de color, y una lista de clientes parecía confeti.
  return (
    <span className={`sello gap-1.5 ${small ? "" : "h-6 px-2"}`}>
      <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: c.fg }} />
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
        className="btn btn-quiet btn-sm px-2"
      >
        + Etiqueta
      </button>
      {open && (
        <div className="elev-md absolute left-0 top-full z-20 mt-1.5 w-64 rounded-xl bg-surface p-2">
          <div className="max-h-48 space-y-0.5 overflow-y-auto">
            {allTags.length === 0 && (
              <p className="px-1.5 py-2 text-apoyo text-ink-3">Aún no hay etiquetas. Crea la primera.</p>
            )}
            {allTags.map((t) => {
              const on = selectedIds.includes(t.id);
              const c = colorOf(t.color);
              return (
                <button
                  key={t.id}
                  onClick={() => onToggle(t.id)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-cuerpo hover:bg-fill"
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
          <div className="mt-1.5 flex gap-1.5 border-t border-line pt-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && create()}
              placeholder="Nueva etiqueta"
              aria-label="Nueva etiqueta"
              className="field min-w-0 flex-1"
            />
            <SecondaryButton
              onClick={create}
              disabled={!draft.trim() || creating}
            >
              Crear
            </SecondaryButton>
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
    <div>
      {dialog}
      <ul>
        {tags.length === 0 && (
          <li className="text-cuerpo text-ink-2">Aún no hay etiquetas. Crea la primera aquí abajo.</li>
        )}
        {tags.map((t) => (
          <li key={t.id} className="flex items-center gap-3 border-b border-line py-2.5 last:border-0">
            <button onClick={() => recolor(t)} title="Cambiar color" className="rounded-full">
              <TagChip tag={t} />
            </button>
            <span className="tnum text-apoyo text-ink-3">
              {t.count ?? 0} {t.count === 1 ? "cliente" : "clientes"}
            </span>
            <button
              onClick={() => remove(t)}
              className="btn btn-quiet btn-sm ml-auto"
            >
              Eliminar
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-5 flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="Nueva etiqueta: Mayoreo, Moroso"
          aria-label="Nueva etiqueta"
          className="field min-w-0 flex-1"
        />
        <PrimaryButton
          onClick={add}
          disabled={!draft.trim() || busy}
        >
          Crear
        </PrimaryButton>
      </div>
      <p className="mt-3 text-apoyo text-ink-3">Toca una etiqueta para cambiarle el color. Se le ponen a cada cliente desde su ficha.</p>
    </div>
  );
}
