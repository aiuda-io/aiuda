"use client";

// Lo que hizo este ayudante, en palabras del dueño: una frase por cada vez que
// trabajó (la escribe el servidor), y al abrirla, qué no pudo y con qué clientes.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type RunDetalle, type RunItem } from "@/lib/api";
import { ErrorState, Skeleton, useApi } from "@/components/ui";
import { hoyOFecha } from "@/lib/format";

const MARCA: Record<RunItem["status"], string | undefined> = {
  done: "var(--color-ok)",
  running: "var(--color-accent)",
  failed: "var(--color-danger)",
  cortado: "var(--color-warn)",
};

const cuando = hoyOFecha;

export function Bitacora({ ayudanteId, name }: { ayudanteId: string; name: string }) {
  const { data, loading, error, refetch } = useApi<RunItem[]>(() => api.runs(ayudanteId), [ayudanteId]);
  const [abierto, setAbierto] = useState("");

  if (error) return <ErrorState message={error} retry={refetch} />;
  if (loading && !data) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <p className="py-8 text-cuerpo text-ink-2">
        {name} todavía no ha trabajado. Cuando lo haga, aquí queda qué revisó, qué te propuso y qué
        no pudo hacer.
      </p>
    );
  }

  return (
    <section>
      <h2 className="mb-2 text-seccion font-semibold text-ink">Lo que hizo</h2>
      <ul>
        {data.map((r) => {
          const on = abierto === r.id;
          return (
            <li key={r.id} className="border-b border-line last:border-0">
              <button
                type="button"
                onClick={() => setAbierto(on ? "" : r.id)}
                aria-expanded={on}
                className="-mx-3 flex w-[calc(100%+1.5rem)] flex-wrap items-baseline gap-x-4 gap-y-1 rounded-lg px-3 py-3.5 text-left hover:bg-panel"
              >
                <span className="min-w-0 flex-1 basis-64 text-cuerpo font-medium text-ink">
                  {r.resumen || "Sin detalle."}
                </span>
                <span className="mark shrink-0" style={{ "--mark": MARCA[r.status] } as React.CSSProperties}>
                  {r.status_label}
                </span>
                <span className="w-full text-apoyo text-ink-3">
                  {[r.disparo_label, cuando(r.started_at)].filter(Boolean).join(" · ")}
                </span>
              </button>
              {on && <Detalle runId={r.id} />}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Detalle({ runId }: { runId: string }) {
  const [d, setD] = useState<RunDetalle | null>(null);
  const [fallo, setFallo] = useState(false);

  useEffect(() => {
    api
      .run(runId)
      .then(setD)
      .catch(() => setFallo(true));
  }, [runId]);

  if (fallo) return <p className="pb-4 text-apoyo text-ink-3">No se pudo abrir el detalle. Intenta de nuevo.</p>;
  if (!d) return <Skeleton className="mb-4 h-12 w-full" />;

  const propuso = d.toco.filter((t) => t.tipo === "reminder");
  const nadaQueDecir = d.motivos.length === 0 && propuso.length === 0 && !d.error;

  return (
    <div className="space-y-4 pb-5">
      {d.error && <p className="text-cuerpo text-danger">{d.error}</p>}

      {propuso.length > 0 && (
        <div>
          <p className="eyebrow">Te propuso</p>
          <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
            {propuso.slice(0, 12).map((t) => (
              <li key={`${t.id}-${t.rol}`} className="text-cuerpo text-ink-2">
                {t.etiqueta}
              </li>
            ))}
          </ul>
          <Link href="/" className="mt-2 inline-block text-apoyo font-medium text-accent-ink hover:underline">
            Verlo en Hoy
          </Link>
        </div>
      )}

      {d.motivos.length > 0 && (
        <div>
          <p className="eyebrow">Lo que no pudo</p>
          <ul className="mt-1.5 space-y-1">
            {d.motivos.map((m) => (
              <li key={m.codigo} className="text-cuerpo text-ink-2">
                <span className="tnum font-medium text-ink">{m.n}</span> {m.detalle || m.codigo.replace(/_/g, " ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {nadaQueDecir && <p className="text-apoyo text-ink-3">No hay más que contar de esta vez.</p>}

      <Link href={`/actividad?r=${runId}`} className="inline-block text-apoyo text-ink-3 hover:text-ink hover:underline">
        Ver el registro completo
      </Link>
    </div>
  );
}
