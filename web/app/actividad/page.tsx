"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type RunDetalle, type RunItem, type RunTurno } from "@/lib/api";
import { EmptyState, ErrorState, PageHeader, Skeleton, useApi } from "@/components/ui";

/** Qué hizo tu ayudante.
 *
 *  Un solo lugar con DOS profundidades, no dos pantallas. Por default se lee como una
 *  frase en español ("leyó 12 facturas, propuso 4"); quien quiera el turno completo lo
 *  abre. La regla del producto: el desarrollador instala, el usuario no técnico
 *  implementa, así que la transcripción existe pero no estorba.
 */
export default function ActividadPage() {
  return (
    <Suspense fallback={null}>
      <Actividad />
    </Suspense>
  );
}

const TONO: Record<string, string> = {
  done: "bg-ok-soft text-ok",
  running: "bg-accent-soft text-accent-ink",
  failed: "bg-danger-soft text-danger",
  cortado: "bg-warn-soft text-warn",
};

function cuando(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const hoy = new Date();
  const mismoDia = d.toDateString() === hoy.toDateString();
  const hora = d.toLocaleTimeString("es-MX", { hour: "numeric", minute: "2-digit" });
  if (mismoDia) return `hoy ${hora}`;
  return `${d.toLocaleDateString("es-MX", { day: "numeric", month: "short" })} ${hora}`;
}

function duracion(ms: number | null): string {
  if (!ms) return "";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms / 60000)} min`;
}

function Actividad() {
  const abierto = useSearchParams().get("r") ?? "";
  const { data, loading, error, refetch } = useApi<RunItem[]>(() => api.runs());
  const [sel, setSel] = useState<string>(abierto);

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Actividad"
        subtitle="Qué hizo cada ayudante, cuándo, y qué no pudo. Sin adornos."
      />
      {loading && !data ? (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-16 w-full rounded-lg" />
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState title="Todavía no hay nada que contar">
          Cuando tus ayudantes corran, aquí queda el registro: qué leyeron, qué
          propusieron y por qué omitieron el resto.
        </EmptyState>
      ) : (
        <ul className="space-y-2">
          {data.map((r) => (
            <li key={r.id}>
              <Fila run={r} abierto={sel === r.id} onToggle={() => setSel(sel === r.id ? "" : r.id)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Fila({ run, abierto, onToggle }: { run: RunItem; abierto: boolean; onToggle: () => void }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={abierto}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-panel/40"
      >
        <span
          className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-sello font-medium ${
            TONO[run.status] ?? "bg-panel text-ink-2"
          }`}
        >
          {run.status_label}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-cuerpo font-medium text-ink">
            {run.resumen || "Sin detalle."}
          </span>
          <span className="mt-0.5 block text-apoyo text-ink-3">
            {[run.ayudante, run.disparo_label, cuando(run.started_at), duracion(run.duracion_ms)]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
        <svg
          viewBox="0 0 12 12"
          aria-hidden
          className={`mt-1 h-3 w-3 shrink-0 text-ink-3 transition-transform ${abierto ? "rotate-90" : ""}`}
          fill="none"
        >
          <path d="M4.5 3 8 6l-3.5 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {abierto && <Detalle runId={run.id} />}
    </div>
  );
}

function Detalle({ runId }: { runId: string }) {
  const [d, setD] = useState<RunDetalle | null>(null);
  const [turnos, setTurnos] = useState<RunTurno[] | null>(null);
  const [verTecnico, setVerTecnico] = useState(false);

  useEffect(() => {
    api.run(runId).then(setD).catch(() => setD(null));
  }, [runId]);

  const abrirTecnico = useCallback(async () => {
    setVerTecnico(true);
    if (turnos === null) {
      try {
        setTurnos(await api.runTurnos(runId));
      } catch {
        setTurnos([]);
      }
    }
  }, [runId, turnos]);

  if (!d) return <div className="border-t border-line px-4 py-3"><Skeleton className="h-12 w-full" /></div>;

  return (
    <div className="border-t border-line px-4 py-3.5">
      {/* Lo que el dueño necesita: qué tocó y qué NO pudo, con su razón. */}
      {d.motivos.length > 0 && (
        <div className="mb-3">
          <p className="mb-1 text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
            Lo que no pudo
          </p>
          <ul className="space-y-1">
            {d.motivos.map((m) => (
              <li key={m.codigo} className="text-cuerpo text-ink-2">
                <span className="tnum font-medium text-ink">{m.n}</span>{" "}
                {m.detalle || m.codigo.replace(/_/g, " ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {d.toco.length > 0 && (
        <div className="mb-3">
          <p className="mb-1 text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
            Lo que tocó
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {d.toco.slice(0, 12).map((t) => (
              <li key={`${t.tipo}-${t.id}-${t.rol}`}>
                {t.tipo === "reminder" ? (
                  <Link
                    href={`/centro?r=${t.id}`}
                    className="inline-block rounded border border-line px-1.5 py-0.5 text-sello text-ink-2 transition-colors hover:border-accent hover:text-accent-ink"
                  >
                    {t.etiqueta}
                  </Link>
                ) : (
                  <span className="inline-block rounded border border-line px-1.5 py-0.5 text-sello text-ink-3">
                    {t.etiqueta}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {d.error && (
        <p className="mb-3 rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-cuerpo text-danger">
          {d.error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3 text-apoyo text-ink-3">
        <span className="tnum">
          {(d.input_tokens + d.output_tokens).toLocaleString("es-MX")} tokens
        </span>
        {d.hay_transcripcion && !verTecnico && (
          <button
            onClick={abrirTecnico}
            className="font-medium text-accent-ink underline-offset-2 hover:underline"
          >
            Ver el detalle técnico
          </button>
        )}
        {!d.hay_transcripcion && <span>La transcripción ya se depuró por antigüedad.</span>}
      </div>

      {verTecnico && (
        <div className="mt-3 space-y-3">
          {turnos === null ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            turnos.map((t) => <Turno key={t.idx} t={t} />)
          )}
        </div>
      )}
    </div>
  );
}

function Turno({ t }: { t: RunTurno }) {
  return (
    <div className="rounded-md border border-line/70 bg-bg px-3 py-2.5">
      <p className="text-sello text-ink-3">
        {[t.task, t.model, `${t.latencia_ms} ms`].filter(Boolean).join(" · ")}
      </p>
      {t.tools.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {t.tools.map((h, i) => (
            <li key={i} className="text-apoyo text-ink-2">
              <span className="font-medium text-ink">{h.nombre}</span>
              <span className="text-ink-3"> · {h.ms} ms</span>
              {h.error ? (
                <span className="text-danger"> · {h.error}</span>
              ) : (
                <span className="text-ink-3"> → {h.resultado_resumen}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {(t.system_prompt || t.user_prompt || t.output_text) && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sello text-ink-3 hover:text-ink-2">
            Prompt y respuesta
          </summary>
          {/* Los datos de tus clientes salen sustituidos por marcadores estables desde
              que se guardaron: aquí no hay forma de leer el original, porque nunca se
              escribió. Los montos y folios sí están: sin ellos no podrías juzgar. */}
          <pre className="mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap text-apoyo leading-relaxed text-ink-3">
            {[t.system_prompt, t.user_prompt, t.output_text].filter(Boolean).join("\n\n---\n\n")}
          </pre>
        </details>
      )}
    </div>
  );
}
