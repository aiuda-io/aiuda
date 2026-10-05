"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type RunDetalle, type RunItem, type RunTurno } from "@/lib/api";
import { EmptyState, ErrorState, Skeleton, useApi } from "@/components/ui";
import { Marca } from "@/components/hoy/piezas";
import { hoyOFecha } from "@/lib/format";

/* Qué hizo cada ayudante cada vez que trabajó.
 *
 * Dos profundidades, no dos pantallas. Por default se lee como una frase en español
 * ("leyó 12 facturas, propuso 4"); quien quiera el paso a paso lo abre. El desarrollador
 * instala y el dueño usa: el detalle existe pero no estorba.
 */

const COLOR: Record<string, "ok" | "accent" | "danger" | "warn"> = {
  done: "ok",
  running: "accent",
  failed: "danger",
  cortado: "warn",
};

// Por qué empezó a trabajar, dicho como lo diría el dueño. El server manda su propia
// etiqueta; aquí se cambia la única que usa una palabra de adentro.
const POR_QUE: Record<string, string> = {
  corrida: "Revisión del día",
};

const cuando = hoyOFecha;

function duracion(ms: number | null): string {
  if (!ms) return "";
  if (ms < 1000) return "menos de un segundo";
  if (ms < 60000) return `${Math.round(ms / 1000)} s`;
  return `${Math.round(ms / 60000)} min`;
}

export function TrabajoAyudantes({ abrir }: { abrir: string }) {
  const { data, loading, error, refetch } = useApi<RunItem[]>(() => api.runs());
  const [sel, setSel] = useState<string>(abrir);

  if (error) return <ErrorState message={error} retry={refetch} />;
  if (loading && !data) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-14 w-full rounded-lg" />
        <Skeleton className="h-14 w-full rounded-lg" />
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState title="Tus ayudantes todavía no han trabajado">
        Cuando lo hagan, aquí queda qué leyeron, qué redactaron y qué no pudieron hacer.
      </EmptyState>
    );
  }
  return (
    <ul>
      {data.map((r) => (
        <li key={r.id} className="border-t border-line first:border-t-0">
          <Fila run={r} abierto={sel === r.id} onToggle={() => setSel(sel === r.id ? "" : r.id)} />
        </li>
      ))}
    </ul>
  );
}

function Fila({ run, abierto, onToggle }: { run: RunItem; abierto: boolean; onToggle: () => void }) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={abierto}
        className="flex w-full items-start gap-3 py-4 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-cuerpo font-medium text-ink">
            {run.resumen || "Sin detalle."}
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-apoyo text-ink-3">
            <Marca color={COLOR[run.status]}>{run.status_label}</Marca>
            {[
              run.ayudante,
              POR_QUE[run.disparo] ?? run.disparo_label,
              cuando(run.started_at),
              duracion(run.duracion_ms),
            ]
              .filter(Boolean)
              .map((t, i) => (
                <span key={i}>{t}</span>
              ))}
          </span>
        </span>
        <svg
          viewBox="0 0 12 12"
          aria-hidden
          className={`mt-1.5 h-3 w-3 shrink-0 text-ink-3 transition-transform ${abierto ? "rotate-90" : ""}`}
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
  const [verPasos, setVerPasos] = useState(false);

  useEffect(() => {
    api.run(runId).then(setD).catch(() => setD(null));
  }, [runId]);

  const abrirPasos = useCallback(async () => {
    setVerPasos(true);
    if (turnos === null) {
      try {
        setTurnos(await api.runTurnos(runId));
      } catch {
        setTurnos([]);
      }
    }
  }, [runId, turnos]);

  if (!d) return <Skeleton className="mb-4 h-12 w-full" />;

  return (
    <div className="pb-5">
      {/* Lo que el dueño necesita: qué tocó y qué NO pudo, con su razón. */}
      {d.motivos.length > 0 && (
        <div className="mb-4">
          <p className="eyebrow mb-1">Lo que no pudo</p>
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
        <div className="mb-4">
          <p className="eyebrow mb-1">Lo que tocó</p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {d.toco.slice(0, 12).map((t) => (
              <li key={`${t.tipo}-${t.id}-${t.rol}`} className="text-apoyo">
                {t.tipo === "reminder" ? (
                  <Link
                    href={`/?r=${t.id}`}
                    className="font-medium text-accent-ink underline-offset-2 hover:underline"
                  >
                    {t.etiqueta}
                  </Link>
                ) : (
                  <span className="text-ink-2">{t.etiqueta}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {d.error && (
        <p role="alert" className="mb-4 text-cuerpo text-danger">
          {d.error}
        </p>
      )}

      <div className="text-apoyo text-ink-3">
        {d.hay_transcripcion && !verPasos && (
          <button
            type="button"
            onClick={abrirPasos}
            className="font-medium text-accent-ink underline-offset-2 hover:underline"
          >
            Ver el paso a paso
          </button>
        )}
        {!d.hay_transcripcion && <span>El paso a paso ya se borró por antigüedad.</span>}
      </div>

      {verPasos && (
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
    <div className="rounded-2xl bg-panel px-4 py-3">
      <p className="text-apoyo text-ink-3">
        {[t.task, t.model, `${t.latencia_ms} ms`].filter(Boolean).join(" · ")}
      </p>
      {t.tools.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {t.tools.map((h, i) => (
            <li key={i} className="break-words text-apoyo text-ink-2">
              <span className="font-medium text-ink">{h.nombre}</span>
              <span className="text-ink-3"> · {h.ms} ms</span>
              {h.error ? (
                <span className="text-danger"> · {h.error}</span>
              ) : (
                <span className="text-ink-3"> · {h.resultado_resumen}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {(t.system_prompt || t.user_prompt || t.output_text) && (
        <details className="mt-2">
          <summary className="cursor-pointer text-apoyo text-ink-3 hover:text-ink-2">
            Lo que se le pidió y lo que contestó
          </summary>
          {/* Los datos de tus clientes salen sustituidos por marcadores estables desde
              que se guardaron: aquí no hay forma de leer el original, porque nunca se
              escribió. Los montos y folios sí están: sin ellos no podrías juzgar. */}
          <pre className="mt-1.5 whitespace-pre-wrap break-words text-apoyo leading-relaxed text-ink-3">
            {[t.system_prompt, t.user_prompt, t.output_text].filter(Boolean).join("\n\n")}
          </pre>
        </details>
      )}
    </div>
  );
}
