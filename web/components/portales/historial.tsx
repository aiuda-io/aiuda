"use client";

// Lo que aiuda ha hecho en los portales: arriba lo que está pasando ahora, con sus
// pasos, y abajo lo terminado. Cada renglón se abre para ver qué pediste, qué trajo y
// las capturas que tomó como prueba.
import { useState } from "react";
import { api, apiUrl, type CuaMision } from "@/lib/api";
import { Collapse } from "@/components/motion";
import { Skeleton } from "@/components/ui";
import { toast } from "@/components/toast";
import { fechaHora, haceTiempo } from "@/lib/format";
import { ESTADO, Marca, cuandoFue, instruccionDe } from "@/components/portales/comunes";

const TOPE = 6;

export function Historial({ misiones }: { misiones: CuaMision[] }) {
  const [todo, setTodo] = useState(false);

  const vivas = misiones
    .filter((m) => ESTADO[m.status].vivo)
    // Lo que ya está adentro antes que lo que espera turno; dentro, lo más reciente.
    .sort((a, b) => {
      if (a.status !== b.status) return a.status === "running" ? -1 : 1;
      return (cuandoFue(b) ?? "").localeCompare(cuandoFue(a) ?? "");
    });
  const terminadas = misiones
    .filter((m) => !ESTADO[m.status].vivo)
    .sort((a, b) => (cuandoFue(b) ?? "").localeCompare(cuandoFue(a) ?? ""));
  const visibles = todo ? terminadas : terminadas.slice(0, TOPE);

  if (misiones.length === 0) return null;

  return (
    <section>
      <h2 className="text-seccion font-semibold text-ink">Lo que ha hecho</h2>

      {vivas.length > 0 && (
        <ul className="mt-3 space-y-2">
          {vivas.map((m) => (
            <EnCurso key={m.id} m={m} />
          ))}
        </ul>
      )}

      {terminadas.length > 0 && (
        <ul className="mt-2">
          {visibles.map((m) => (
            <Terminada key={m.id} m={m} />
          ))}
        </ul>
      )}
      {terminadas.length > TOPE && (
        <button onClick={() => setTodo((v) => !v)} className="btn btn-quiet btn-sm -ml-3 mt-2">
          {todo ? "Ver menos" : `Ver todo (${terminadas.length})`}
        </button>
      )}
    </section>
  );
}

