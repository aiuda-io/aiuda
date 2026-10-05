"use client";

// Lo que sabe hacer un ayudante, tarea por tarea. Cada renglón contesta las tres
// preguntas del dueño sin abrir nada: qué hace, cuándo, y si algo sale sin que él lo
// apruebe. Su ajuste principal va a la vista; el resto, detrás de "Más ajustes".
import Link from "next/link";
import { useState } from "react";
import type { AiuditaConfig, AiuditaSpec, AiuditasCatalog, Fuente, Perilla } from "@/lib/api";
import { AiuditaIcon, aiuditaTipo } from "@/components/aiudita-icon";
import { Collapse } from "@/components/motion";
import { SecondaryButton, SinEstrenar, inputCls } from "@/components/ui";
import { removeAiudita, setAiudita } from "@/lib/ayudantes-store";
import { toast } from "@/components/toast";
import { rutaAjustes } from "@/lib/ajustes";

/** El catálogo ya trae estas dos frases por tarea (`aiuditas/catalog.py`). Vacías en
 *  las que todavía no funcionan. */
export type Tarea = AiuditaSpec;

type Valor = string | number | boolean;

export function Tareas({
  ayudanteId,
  catalog,
  activos,
  onAgregar,
}: {
  ayudanteId: string;
  catalog: AiuditasCatalog;
  activos: Record<string, AiuditaConfig>;
  onAgregar: () => void;
}) {
  // En el orden del catálogo, que ya agrupa por oficio; solo las que tiene.
  const tareas = (catalog.aiuditas as Tarea[]).filter((a) => a.id in activos);

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-seccion font-semibold text-ink">Lo que sabe hacer</h2>
        <SecondaryButton size="sm" onClick={onAgregar}>
          Agregar aiudita
        </SecondaryButton>
      </div>
      {tareas.length === 0 ? (
        <p className="py-8 text-cuerpo text-ink-2">
          Todavía no sabe hacer nada. Agrégale una aiudita: cada una es una tarea concreta, con sus
          ajustes.
        </p>
      ) : (
        <ul>
          {tareas.map((t) => (
            <TareaFila key={t.id} ayudanteId={ayudanteId} tarea={t} config={activos[t.id]} />
          ))}
        </ul>
      )}
    </section>
  );
}

