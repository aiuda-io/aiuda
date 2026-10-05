"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { EmptyState, ErrorState, PageHeader, PrimaryButton, SecondaryButton, Skeleton, TextInput } from "@/components/ui";
import { Avatar } from "@/components/avatar";
import { Drawer } from "@/components/drawer";
import { toast } from "@/components/toast";
import { createAyudante, useAyudantes, useCatalog, type Ayudante } from "@/lib/ayudantes-store";
import type { AiuditasCatalog } from "@/lib/api";
import { appearanceForSlug, lookForAiuditas, normalizeAppearance } from "@/lib/look";
import { perfilesActivos } from "@/lib/perfiles";

function Flecha() {
  return (
    <svg viewBox="0 0 12 12" aria-hidden className="h-3 w-3 shrink-0 text-ink-3" fill="none">
      <path d="M4.5 3 8 6l-3.5 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Un renglón del equipo: su cara, el nombre que le puso el dueño, de qué se encarga
 *  y si tiene algo esperando aprobación. */
function Renglon({ a, catalog }: { a: Ayudante; catalog: AiuditasCatalog | null }) {
  const oficios = catalog ? perfilesActivos(catalog, a.aiuditas) : [];
  return (
    <li className="border-b border-line last:border-0">
      <Link href={`/ayudantes/detalle?id=${a.id}`} className="-mx-3 flex items-center gap-4 rounded-lg px-3 py-4 hover:bg-panel">
        <Avatar name={a.name} size={44} {...normalizeAppearance(a.appearance)} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-seccion font-semibold text-ink">{a.name}</p>
          <p className="truncate text-cuerpo text-ink-2">
            {oficios.length > 0 ? oficios.map((p) => p.name).join(" y ") : "Todavía sin tareas"}
          </p>
        </div>
        {a.acciones.pendientes > 0 && (
          <span className="mark shrink-0" style={{ "--mark": "var(--color-accent)" } as React.CSSProperties}>
            {a.acciones.pendientes} por aprobar
          </span>
        )}
        <Flecha />
      </Link>
    </li>
  );
}

/** Alta de un ayudante: el dueño le pone nombre y elige de qué se va a encargar. El
 *  oficio solo le precarga sus tareas; se pueden cambiar después. */
function Nuevo({
  open,
  onClose,
  catalog,
  cuantos,
}: {
  open: boolean;
  onClose: () => void;
  catalog: AiuditasCatalog | null;
  cuantos: number;
}) {
  const router = useRouter();
  const [nombre, setNombre] = useState("");
  const [oficio, setOficio] = useState("cobranza");
  const [creando, setCreando] = useState(false);

  const crear = async () => {
    const name = nombre.trim();
    if (!name || creando) return;
    setCreando(true);
    try {
      const ids = catalog ? catalog.aiuditas.filter((x) => x.perfil === oficio).map((x) => x.id) : [];
      const cara = oficio ? appearanceForSlug(oficio) : lookForAiuditas([], cuantos);
      const a = await createAyudante(name, cara, ids);
      router.push(`/ayudantes/detalle?id=${a.id}&nuevo=1`);
    } catch (e) {
      toast(`No se pudo crear: ${(e as Error).message}`, "error");
      setCreando(false);
    }
  };

  const opciones = [
    ...(catalog?.perfiles ?? []).map((p) => {
      const tareas = catalog!.aiuditas.filter((x) => x.perfil === p.slug);
      const faltan = tareas.filter((x) => !x.live).length;
      return {
        slug: p.slug,
        nombre: p.name,
        desc: p.desc,
        nota: faltan > 0 ? `${faltan} de sus ${tareas.length} tareas todavía no funcionan.` : "",
      };
    }),
    { slug: "", nombre: "Lo decido después", desc: "Empieza sin tareas y se las agregas tú.", nota: "" },
  ];

  return (
    <Drawer open={open} onClose={onClose} title="Nuevo ayudante" subtitle="Tú le pones el nombre">
      <form
        className="space-y-7"
        onSubmit={(e) => {
          e.preventDefault();
          crear();
        }}
      >
        <label className="block">
          <span className="text-cuerpo font-medium text-ink">¿Cómo se llama?</span>
          <TextInput
            autoFocus
            className="mt-2"
            value={nombre}
            maxLength={120}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="El nombre que tú quieras"
          />
        </label>

        <fieldset>
          <legend className="text-cuerpo font-medium text-ink">¿De qué se va a encargar?</legend>
          <div className="mt-2">
            {opciones.map((o) => (
              <label
                key={o.slug || "ninguno"}
                className="flex cursor-pointer items-start gap-3 border-b border-line py-3 last:border-0"
              >
                <input
                  type="radio"
                  name="oficio"
                  className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-accent)]"
                  checked={oficio === o.slug}
                  onChange={() => setOficio(o.slug)}
                />
                <span className="min-w-0">
                  <span className="block text-cuerpo font-medium text-ink">{o.nombre}</span>
                  <span className="block text-apoyo text-ink-2">{o.desc}</span>
                  {o.nota && <span className="block text-apoyo text-ink-3">{o.nota}</span>}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="flex gap-2">
          <PrimaryButton type="submit" disabled={!nombre.trim() || creando}>
            {creando ? "Creando…" : "Crear ayudante"}
          </PrimaryButton>
          <SecondaryButton type="button" onClick={onClose}>
            Cancelar
          </SecondaryButton>
        </div>
      </form>
    </Drawer>
  );
}

export default function AyudantesPage() {
  const { ayudantes, loading, error, retry } = useAyudantes();
  const { catalog } = useCatalog();
  const [nuevo, setNuevo] = useState(false);
  const hay = ayudantes.length > 0;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Ayudantes"
        subtitle="Tu equipo. Cada uno redacta y propone; nada sale sin que tú lo apruebes."
        right={hay ? <PrimaryButton onClick={() => setNuevo(true)}>Agregar ayudante</PrimaryButton> : undefined}
      />
      <Nuevo open={nuevo} onClose={() => setNuevo(false)} catalog={catalog} cuantos={ayudantes.length} />

      {error ? (
        <ErrorState message={error} retry={retry} />
      ) : loading ? (
        <div className="max-w-3xl space-y-2">
          <Skeleton className="h-[76px] w-full" />
          <Skeleton className="h-[76px] w-full" />
        </div>
      ) : !hay ? (
        <EmptyState
          title="Todavía no tienes ayudantes"
          action={<PrimaryButton onClick={() => setNuevo(true)}>Crear mi primer ayudante</PrimaryButton>}
        >
          Falta crear al primero. Le pones nombre, eliges de qué se encarga y empieza a proponerte
          qué hacer.
        </EmptyState>
      ) : (
        <ul className="max-w-3xl">
          {ayudantes.map((a) => (
            <Renglon key={a.id} a={a} catalog={catalog} />
          ))}
        </ul>
      )}

      {/* Portales salió del menú y entra desde aquí: es trabajo que aiuda hace por el
          dueño en un sitio web, igual que el de un ayudante. */}
      {!error && !loading && (
        <section className="mt-14 max-w-3xl">
          <h2 className="eyebrow">También trabaja por ti</h2>
          <Link href="/rutinas" className="-mx-3 mt-1 flex items-center gap-4 rounded-lg px-3 py-4 hover:bg-panel">
            <div className="min-w-0 flex-1">
              <p className="text-seccion font-semibold text-ink">Portales</p>
              <p className="text-cuerpo text-ink-2">
                aiuda entra al portal del SAT y te baja tu opinión de cumplimiento y tu constancia de
                situación fiscal.
              </p>
            </div>
            <Flecha />
          </Link>
        </section>
      )}
    </div>
  );
}
