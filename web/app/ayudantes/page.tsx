"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PageHeader, PrimaryButton, SecondaryButton, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { Avatar } from "@/components/avatar";
import {
  createAyudante,
  useAyudantes,
  useCatalog,
  type Ayudante,
} from "@/lib/ayudantes-store";
import type { AiuditasCatalog, PerfilSpec } from "@/lib/api";
import { appearanceForSlug, lookForAiuditas, normalizeAppearance } from "@/lib/look";
import { perfilesActivos } from "@/lib/perfiles";

/** Sugerencias de nombre para el primer ayudante (cortos, propios, sin apellido). */
const NOMBRES_SUGERIDOS = ["abi", "ome", "gio", "uli", "tavo", "nan"];

function aiuditasDePerfil(catalog: AiuditasCatalog, slug: string) {
  return catalog.aiuditas.filter((a) => a.perfil === slug);
}

/** Tarjeta "roster": el ayudante como alguien de tu plantilla · mascota, nombre, oficio
 *  (sus perfiles activos), lo que sabe hacer (chips de aiuditas) y su nivel real. Se abre
 *  a su ficha. */
function AyudanteCard({ a, catalog }: { a: Ayudante; catalog: AiuditasCatalog | null }) {
  const perfiles = catalog ? perfilesActivos(catalog, a.aiuditas) : [];
  const specs = catalog ? catalog.aiuditas.filter((c) => c.id in a.aiuditas) : [];
  const rol = perfiles.length > 0 ? perfiles.map((p) => p.name).join(" · ") : "Sin oficio todavía";
  const MAX = 3;
  return (
    <Link
      href={`/ayudantes/detalle?id=${a.id}`}
      className="group flex flex-col rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong"
    >
      <div className="flex items-center gap-3">
        <Avatar name={a.name} size={44} {...normalizeAppearance(a.appearance)} />
        <div className="min-w-0 flex-1">
          <p className="text-cuerpo font-semibold text-ink group-hover:text-accent-ink">{a.name}</p>
          <p className="truncate text-apoyo text-ink-3">{rol}</p>
        </div>
      </div>

      {specs.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {specs.slice(0, MAX).map((c) => (
            <span key={c.id} className="rounded-md bg-panel px-2 py-0.5 text-sello text-ink-2">
              {c.label}
            </span>
          ))}
          {specs.length > MAX && (
            <span className="rounded-md px-1.5 py-0.5 text-sello text-ink-3">
              +{specs.length - MAX}
            </span>
          )}
        </div>
      ) : (
        <p className="mt-3 text-apoyo text-ink-3">Sin aiuditas todavía</p>
      )}

      <div className="mt-3 flex items-center justify-between border-t border-line/60 pt-3">
        <span className="text-apoyo text-ink-3">
          <span className="font-medium text-ink-2">{a.nivel.nivel}</span> · {a.acciones.total} acci
          {a.acciones.total === 1 ? "ón" : "ones"}
        </span>
        <span className="text-cuerpo font-medium text-accent-ink group-hover:underline">
          Abrir &rarr;
        </span>
      </div>
    </Link>
  );
}

/** Plantilla en fila compacta: un rol ya armado (mascota, nombre, cuántas aiuditas trae y
 *  cuántas están listas) con un botón para partir de ahí. El catálogo completo ya no se
 *  apila en la página: se explora al agregar aiuditas dentro de la ficha. */
function PlantillaCard({
  p,
  count,
  live,
  onUse,
  busy,
  disabled,
}: {
  p: PerfilSpec;
  count: number;
  live: number;
  onUse: () => void;
  busy: boolean;
  disabled: boolean;
}) {
  return (
    <div className={`flex items-center gap-3 rounded-lg border border-line bg-surface p-3 ${busy ? "ring-1 ring-accent/40" : ""}`}>
      <Avatar name={p.name} size={34} {...appearanceForSlug(p.slug)} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-seccion font-semibold text-ink">{p.name}</p>
        <p className="text-apoyo text-ink-3">
          {count} aiudita{count === 1 ? "" : "s"}
          {live > 0 ? ` · ${live} lista${live === 1 ? "" : "s"}` : " · por conectar"}
        </p>
      </div>
      <SecondaryButton onClick={onUse} disabled={disabled || busy}>
        {busy ? "Creando…" : "Usar"}
      </SecondaryButton>
    </div>
  );
}