function TareaFila({
  ayudanteId,
  tarea,
  config,
}: {
  ayudanteId: string;
  tarea: Tarea;
  config: AiuditaConfig;
}) {
  const [abierta, setAbierta] = useState(false);

  const guardar = async (key: string, value: Valor) => {
    try {
      await setAiudita(ayudanteId, tarea.id, { ...config, [key]: value });
      toast("Guardado", "info");
    } catch (e) {
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    }
  };

  const valor = (p: Perilla): Valor => (config != null && p.key in config ? config[p.key] : p.default);
  const valorDe = (key: string): Valor => {
    if (config != null && key in config) return config[key];
    return tarea.perillas.find((x) => x.key === key)?.default ?? "";
  };
  // Un ajuste que depende de otro solo aparece cuando ese otro lo pide.
  const aplica = (p: Perilla) => !p.depende_de || String(valorDe(p.depende_de.key)) === p.depende_de.valor;

  // El ajuste a la vista es el primero de la tarea, con los que dependen de él.
  const principal = tarea.perillas[0];
  const aLaVista = principal
    ? tarea.perillas.filter((p) => p === principal || (p.depende_de?.key === principal.key && aplica(p)))
    : [];
  const resto = tarea.perillas.filter((p) => !aLaVista.includes(p) && aplica(p));

  const reglas = typeof config?.reglas === "string" ? config.reglas : "";
  const fuentes = tarea.fuentes ?? [];
  const fuenteSel = typeof config?._fuente === "string" ? config._fuente : "";
  const masAjustes = resto.length + (fuentes.length > 0 ? 1 : 0) + (tarea.reglas_libres ? 1 : 0);

  return (
    <li className="border-b border-line py-6 last:border-0">
      <div className="flex items-start gap-4">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-fill p-2 text-ink-2">
          <AiuditaIcon id={tarea.id} tipo={aiuditaTipo(tarea.id, tarea.lectura)} className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-cuerpo font-semibold text-ink">{tarea.label}</h3>
          <p className="mt-0.5 max-w-2xl text-cuerpo text-ink-2">{tarea.linea}</p>

          {tarea.live ? (
            <dl className="mt-3 grid max-w-2xl gap-x-6 gap-y-1 sm:grid-cols-[7.5rem_minmax(0,1fr)]">
              {tarea.cuando && (
                <>
                  <dt className="text-rotulo text-ink-3 sm:pt-0.5">Cuándo</dt>
                  <dd className="text-apoyo text-ink">{tarea.cuando}</dd>
                </>
              )}
              {tarea.aprobacion && (
                <>
                  <dt className="text-rotulo text-ink-3 sm:pt-0.5">Tu aprobación</dt>
                  <dd className="text-apoyo text-ink">{tarea.aprobacion}</dd>
                </>
              )}
            </dl>
          ) : (
            <p className="mt-3 text-apoyo text-ink-3">
              Todavía no funciona. Puedes dejarla puesta: no hace nada hasta que esté lista.
            </p>
          )}

          {aLaVista.length > 0 && (
            <div className="mt-5 max-w-2xl space-y-5">
              {aLaVista.map((p) => (
                <PerillaField key={p.key} scope={tarea.id} perilla={p} value={valor(p)} onSave={(v) => guardar(p.key, v)} />
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {masAjustes > 0 && (
              <button
                onClick={() => setAbierta((v) => !v)}
                aria-expanded={abierta}
                className="btn btn-quiet btn-sm -ml-3"
              >
                {abierta ? "Ocultar ajustes" : `Más ajustes (${masAjustes})`}
              </button>
            )}
            <button
              onClick={() => removeAiudita(ayudanteId, tarea.id).catch(() => toast("No se pudo quitar.", "error"))}
              className={`btn btn-quiet btn-sm ${masAjustes > 0 ? "" : "-ml-3"}`}
            >
              Quitar
            </button>
          </div>

          <Collapse open={abierta}>
            <div className="max-w-2xl space-y-5 pt-4">
              {resto.map((p) => (
                <PerillaField key={p.key} scope={tarea.id} perilla={p} value={valor(p)} onSave={(v) => guardar(p.key, v)} />
              ))}
              {fuentes.length > 0 && (
                <FuenteField fuentes={fuentes} value={fuenteSel} onSelect={(k) => guardar("_fuente", k)} />
              )}
              {tarea.reglas_libres && (
                <div>
                  <label htmlFor={`reglas-${tarea.id}`} className="text-cuerpo font-medium text-ink">
                    Reglas de tu negocio
                  </label>
                  <p className="mb-2 text-apoyo text-ink-3">
                    En tus palabras, lo que debe o no debe hacer. Por ejemplo: no menciones recargos.
                  </p>
                  <textarea
                    id={`reglas-${tarea.id}`}
                    defaultValue={reglas}
                    onBlur={(e) => {
                      if (e.target.value !== reglas) guardar("reglas", e.target.value);
                    }}
                    rows={2}
                    className={`${inputCls} resize-y`}
                    placeholder="Escribe aquí tus reglas"
                  />
                </div>
              )}
            </div>
          </Collapse>
        </div>
      </div>
    </li>
  );
}

/** Un ajuste: el control cambia según lo que se ajusta. Se guarda al tocarlo o al
 *  salir del campo, sin botón. */
function PerillaField({
  scope,
  perilla: p,
  value,
  onSave,
}: {
  scope: string;
  perilla: Perilla;
  value: Valor;
  onSave: (v: Valor) => void;
}) {
  const id = `perilla-${scope}-${p.key}`;
  return (
    <div className={p.live ? undefined : "opacity-60"}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <label htmlFor={id} className="text-cuerpo font-medium text-ink">
            {p.label}
          </label>
          {!p.live && <span className="ml-2 text-apoyo text-ink-3">Todavía no funciona</span>}
          {p.ayuda && <p className="text-apoyo text-ink-3">{p.ayuda}</p>}
        </div>
        {p.tipo === "bool" && (
          <button
            id={id}
            onClick={() => onSave(!(value as boolean))}
            role="switch"
            aria-checked={value as boolean}
            className={`relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full ${
              value ? "bg-accent" : "bg-line-strong"
            }`}
          >
            <span
              className={`inline-block h-5 w-5 rounded-full bg-surface transition-transform ${
                value ? "translate-x-[22px]" : "translate-x-0.5"
              }`}
            />
          </button>
        )}
      </div>

      {p.tipo === "enum" ? (
        <div id={id} role="radiogroup" aria-label={p.label} className="mt-2 flex flex-wrap gap-1.5">
          {(p.opciones ?? []).map((o) => {
            const on = value === o.value;
            return (
              <button
                key={o.value}
                role="radio"
                aria-checked={on}
                onClick={() => onSave(o.value)}
                className={`btn btn-sm ${on ? "bg-accent-soft text-accent-ink" : "btn-secondary"}`}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      ) : p.tipo === "numero" ? (
        <div className="mt-2 flex items-center gap-2">
          <input
            id={id}
            key={String(value)}
            type="number"
            defaultValue={value as number}
            min={p.minimo}
            max={p.maximo}
            onBlur={(e) => {
              const n = Number(e.target.value);
              if (e.target.value !== "" && !Number.isNaN(n) && n !== value) onSave(n);
            }}
            className={`${inputCls} tnum !w-24`}
          />
          {p.unidad && <span className="text-cuerpo text-ink-2">{p.unidad}</span>}
        </div>
      ) : p.tipo !== "bool" ? (
        // texto u hora
        <input
          id={id}
          key={String(value)}
          type="text"
          defaultValue={value as string}
          onBlur={(e) => {
            if (e.target.value !== value) onSave(e.target.value);
          }}
          className={`${inputCls} mt-2 max-w-xs`}
        />
      ) : null}
    </div>
  );
}

/** De dónde lee esta tarea: el dueño elige la fuente. Las que ya leen se eligen aquí;
 *  las que faltan llevan a conectarlas. Entrar al portal es una opción real, pero
 *  nadie la ha usado todavía con un portal de verdad, y se dice. */
function FuenteField({
  fuentes,
  value,
  onSelect,
}: {
  fuentes: Fuente[];
  value: string;
  onSelect: (key: string) => void;
}) {
  const hayViva = fuentes.some((f) => f.live);
  return (
    <div>
      <p className="text-cuerpo font-medium text-ink">De dónde lee</p>
      <p className="mb-2 text-apoyo text-ink-3">
        {hayViva
          ? "De aquí saca los datos. Conecta otra fuente para poder cambiarla."
          : "Todavía no hay de dónde leer esto. Conecta una fuente para que funcione."}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        {fuentes.map((f) => {
          const nombre = f.name;
          if (f.live || f.experimental) {
            const on = value === f.key;
            return (
              <button
                key={f.key}
                onClick={() => onSelect(f.key)}
                aria-pressed={on}
                className={`btn btn-sm ${on ? "bg-accent-soft text-accent-ink" : "btn-secondary"}`}
              >
                {nombre}
                {f.experimental && <SinEstrenar />}
              </button>
            );
          }
          return (
            <Link
              key={f.key}
              href={rutaAjustes("conexiones", f.key)}
              className="btn btn-quiet btn-sm"
            >
              Conectar {nombre}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
