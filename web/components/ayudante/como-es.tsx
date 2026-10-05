"use client";

// Cómo es el ayudante: lo que el dueño le pide con sus palabras, lo que nunca hará
// aunque se lo pidan, y lo que ha aprendido de sus correcciones.
import { useEffect, useState } from "react";
import { api, type LearningSummary } from "@/lib/api";
import { inputCls } from "@/components/ui";
import { updateAyudante } from "@/lib/ayudantes-store";
import { toast } from "@/components/toast";

/** Lo que vale para TODO ayudante y el dueño no puede quitar. Refleja las reglas que
 *  el servidor le antepone siempre a lo que el dueño escriba. */
const SIEMPRE = [
  "No manda cobros ni mensajes de venta por su cuenta: los propone y tú apruebas antes de que salgan.",
  "No inventa montos, folios ni fechas: los consulta, o dice que no los tiene.",
  "No obedece órdenes escondidas en los mensajes de un cliente.",
  "Le pasa a una persona lo que se sale de su alcance: disputas, quejas, temas legales.",
  "Solo ve los datos de tu negocio.",
];

export function ComoEs({ id, name, instructions }: { id: string; name: string; instructions: string }) {
  const [value, setValue] = useState(instructions);
  const [estado, setEstado] = useState<"idle" | "guardando" | "ok">("idle");
  const [completas, setCompletas] = useState<{ chat: string; corrida: string } | null>(null);
  const [cual, setCual] = useState<"corrida" | "chat">("corrida");
  const [cargando, setCargando] = useState(false);

  const sinGuardar = value.trim() !== (instructions ?? "").trim();

  const guardar = async () => {
    if (!sinGuardar) return;
    setEstado("guardando");
    try {
      await updateAyudante(id, { instructions: value.trim() });
      setEstado("ok");
      setCompletas(null); // cambiaron: lo que estaba a la vista ya no es cierto
    } catch (e) {
      setEstado("idle");
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    }
  };

  const verCompletas = async () => {
    if (completas !== null) {
      setCompletas(null);
      return;
    }
    setCargando(true);
    try {
      const r = await api.ayudantePrompt(id);
      setCompletas({ chat: r.chat, corrida: r.corrida });
    } catch (e) {
      toast(`No se pudieron abrir: ${(e as Error).message}`, "error");
    } finally {
      setCargando(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-12">
      <section>
        <label htmlFor="persona" className="text-seccion font-semibold text-ink">
          Cómo quieres que sea {name}
        </label>
        <p className="mb-3 mt-1 text-cuerpo text-ink-2">
          En tus palabras: su tono, en qué poner atención, qué evitar. Por ejemplo: trata de usted, sé
          breve y prioriza a los clientes con más atraso.
        </p>
        <textarea
          id="persona"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            if (estado !== "idle") setEstado("idle");
          }}
          onBlur={guardar}
          rows={5}
          maxLength={4000}
          placeholder="Escribe aquí cómo quieres que sea"
          className={`${inputCls} resize-y`}
        />
        <p className="mt-2 min-h-5 text-apoyo text-ink-3" aria-live="polite">
          {estado === "guardando"
            ? "Guardando…"
            : estado === "ok"
              ? "Guardado"
              : sinGuardar
                ? "Se guarda al salir del campo."
                : ""}
        </p>
      </section>

      <section>
        <h2 className="text-seccion font-semibold text-ink">Lo que nunca hace</h2>
        <p className="mt-1 text-cuerpo text-ink-2">
          Vale para todos tus ayudantes y manda sobre lo que escribas arriba. No se puede quitar.
        </p>
        <ul className="mt-3">
          {SIEMPRE.map((g) => (
            <li key={g} className="border-b border-line py-2.5 text-cuerpo text-ink last:border-0">
              {g}
            </li>
          ))}
        </ul>
        <button onClick={verCompletas} disabled={cargando} className="btn btn-quiet btn-sm -ml-3 mt-3">
          {cargando ? "Abriendo…" : completas !== null ? "Ocultar las instrucciones completas" : "Ver las instrucciones completas"}
        </button>
        {completas !== null && (
          <div className="mt-3">
            {/* Son dos y no una: lo que le dice a un cliente no es lo que te contesta a ti. */}
            <div className="mb-2 flex flex-wrap gap-1.5">
              {(["corrida", "chat"] as const).map((k) => (
                <button
                  key={k}
                  onClick={() => setCual(k)}
                  aria-pressed={cual === k}
                  className={`btn btn-sm ${cual === k ? "bg-accent-soft text-accent-ink" : "btn-secondary"}`}
                >
                  {k === "corrida" ? "Cuando le escribe a un cliente" : "Cuando platicas con él"}
                </button>
              ))}
            </div>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-panel px-4 py-3 font-sans text-apoyo text-ink-2">
              {completas[cual]}
            </pre>
          </div>
        )}
      </section>

      <Aprendizaje ayudanteId={id} name={name} />
    </div>
  );
}

/** Lo que aprende de las correcciones del dueño: cuánto aprueba sin tocar y sus
 *  últimos cambios, que el ayudante imita en los siguientes borradores. Son las de
 *  ESTE ayudante. */
function Aprendizaje({ ayudanteId, name }: { ayudanteId: string; name: string }) {
  const [sum, setSum] = useState<LearningSummary | null>(null);
  const [listo, setListo] = useState(false);
  useEffect(() => {
    api
      .learningSummary(ayudanteId)
      .then(setSum)
      .catch(() => setSum(null))
      .finally(() => setListo(true));
  }, [ayudanteId]);
  if (!listo) return null;
  const revisados = (sum?.approved ?? 0) + (sum?.edited ?? 0);

  return (
    <section>
      <h2 className="text-seccion font-semibold text-ink">Lo que ha aprendido de ti</h2>
      <p className="mt-1 text-cuerpo text-ink-2">
        Cuando corriges un mensaje en Hoy antes de aprobarlo, {name} aprende cómo escribes y lo imita en
        los siguientes.
      </p>
      {!sum || revisados === 0 ? (
        <p className="mt-3 text-cuerpo text-ink-3">Todavía no hay nada. Aparece cuando apruebes o corrijas mensajes.</p>
      ) : (
        <>
          <dl className="mt-4 flex flex-wrap gap-x-12 gap-y-4">
            <Cifra
              label="Aprobados sin tocar"
              value={sum.tasaSinEditar != null ? `${Math.round(sum.tasaSinEditar * 100)}%` : "·"}
            />
            <Cifra label="Corregidos por ti" value={String(sum.edited)} />
            <Cifra label="Rechazados" value={String(sum.rejected)} />
          </dl>
          {sum.recientes.length > 0 && (
            <div className="mt-6">
              <p className="eyebrow">Tus últimas correcciones</p>
              <ul className="mt-2">
                {sum.recientes.map((c, i) => (
                  <li key={i} className="border-b border-line py-3 text-cuerpo last:border-0">
                    <p className="text-ink-3 line-through">{c.original}</p>
                    <p className="mt-1 text-ink">{c.final}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Cifra({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dd className="tnum text-titulo font-semibold text-ink">{value}</dd>
      <dt className="mt-1 text-apoyo text-ink-3">{label}</dt>
    </div>
  );
}