function CrearAyudante({ onClose, count }: { onClose: () => void; count: number }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const crear = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const a = await createAyudante(name.trim() || "Sin nombre", lookForAiuditas([], count));
      router.push(`/ayudantes/detalle?id=${a.id}&nuevo=1`);
    } catch {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <p className="text-cuerpo font-medium text-ink">Nuevo ayudante</p>
      <p className="mt-0.5 text-apoyo text-ink-3">
        Ponle un nombre corto. Luego le agregas las aiuditas que quieras.
      </p>
      <form
        className="mt-3 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          crear();
        }}
      >
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="abi"
          className="min-w-0 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
        />
        <PrimaryButton type="submit" disabled={saving}>
          {saving ? "Creando…" : "Crear ayudante"}
        </PrimaryButton>
        <SecondaryButton type="button" onClick={onClose}>
          Cancelar
        </SecondaryButton>
      </form>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <span className="text-apoyo text-ink-3">Sugerencias:</span>
        {NOMBRES_SUGERIDOS.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => setName(n)}
            className="rounded-full border border-line bg-panel/50 px-2 py-0.5 text-sello text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function AyudantesPage() {
  const { ayudantes, loading, error, retry } = useAyudantes();
  const { catalog, error: catError, retry: catRetry } = useCatalog();
  const [creating, setCreating] = useState(false);
  const [usando, setUsando] = useState<string | null>(null);
  const router = useRouter();

  const usarPlantilla = async (p: PerfilSpec) => {
    if (!catalog || usando) return;
    setUsando(p.slug);
    try {
      const ids = aiuditasDePerfil(catalog, p.slug).map((a) => a.id);
      const a = await createAyudante(p.name, appearanceForSlug(p.slug), ids);
      router.push(`/ayudantes/detalle?id=${a.id}&nuevo=1`);
    } catch {
      setUsando(null);
    }
  };

  return (
    <div className="min-w-0">
      <PageHeader
        title="Ayudantes"
        subtitle="Crea un ayudante desde cero o desde una plantilla, y agrégale aiuditas: las cosas concretas que quieres que haga. Cada una se explica y se configura a tu negocio."
        right={
          !creating && (
            <PrimaryButton onClick={() => setCreating(true)}>Crear ayudante</PrimaryButton>
          )
        }
      />

      {creating && (
        <div className="mb-6">
          <CrearAyudante onClose={() => setCreating(false)} count={ayudantes.length} />
        </div>
      )}

      <section>
        <h2 className="mb-2.5 text-rotulo font-semibold uppercase tracking-[0.07em] text-ink-3">
          Tus ayudantes · {ayudantes.length}
        </h2>
        {error ? (
          <ErrorState message={error} retry={retry} />
        ) : loading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </div>
        ) : ayudantes.length === 0 ? (
          !creating && (
            <EmptyState
              title="Todavía no tienes ayudantes"
              action={<PrimaryButton onClick={() => setCreating(true)}>Crear mi primer ayudante</PrimaryButton>}
            >
              Un ayudante es tuyo: tú lo nombras (abi, ome, gio…) y le agregas las aiuditas
              que tu negocio necesita. Empieza desde cero, o usa una plantilla de abajo.
            </EmptyState>
          )
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {ayudantes.map((a) => (
              <AyudanteCard key={a.id} a={a} catalog={catalog} />
            ))}
          </div>
        )}
      </section>

      <section className="mt-9">
        <h2 className="mb-1 text-rotulo font-semibold uppercase tracking-[0.07em] text-ink-3">
          Empieza desde una plantilla
        </h2>
        <p className="mb-3.5 text-cuerpo text-ink-3">
          Una plantilla es un rol ya armado con sus aiuditas. Úsala para no partir de cero:
          se crea un ayudante que luego nombras y ajustas a tu gusto. El catálogo completo de
          aiuditas se explora al agregarlas dentro de cada ayudante.
        </p>
        {catError ? (
          <ErrorState message={catError} retry={catRetry} />
        ) : !catalog ? (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {catalog.perfiles.map((p) => {
              const items = aiuditasDePerfil(catalog, p.slug);
              return (
                <PlantillaCard
                  key={p.slug}
                  p={p}
                  count={items.length}
                  live={items.filter((a) => a.live).length}
                  onUse={() => usarPlantilla(p)}
                  busy={usando === p.slug}
                  disabled={usando !== null}
                />
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