function EnCurso({ m }: { m: CuaMision }) {
  const est = ESTADO[m.status];
  const adentro = m.status === "running";
  const pasos = m.steps.slice(-4);
  return (
    <li className="rounded-xl bg-panel px-5 py-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="min-w-0 flex-1 truncate text-cuerpo font-medium text-ink">{m.sistema}</span>
        <Marca color={est.marca}>{est.label}</Marca>
        <span className="tnum shrink-0 text-apoyo text-ink-3">
          {adentro ? `Empezó ${haceTiempo(m.startedAt || m.createdAt)}` : haceTiempo(m.createdAt)}
        </span>
      </div>
      <p className="mt-1 text-apoyo text-ink-2">
        {m.resumen || instruccionDe(m) || (adentro ? "Trabajando en el portal…" : "Esperando su turno.")}
      </p>
      {pasos.length > 0 && (
        <ul className="mt-3 space-y-1">
          {pasos.map((s, i) => (
            <li key={i} className={`truncate text-apoyo ${adentro && i === pasos.length - 1 ? "text-ink" : "text-ink-3"}`}>
              {s}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** Lo que trajo, en renglones legibles en vez de un bloque de datos crudos. */
function Trajo({ data }: { data: Record<string, unknown> }) {
  const entradas = Object.entries(data).filter(([k]) => !k.startsWith("_") && k !== "documento_id");
  if (entradas.length === 0) return null;
  const texto = (v: unknown): string =>
    v === null || v === undefined
      ? "sin dato"
      : typeof v === "object"
        ? Object.entries(v as Record<string, unknown>)
            .map(([k, x]) => `${k.replace(/_/g, " ")}: ${texto(x)}`)
            .join(" · ")
        : String(v);
  return (
    <div>
      <p className="eyebrow">Lo que trajo</p>
      <dl className="mt-1.5 space-y-2">
        {entradas.map(([k, v]) => (
          <div key={k}>
            <dt className="text-rotulo text-ink-3">{k.replace(/_/g, " ")}</dt>
            {Array.isArray(v) ? (
              <dd>
                <ul>
                  {v.map((x, i) => (
                    <li key={i} className="break-words text-apoyo text-ink-2">
                      {texto(x)}
                    </li>
                  ))}
                </ul>
              </dd>
            ) : (
              <dd className="break-words text-apoyo text-ink-2">{texto(v)}</dd>
            )}
          </div>
        ))}
      </dl>
    </div>
  );
}

function Terminada({ m }: { m: CuaMision }) {
  const [abierta, setAbierta] = useState(false);
  const [capturas, setCapturas] = useState<string[] | null>(null);
  const [cargando, setCargando] = useState(false);
  const est = ESTADO[m.status];
  const instruccion = instruccionDe(m);

  const abrir = async () => {
    const next = !abierta;
    setAbierta(next);
    if (next && capturas === null && m.evidencia_capturas > 0) {
      setCargando(true);
      try {
        setCapturas((await api.cuaMision(m.id)).evidencia ?? []);
      } catch (e) {
        // Si no bajan, se dice (y se reintenta al volver a abrir).
        toast(`No se pudieron cargar las capturas: ${(e as Error).message}`, "error");
      } finally {
        setCargando(false);
      }
    }
  };

  return (
    <li className="border-b border-line last:border-0">
      <button
        onClick={abrir}
        aria-expanded={abierta}
        className="-mx-3 flex w-[calc(100%+1.5rem)] flex-wrap items-baseline gap-x-4 gap-y-1 rounded-lg px-3 py-3.5 text-left hover:bg-panel"
      >
        <span className="min-w-0 flex-1 basis-56 truncate text-cuerpo font-medium text-ink">{m.sistema}</span>
        <Marca color={est.marca}>{est.label}</Marca>
        <span className="tnum shrink-0 text-apoyo text-ink-3">{fechaHora(cuandoFue(m))}</span>
        <span className="w-full truncate text-apoyo text-ink-3">
          {m.status === "failed" ? m.error : m.resumen || instruccion || "Sin detalle."}
        </span>
      </button>

      <Collapse open={abierta}>
        <div className="space-y-4 pb-5">
          {instruccion && (
            <div>
              <p className="eyebrow">Le pediste</p>
              <p className="mt-1 text-cuerpo text-ink-2">{instruccion}</p>
            </div>
          )}
          {m.status === "failed" && m.error && <p className="text-cuerpo text-danger">{m.error}</p>}
          {m.status === "done" && <Trajo data={m.data ?? {}} />}
          {typeof m.data?.documento_id === "string" && (
            <a
              href={apiUrl(`/v1/documentos/${m.data.documento_id}.pdf`)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block text-cuerpo font-medium text-accent-ink hover:underline"
            >
              Ver PDF
            </a>
          )}
          {m.steps.length > 0 && (
            <div>
              <p className="eyebrow">Paso a paso</p>
              <ul className="mt-1.5 space-y-0.5">
                {m.steps.map((s, i) => (
                  <li key={i} className="truncate text-apoyo text-ink-3">
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {m.evidencia_capturas > 0 && (
            <div>
              <p className="eyebrow">Capturas ({m.evidencia_capturas})</p>
              {cargando ? (
                <Skeleton className="mt-1.5 h-24 w-full" />
              ) : (
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {(capturas ?? []).map((b64, i) => (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      key={i}
                      src={`data:image/png;base64,${b64}`}
                      alt={`Captura ${i + 1}`}
                      className="h-24 w-auto rounded-md"
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </Collapse>
    </li>
  );
}
