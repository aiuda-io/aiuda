"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { ErrorState, PrimaryButton, SecondaryButton, Skeleton, Tabs } from "@/components/ui";
import { AnimatedNumber } from "@/components/motion";
import { Avatar } from "@/components/avatar";
import { AiuditaIcon, TIPO_META, aiuditaTipo } from "@/components/aiudita-icon";
import { AiuditaPicker } from "@/components/aiudita-picker";
import { Chatter, type ChatterMessage } from "@/components/chatter";
import {
  deleteAyudante,
  refreshAyudante,
  removeAiudita,
  setAiudita,
  updateAyudante,
  useAyudante,
  useCatalog,
} from "@/lib/ayudantes-store";
import { api, type AiuditaConfig, type AiuditaSpec, type AiuditasCatalog, type CorridaAyudante, type Fuente, type LearningSummary, type Perilla } from "@/lib/api";
import {
  ACCENT_COLORS,
  SYMBOL_KEYS,
  PART_META,
  PART_KEYS,
  normalizeAppearance,
  type Appearance,
  type PartCategory,
} from "@/lib/look";
import { perfilColor, perfilesActivos } from "@/lib/perfiles";
import { RoleIcon } from "@/components/role-icon";
import { toast } from "@/components/toast";

export default function AyudanteDetailPage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <AyudanteDetail />
    </Suspense>
  );
}

function AyudanteDetail() {
  const id = useSearchParams().get("id") ?? "";
  const router = useRouter();
  const { ayudante, loading, error, retry } = useAyudante(id);
  const { catalog, error: catError, retry: catRetry } = useCatalog();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const reciénCreado = useSearchParams().get("nuevo") === "1";
  const [guiaCerrada, setGuiaCerrada] = useState(false);
  const [tab, setTab] = useState<"trabajo" | "personalidad" | "aprendizaje">("trabajo");
  const [pickerOpen, setPickerOpen] = useState(false);

  if (error || catError) {
    return (
      <div className="min-w-0">
        <ErrorState
          message={error ?? catError ?? ""}
          retry={error ? retry : catRetry}
        />
      </div>
    );
  }
  if (loading || !catalog) {
    return (
      <div className="min-w-0 space-y-3">
        <Skeleton className="h-14 w-full rounded-lg" />
        <Skeleton className="h-32 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
    );
  }
  if (!ayudante) {
    return (
      <div className="min-w-0">
        <ErrorState message="Este ayudante ya no existe o el link está incompleto. Regresa a tu equipo y elígelo de la lista." />
      </div>
    );
  }

  const app = normalizeAppearance(ayudante.appearance);
  const activos = ayudante.aiuditas; // { aiudita_id: config }
  const activeCount = Object.keys(activos).length;
  const setAppearance = (patch: Partial<Appearance>) =>
    updateAyudante(id, { appearance: { ...ayudante.appearance, ...patch } });

  // Perfiles con al menos una aiudita activa: definen el "rol" del ayudante en una línea.
  const perfiles = perfilesActivos(catalog, activos);
  // Fuentes reales de las que lee (elegidas o vivas), para mostrarlas de un vistazo.
  const fuentes = fuentesConectadas(catalog, activos);

  const remove = async () => {
    await deleteAyudante(id);
    router.push("/ayudantes");
  };

  return (
    // En «Trabajo» la ficha se ancla al alto de la ventana (como el maestro-detalle
    // de Conversaciones): el encabezado y las pestañas no se mueven y el chat llena
    // lo que queda, así el campo para escribir SIEMPRE se ve sin scrollear. En las
    // otras pestañas la página fluye normal, que es lo que pide su contenido largo.
    <div
      className={`min-w-0 ${
        tab === "trabajo" ? "lg:flex lg:h-[calc(100dvh-8.75rem)] lg:min-h-[520px] lg:flex-col" : ""
      }`}
    >
      {/* Encabezado de identidad: el ayudante como un carácter (mascota, rol en una
          línea, nivel real y las fuentes que lee), no un recuadro de settings. */}
      <header className="reveal mb-5 shrink-0 rounded-xl border border-line bg-surface px-5 py-4">
        <div className="flex items-start gap-4">
          <Avatar name={ayudante.name} size={56} {...app} className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <input
              defaultValue={ayudante.name}
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && v !== ayudante.name) {
                  updateAyudante(id, { name: v }).then(() => toast("Nombre guardado", "info"));
                }
              }}
              aria-label="Nombre del ayudante"
              className="-ml-1 w-full max-w-xs rounded-md border border-transparent bg-transparent px-1 py-0.5 text-titulo font-semibold tracking-tight text-ink hover:border-line focus:border-accent focus:bg-surface focus:outline-none"
            />
            <p className="mt-0.5 px-1 text-cuerpo text-ink-2">
              {perfiles.length > 0
                ? perfiles.map((p) => p.name).join(" · ")
                : "Sin oficio todavía · elige qué quieres que haga"}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 px-1">
              {/* Nivel y acciones REALES: los deriva el backend de sus propuestas en la
                  bandeja (trabajar sube, rechazado no cuenta). Info, no un juego. */}
              <span className="rounded bg-accent-soft px-1.5 py-px text-sello font-semibold text-accent-ink">
                {ayudante.nivel.nivel}
              </span>
              <span className="rounded border border-line px-1.5 py-px text-sello text-ink-2">
                <span className="tnum">{ayudante.acciones.total}</span> acci
                {ayudante.acciones.total === 1 ? "ón" : "ones"}
              </span>
              <span className="rounded border border-line px-1.5 py-px text-sello text-ink-2">
                <span className="tnum">{activeCount}</span> aiudita{activeCount === 1 ? "" : "s"}
              </span>
              {fuentes.length > 0 && (
                <>
                  <span aria-hidden className="text-line-strong">
                    ·
                  </span>
                  {fuentes.map((f) => (
                    <span
                      key={f.key}
                      title={f.live ? `Lee de ${f.name}` : `${f.name}: por conectar`}
                      className="inline-flex items-center gap-1.5 rounded border border-line px-1.5 py-px text-sello text-ink-2"
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ background: f.live ? "var(--color-ok)" : "var(--color-line-strong)" }}
                      />
                      {f.name}
                    </span>
                  ))}
                </>
              )}
            </div>
          </div>
          {confirmDelete ? (
            <span className="flex shrink-0 items-center gap-2">
              <button
                onClick={remove}
                className="rounded-md border border-danger/40 bg-danger-soft px-3 py-1.5 text-cuerpo font-medium text-danger transition-colors hover:bg-danger hover:text-surface"
              >
                Eliminar
              </button>
              <SecondaryButton onClick={() => setConfirmDelete(false)}>Cancelar</SecondaryButton>
            </span>
          ) : (
            <SecondaryButton onClick={() => setConfirmDelete(true)}>Eliminar</SecondaryButton>
          )}
        </div>
      </header>

      {reciénCreado && !guiaCerrada && (
        <div className="mb-4 flex shrink-0 items-start gap-3 rounded-lg border border-accent/30 bg-accent-soft px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-seccion font-semibold text-accent-ink">
              {ayudante.name} está listo
            </p>
            <p className="mt-0.5 text-cuerpo text-ink-2">
              {activeCount === 0
                ? "Con «Agregar aiudita» le eliges lo que quieres que haga; cada una se explica y se configura a tu negocio."
                : "Ahora ajusta sus aiuditas a tu negocio: de dónde lee, el tono y tus reglas. Ábrelas en «Lo que sabe hacer»."}
            </p>
            <p className="mt-1.5 text-cuerpo text-ink-3">
              Corre con tu propia IA.{" "}
              <Link href="/proveedor" className="font-medium text-accent-ink hover:underline">
                Conecta tu proveedor
              </Link>
              .
            </p>
          </div>
          <button
            onClick={() => setGuiaCerrada(true)}
            className="shrink-0 rounded-md px-2 py-1 text-sello font-medium text-accent-ink/80 transition-colors hover:text-accent-ink"
          >
            Entendido
          </button>
        </div>
      )}

      {/* Un ayudante tiene tres caras: su trabajo, su personalidad, lo que aprende.
          Cada una es un espacio propio · no una pila de todo a la vez. */}
      <div className="shrink-0">
        <Tabs
          tabs={[
            { key: "trabajo", label: "Trabajo", count: activeCount || undefined },
            { key: "personalidad", label: "Personalidad" },
            { key: "aprendizaje", label: "Aprendizaje" },
          ]}
          active={tab}
          onChange={(k) => setTab(k as typeof tab)}
        />
      </div>

      {tab === "trabajo" && (
        // Espacio de trabajo de dos columnas: a la izquierda lo que sabe hacer (sus
        // habilidades equipadas), a la derecha la superficie de trabajo (correr + chat).
        // En móvil se apila con el chat primero · es cómo se trabaja con él.
        <div
          key="trabajo"
          className="flex min-h-0 flex-col-reverse gap-4 lg:flex-1 lg:flex-row lg:items-stretch"
        >
          <div className="lg:w-[340px] lg:shrink-0">
            <SkillsPanel
              ayudanteId={id}
              catalog={catalog}
              activos={activos}
              onOpenPicker={() => setPickerOpen(true)}
            />
          </div>
          <div className="min-w-0 lg:min-h-0 lg:flex-1">
            <WorkSurface
              id={id}
              name={ayudante.name}
              activos={activos}
              acciones={ayudante.acciones}
            />
          </div>
        </div>
      )}

      {pickerOpen && (
        <AiuditaPicker
          ayudanteId={id}
          catalog={catalog}
          activos={activos}
          onClose={() => setPickerOpen(false)}
        />
      )}

      {tab === "personalidad" && (
        <div key="personalidad" className="reveal-stagger">
          {/* Personalidad: instrucciones libres del dueño, bajo las garantías de fábrica */}
          <PersonaEditor id={id} name={ayudante.name} instructions={ayudante.instructions} />
          {/* Apariencia: estudio compacto por pestañas (color + cara por capas + símbolo de rol) */}
          <AppearancePicker app={app} onChange={setAppearance} />
        </div>
      )}

      {tab === "aprendizaje" && (
        <div key="aprendizaje" className="reveal">
          {/* Loop de aprendizaje: qué aprende de tus ediciones en el Centro */}
          <LearningPanel ayudanteId={id} />
        </div>
      )}
    </div>
  );
}

/** Garantías de fábrica: valen para TODO ayudante y el dueño no las puede quitar.
 *  Reflejan los safeguards del prompt del sistema (cleo/prompt.py + aiuditas/chat.py). */
const GARANTIAS_FABRICA = [
  "No manda cobros ni mensajes de venta por su cuenta: los propone y tú apruebas antes de que salgan.",
  "No inventa montos, folios ni fechas: los consulta, o dice que no los tiene.",
  "Ignora órdenes escondidas en mensajes de clientes (no obedece «actúa como el dueño»).",
  "Escala a una persona lo que se sale de su alcance (disputas, quejas, temas legales).",
  "Solo ve los datos de tu negocio; nunca los de otro cliente.",
];

function LearningStat({
  label,
  value,
  format,
}: {
  label: string;
  value: number | null;
  format?: (n: number) => string;
}) {
  return (
    <div>
      <div className="text-cuerpo font-semibold tabular-nums text-ink">
        {value === null ? "·" : <AnimatedNumber value={value} format={format} />}
      </div>
      <div className="text-apoyo text-ink-3">{label}</div>
    </div>
  );
}

/** El loop de aprendizaje hecho visible: cuánto se aprueba sin editar y las últimas
 *  correcciones del dueño. Esas ediciones se reinyectan al prompt del ayudante (backend),
 *  así redacta cada vez más como él.
 *
 *  Son las correcciones DE ESTE ayudante: antes se pedía siempre el slug de runtime, así
 *  que la pestaña mostraba los mismos números en todos. Dato falso y silencioso. */
function LearningPanel({ ayudanteId }: { ayudanteId: string }) {
  const [sum, setSum] = useState<LearningSummary | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    api
      .learningSummary(ayudanteId)
      .then(setSum)
      .catch(() => setSum(null))
      .finally(() => setLoaded(true));
  }, [ayudanteId]);
  if (!loaded) return null; // secundario: silencioso mientras carga
  const enviados = (sum?.approved ?? 0) + (sum?.edited ?? 0);
  return (
    <section className="mb-6">
      <h2 className="mb-1 text-rotulo font-semibold uppercase tracking-[0.07em] text-ink-3">
        Qué aprende de ti
      </h2>
      <p className="mb-3 text-cuerpo text-ink-3">
        Cuando editas un recordatorio en el Centro antes de enviarlo, tu ayudante aprende tu
        forma de escribir e imita esos cambios en los siguientes borradores.
      </p>
      {!sum || enviados === 0 ? (
        <div className="rounded-lg border border-line bg-surface px-4 py-3 text-cuerpo text-ink-3">
          Aún no hay señales. Cuando apruebes o edites recordatorios en el Centro, aquí verás
          qué está aprendiendo.
        </div>
      ) : (
        <div className="rounded-lg border border-line bg-surface">
          <div className="flex flex-wrap gap-x-8 gap-y-2 border-b border-line/60 px-4 py-3">
            <LearningStat
              label="Aprobados sin editar"
              value={sum.tasaSinEditar != null ? sum.tasaSinEditar * 100 : null}
              format={(n) => `${Math.round(n)}%`}
            />
            <LearningStat label="Editados por ti" value={sum.edited} />
            <LearningStat label="Rechazados" value={sum.rejected} />
          </div>
          {sum.recientes.length > 0 && (
            <div className="px-4 py-3">
              <p className="mb-2 text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
                Tus últimas correcciones
              </p>
              <ul className="space-y-2.5">
                {sum.recientes.map((c, i) => (
                  <li key={i} className="text-cuerpo leading-relaxed">
                    <p className="text-ink-3 line-through decoration-ink-3/40">{c.original}</p>
                    <p className="text-ink">{c.final}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** Personalidad e instrucciones: texto libre del dueño que define tono y foco. Se inyecta
 *  DEBAJO de las garantías de fábrica (agrega, nunca las contradice). Con vista previa del
 *  prompt real que corre · la fuente de verdad la arma el backend, no el front. */
function PersonaEditor({
  id,
  name,
  instructions,
}: {
  id: string;
  name: string;
  instructions: string;
}) {
  const [value, setValue] = useState(instructions);
  const [estado, setEstado] = useState<"idle" | "guardando" | "ok">("idle");
  const [verGarantias, setVerGarantias] = useState(false);
  const [prompt, setPrompt] = useState<{ chat: string; corrida: string } | null>(null);
  const [promptTab, setPromptTab] = useState<"corrida" | "chat">("corrida");
  const [cargandoPrompt, setCargandoPrompt] = useState(false);

  const dirty = value.trim() !== (instructions ?? "").trim();

  const guardar = async () => {
    if (!dirty) return;
    setEstado("guardando");
    await updateAyudante(id, { instructions: value.trim() });
    setEstado("ok");
    setPrompt(null); // el prompt cambió: invalida la vista previa
  };

  const verPrompt = async () => {
    if (prompt !== null) {
      setPrompt(null);
      return;
    }
    setCargandoPrompt(true);
    try {
      const r = await api.ayudantePrompt(id);
      setPrompt({ chat: r.chat, corrida: r.corrida });
    } finally {
      setCargandoPrompt(false);
    }
  };

  return (
    <section className="mb-6">
      <h2 className="mb-1 text-rotulo font-semibold uppercase tracking-[0.07em] text-ink-3">
        Personalidad e instrucciones
      </h2>
      <div className="rounded-lg border border-line bg-surface px-4 py-3.5">
        <label htmlFor="persona" className="text-cuerpo font-medium text-ink">
          Cómo quieres que sea {name}
        </label>
        <p className="mb-2 mt-0.5 text-apoyo leading-relaxed text-ink-3">
          En tus palabras: su tono, en qué poner atención, qué evitar. Ej: «Trata de usted, sé
          breve y cálido, y prioriza a los clientes con más atraso.» Esto se suma a lo que ya
          sabe hacer; las garantías de fábrica siguen mandando.
        </p>
        <textarea
          id="persona"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            if (estado !== "idle") setEstado("idle");
          }}
          onBlur={guardar}
          rows={4}
          maxLength={4000}
          placeholder="Escribe aquí la personalidad y las instrucciones de tu ayudante…"
          className="w-full resize-y rounded-md border border-line bg-bg px-3 py-2 text-cuerpo leading-relaxed text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
        />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-apoyo text-ink-3" aria-live="polite">
            {estado === "guardando"
              ? "Guardando…"
              : estado === "ok"
                ? "Guardado"
                : dirty
                  ? "Sin guardar · sal del campo para guardar"
                  : ""}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setVerGarantias((v) => !v)}
              className="rounded-md border border-line px-2.5 py-1 text-sello font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
            >
              {verGarantias ? "Ocultar garantías" : "Garantías de fábrica"}
            </button>
            <button
              onClick={verPrompt}
              disabled={cargandoPrompt}
              className="rounded-md border border-line px-2.5 py-1 text-sello font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
            >
              {cargandoPrompt ? "Cargando…" : prompt !== null ? "Ocultar prompt" : "Ver el prompt final"}
            </button>
          </div>
        </div>

        {verGarantias && (
          <div className="mt-3 rounded-md border border-line/70 bg-bg px-3 py-2.5">
            <p className="mb-1.5 text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
              No se pueden quitar
            </p>
            <ul className="space-y-1">
              {GARANTIAS_FABRICA.map((g) => (
                <li key={g} className="flex gap-2 text-apoyo leading-relaxed text-ink-2">
                  <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-3" />
                  {g}
                </li>
              ))}
            </ul>
          </div>
        )}

        {prompt !== null && (
          <div className="mt-3">
            {/* Son dos y no uno: lo que le dice a un CLIENTE no es lo que te contesta
                a ti. Antes esta vista enseñaba el de chat rotulado como "el final". */}
            <div className="mb-1.5 flex items-center gap-3">
              <p className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
                Prompt del sistema
              </p>
              <div className="flex gap-1">
                {(["corrida", "chat"] as const).map((k) => (
                  <button
                    key={k}
                    onClick={() => setPromptTab(k)}
                    className={`rounded px-1.5 py-px text-sello font-medium transition-colors ${
                      promptTab === k
                        ? "bg-accent-soft text-accent-ink"
                        : "text-ink-3 hover:text-ink-2"
                    }`}
                  >
                    {k === "corrida" ? "Cuando le escribe a un cliente" : "Cuando platicas con él"}
                  </button>
                ))}
              </div>
            </div>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-line/70 bg-bg px-3 py-2.5 text-apoyo leading-relaxed text-ink-2">
              {prompt[promptTab]}
            </pre>
          </div>
        )}
      </div>
    </section>
  );
}

/** Fuentes reales de las que lee el ayudante: la elegida por aiudita (config._fuente) o,
 *  si no eligió, la primera viva. Dedup por clave. Honesto: el punto dice viva vs por conectar. */
function fuentesConectadas(catalog: AiuditasCatalog, activos: Record<string, AiuditaConfig>): Fuente[] {
  const vistas = new Map<string, Fuente>();
  for (const [aiuditaId, config] of Object.entries(activos)) {
    const spec = catalog.aiuditas.find((a) => a.id === aiuditaId);
    if (!spec?.fuentes?.length) continue;
    const sel = typeof config._fuente === "string" ? config._fuente : "";
    const efectiva = spec.fuentes.find((f) => f.key === sel) ?? spec.fuentes.find((f) => f.live);
    if (efectiva && !vistas.has(efectiva.key)) vistas.set(efectiva.key, efectiva);
  }
  return [...vistas.values()];
}

function Caret({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`h-4 w-4 shrink-0 text-ink-3 transition-transform ${open ? "rotate-90" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 4l4 4-4 4" />
    </svg>
  );
}

/** Panel izquierdo: lo que el ayudante SABE HACER. Sus aiuditas activas como lista compacta
 *  (cada una acordeón con su config en línea) + un botón que abre el picker. No repite el
 *  catálogo completo: eso vive en el picker. */
function SkillsPanel({
  ayudanteId,
  catalog,
  activos,
  onOpenPicker,
}: {
  ayudanteId: string;
  catalog: AiuditasCatalog;
  activos: Record<string, AiuditaConfig>;
  onOpenPicker: () => void;
}) {
  // Orden del catálogo (agrupa por perfil de forma natural), solo las activas.
  const specs = catalog.aiuditas.filter((a) => a.id in activos);
  return (
    // Llena la columna: la lista scrollea por dentro y «Agregar aiudita» queda
    // siempre a la vista, aunque tenga muchas.
    <div className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface lg:h-full">
      <div className="flex shrink-0 items-center justify-between border-b border-line px-4 py-3">
        <h2 className="text-rotulo font-semibold uppercase tracking-[0.07em] text-ink-3">
          Lo que sabe hacer
        </h2>
        {specs.length > 0 && <span className="tnum text-apoyo text-ink-3">{specs.length}</span>}
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {specs.length === 0 ? (
          <p className="px-1 py-6 text-center text-cuerpo leading-relaxed text-ink-3">
            Todavía no sabe hacer nada. Agrégale una aiudita para empezar; cada una se explica y
            se ajusta a tu negocio.
          </p>
        ) : (
          specs.map((spec) => (
            <AiuditaRow
              key={spec.id}
              ayudanteId={ayudanteId}
              spec={spec}
              config={activos[spec.id]}
              onRemove={() => removeAiudita(ayudanteId, spec.id)}
            />
          ))
        )}
      </div>
      <div className="shrink-0 border-t border-line/60 p-3">
        <button
          onClick={onOpenPicker}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-line-strong px-3 py-2.5 text-cuerpo font-medium text-accent-ink transition-colors hover:border-accent hover:bg-accent-soft"
        >
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M8 3v10M3 8h10" />
          </svg>
          Agregar aiudita
        </button>
      </div>
    </div>
  );
}

/** Una aiudita equipada, en formato fila/acordeón: cabecera con icono, nombre, estado
 *  (Lista/Por conectar) y tipo (Consulta/Actúa/Envía); al abrir, su config en línea
 *  (de dónde lee, perillas, reglas) y el botón para quitarla. Misma lógica de
 *  configuración de antes, en un envase compacto para el panel izquierdo. */
function AiuditaRow({
  ayudanteId,
  spec,
  config,
  onRemove,
}: {
  ayudanteId: string;
  spec: AiuditaSpec;
  config: AiuditaConfig;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const tipo = aiuditaTipo(spec.id, spec.lectura);
  const tipoMeta = TIPO_META[tipo];
  const color = perfilColor(spec.perfil);

  const guardar = (key: string, value: string | number | boolean) =>
    setAiudita(ayudanteId, spec.id, { ...config, [key]: value });

  const valor = (p: Perilla): string | number | boolean =>
    key_in(config, p.key) ? config[p.key] : p.default;

  // Perilla visible solo si su dependencia se cumple.
  const visible = (p: Perilla): boolean =>
    !p.depende_de || String(valor_de(config, spec, p.depende_de.key)) === p.depende_de.valor;

  const reglas = typeof config.reglas === "string" ? config.reglas : "";
  const fuentes = spec.fuentes ?? [];
  const fuenteSel = typeof config._fuente === "string" ? config._fuente : "";
  const hayConfig = fuentes.length > 0 || spec.perillas.length > 0 || spec.reglas_libres;

  return (
    <div className={`rounded-lg border bg-surface transition-colors ${open ? "border-line-strong" : "border-line"}`}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left"
      >
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
          style={{ background: `${color}1f`, color }}
        >
          <AiuditaIcon id={spec.id} tipo={tipo} className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-cuerpo font-medium text-ink">{spec.label}</span>
          <span className="mt-0.5 flex items-center gap-2 text-apoyo">
            <span
              className="inline-flex items-center gap-1 font-semibold"
              style={{ color: spec.live ? "var(--color-ok)" : "var(--color-ink-3)" }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: spec.live ? "var(--color-ok)" : "var(--color-line-strong)" }}
              />
              {spec.live ? "Lista" : "Por conectar"}
            </span>
            <span aria-hidden className="text-line">
              ·
            </span>
            <span className="font-semibold" style={{ color: tipoMeta.ink }}>
              {tipoMeta.label}
            </span>
          </span>
        </span>
        <Caret open={open} />
      </button>

      {open && (
        <div className="space-y-3 border-t border-line/60 px-3 py-3">
          {hayConfig ? (
            <>
              {fuentes.length > 0 && (
                <FuenteField fuentes={fuentes} value={fuenteSel} onSelect={(k) => guardar("_fuente", k)} />
              )}
              {spec.perillas.filter(visible).map((p) => (
                <PerillaField key={p.key} perilla={p} value={valor(p)} onSave={(v) => guardar(p.key, v)} />
              ))}
              {spec.reglas_libres && (
                <div>
                  <label className="text-cuerpo font-medium text-ink">Reglas de tu negocio</label>
                  <p className="mb-1 text-apoyo text-ink-3">
                    En tus palabras, lo que debe o no debe hacer. Ej: «no menciones recargos».
                  </p>
                  <textarea
                    defaultValue={reglas}
                    onBlur={(e) => {
                      if (e.target.value !== reglas) guardar("reglas", e.target.value);
                    }}
                    rows={2}
                    className="w-full resize-y rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
                    placeholder="Escribe aquí tus reglas…"
                  />
                </div>
              )}
            </>
          ) : (
            <p className="text-apoyo leading-relaxed text-ink-3">{spec.linea}</p>
          )}
          <div className="flex justify-end pt-1">
            <button
              onClick={onRemove}
              className="rounded-md border border-line px-2 py-1 text-sello font-medium text-ink-2 transition-colors hover:border-danger/40 hover:text-danger"
            >
              Quitar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Una perilla: el control cambia según su tipo. */
function PerillaField({
  perilla: p,
  value,
  onSave,
}: {
  perilla: Perilla;
  value: string | number | boolean;
  onSave: (v: string | number | boolean) => void;
}) {
  const muted = !p.live;
  return (
    <div className={muted ? "opacity-70" : undefined}>
      <div className="flex items-center gap-2">
        <label className="text-cuerpo font-medium text-ink">{p.label}</label>
        {!p.live && (
          <span className="rounded bg-line/50 px-1.5 py-px text-sello font-medium text-ink-3">
            por conectar
          </span>
        )}
      </div>
      {p.ayuda && <p className="mb-1 text-apoyo text-ink-3">{p.ayuda}</p>}

      {p.tipo === "bool" ? (
        <button
          onClick={() => onSave(!(value as boolean))}
          role="switch"
          aria-checked={value as boolean}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            value ? "bg-accent" : "bg-line"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-surface transition-transform ${
              value ? "translate-x-4" : "translate-x-0.5"
            }`}
          />
        </button>
      ) : p.tipo === "enum" ? (
        <div className="flex flex-wrap gap-1.5">
          {(p.opciones ?? []).map((o) => (
            <button
              key={o.value}
              onClick={() => onSave(o.value)}
              className={`rounded-md px-2.5 py-1 text-sello font-medium transition-colors ${
                value === o.value
                  ? "bg-accent-soft text-accent-ink"
                  : "border border-line text-ink-2 hover:border-line-strong hover:text-ink"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      ) : p.tipo === "numero" ? (
        <div className="flex items-center gap-2">
          <input
            type="number"
            defaultValue={value as number}
            min={p.minimo}
            max={p.maximo}
            onBlur={(e) => {
              const n = Number(e.target.value);
              if (!Number.isNaN(n) && n !== value) onSave(n);
            }}
            className="w-24 rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink focus:border-accent focus:outline-none"
          />
          {p.unidad && <span className="text-cuerpo text-ink-3">{p.unidad}</span>}
        </div>
      ) : (
        // texto / hora
        <input
          type="text"
          defaultValue={value as string}
          onBlur={(e) => {
            if (e.target.value !== value) onSave(e.target.value);
          }}
          className="w-full max-w-xs rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
        />
      )}
    </div>
  );
}

/** Logo de una fuente: imagen propia si la tiene, si no un punto de su color. */
function FuenteLogo({ f, muted }: { f: Fuente; muted?: boolean }) {
  if (f.logo) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={f.logo} alt="" className={`h-3.5 w-3.5 object-contain ${muted ? "opacity-50 grayscale" : ""}`} />;
  }
  return (
    <span
      className="h-2.5 w-2.5 rounded-full"
      style={{ background: f.color, opacity: muted ? 0.5 : 1 }}
    />
  );
}

/** "De dónde lee": el dueño elige la fuente de esta capacidad. Es lo que vuelve a
 *  aiuda una capa de acción configurable (no un ERP de fuente fija). Honesto: las
 *  fuentes vivas son seleccionables; CUA (sin conector API) es seleccionable pero
 *  experimental; las demás enlazan a Integraciones para conectarlas. */
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
  const hayCua = fuentes.some((f) => f.experimental);
  return (
    <div>
      <label className="text-cuerpo font-medium text-ink">De dónde lee</label>
      <p className="mb-1.5 text-apoyo text-ink-3">
        {hayViva
          ? "La fuente de esta capacidad. Conecta otra para poder cambiarla."
          : hayCua
            ? "Sin conector API todavía: puedes leer del portal con un agente de cómputo (CUA), o conectar una fuente."
            : "Esta capacidad leerá de aquí en cuanto lo conectes."}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {fuentes.map((f) =>
          f.live || f.experimental ? (
            <button
              key={f.key}
              onClick={() => onSelect(f.key)}
              title={
                f.experimental
                  ? "Un agente de cómputo opera el portal. Experimental: aún no ejecuta en este entorno."
                  : undefined
              }
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sello font-medium transition-colors ${
                value === f.key
                  ? "bg-accent-soft text-accent-ink ring-1 ring-accent/40"
                  : "border border-line text-ink-2 hover:border-line-strong hover:text-ink"
              }`}
            >
              <FuenteLogo f={f} muted={f.experimental} />
              {f.name}
              {f.experimental && (
                <span className="rounded bg-line/50 px-1 py-px text-sello text-ink-3">experimental</span>
              )}
            </button>
          ) : (
            <Link
              key={f.key}
              href={`/integraciones/detalle?key=${f.key}`}
              className="flex items-center gap-1.5 rounded-md border border-dashed border-line px-2.5 py-1 text-sello font-medium text-ink-3 transition-colors hover:border-line-strong hover:text-ink-2"
            >
              <FuenteLogo f={f} muted />
              {f.name}
              <span className="rounded bg-line/50 px-1 py-px text-sello">por conectar</span>
            </Link>
          ),
        )}
      </div>
    </div>
  );
}

function key_in(config: AiuditaConfig, key: string): boolean {
  return config != null && key in config;
}

function valor_de(config: AiuditaConfig, spec: AiuditaSpec, key: string): string | number | boolean {
  if (key_in(config, key)) return config[key];
  const p = spec.perillas.find((x) => x.key === key);
  return p ? p.default : "";
}

/** La única aiudita que corre SOLA en batch hoy (misma constante que el backend:
 *  AIUDITAS_DE_CORRIDA en api/ayudantes.py). Las demás trabajan en el chat o bajo
 *  demanda (cotizar en Ventas, conciliar en Conciliación). */
const AIUDITA_DE_CORRIDA = "cobranza.redactar_recordatorio";

/** Un dato real del ayudante (sus acciones derivadas), en el encabezado del trabajo. */
function WorkStat({ n, label }: { n: number; label: string }) {
  return (
    <div>
      <div className="text-seccion font-semibold leading-none tabular-nums text-ink">
        <AnimatedNumber value={n} />
      </div>
      <div className="mt-1 text-apoyo text-ink-3">{label}</div>
    </div>
  );
}

/** Panel derecho: la superficie de trabajo. Encabezado con contexto real (sus acciones)
 *  y «Correr ahora», luego el CHAT ocupando el espacio principal · es cómo se trabaja con
 *  él. Correr deja PROPUESTAS en el Centro esperando aprobación; nada sale solo. Honesto:
 *  si no tiene aiuditas de corrida, lo dice en vez de fingir un botón que no hace nada. */
function WorkSurface({
  id,
  name,
  activos,
  acciones,
}: {
  id: string;
  name: string;
  activos: Record<string, AiuditaConfig>;
  acciones: { pendientes: number; enviadas: number; total: number };
}) {
  const [corriendo, setCorriendo] = useState(false);
  const [resultado, setResultado] = useState<CorridaAyudante | null>(null);
  const corrible = AIUDITA_DE_CORRIDA in activos;

  const correr = async () => {
    if (corriendo) return;
    setCorriendo(true);
    setResultado(null);
    try {
      const r = await api.correrAyudante(id);
      setResultado(r);
      // Acciones y nivel se derivan en el backend: re-lee para que la ficha los refleje.
      await refreshAyudante(id);
    } catch (e) {
      toast(e instanceof Error ? e.message : "No pude correr al ayudante ahora.", "error");
    } finally {
      setCorriendo(false);
    }
  };

  return (
    <div className="flex h-[560px] flex-col overflow-hidden rounded-xl border border-line bg-surface lg:h-full">
      {/* Encabezado del trabajo: contexto real + correr ahora. Compacto a propósito:
          el protagonista de este panel es la conversación, no la estadística. */}
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <div className="flex gap-6">
          <WorkStat n={acciones.pendientes} label="Propuestas pendientes" />
          <WorkStat n={acciones.enviadas} label="Enviadas" />
        </div>
        {corrible ? (
          <PrimaryButton onClick={correr} disabled={corriendo}>
            {corriendo ? "Corriendo…" : "Correr ahora"}
          </PrimaryButton>
        ) : (
          <span className="max-w-[190px] text-right text-apoyo leading-snug text-ink-3">
            Trabaja en el chat; para correr la cartera sola, agrégale «Redactar recordatorio».
          </span>
        )}
      </div>

      {resultado && (
        <p
          className="shrink-0 border-b border-line bg-accent-soft/40 px-4 py-2 text-cuerpo text-ink-2"
          aria-live="polite"
        >
          {resultado.propuestas > 0 ? (
            <>
              {resultado.propuestas} propuesta{resultado.propuestas === 1 ? "" : "s"} esperando tu
              aprobación.{" "}
              <Link href="/centro" className="font-medium text-accent-ink hover:underline">
                Revísalas en el Centro
              </Link>
              .
            </>
          ) : (
            (resultado.detalle ?? "Sin nada que proponer ahora.")
          )}
        </p>
      )}

      {/* El chat es el centro: ocupa el resto del panel, con scroll propio y el campo
          para escribir pegado abajo (mismo patrón que el hilo de Conversaciones). */}
      <div className="min-h-0 flex-1 p-3">
        <AyudanteChat id={id} name={name} activos={activos} fill />
      </div>
    </div>
  );
}

/** Preguntas de arranque HONESTAS: solo se ofrecen las que este ayudante puede
 *  contestar de verdad con lo que trae equipado (en el chat sus herramientas son
 *  de solo lectura: consultar cartera, catálogo, cliente, agenda, citas, pagos).
 *  Redactar es proponer texto en el hilo; enviar sigue siendo decisión tuya. */
const PREGUNTAS_POR_AIUDITA: [string, string][] = [
  ["cobranza.consultar_cartera", "¿Cómo va mi cartera?"],
  ["cobranza.consultar_cartera", "¿A quién le cobro hoy?"],
  ["cobranza.redactar_recordatorio", "Propón un recordatorio para el cliente que más debe"],
  ["conciliacion.consultar_pagos", "¿Qué pagos entraron esta semana?"],
  ["ventas.consultar_cliente", "Cuéntame de mi cliente más importante"],
  ["ventas.consultar_catalogo", "¿Qué le puedo ofrecer a un cliente nuevo?"],
  ["recepcion.consultar_agenda", "¿Cómo está mi agenda de hoy?"],
  ["recepcion.buscar_cita", "¿Tengo alguna cita sin confirmar?"],
];

function preguntasDeArranque(activos: Record<string, AiuditaConfig>): string[] {
  const puede = (id: string) => id in activos;
  const lista = PREGUNTAS_POR_AIUDITA.filter(([aiudita]) => {
    if (!puede(aiudita)) return false;
    // Redactar sin de dónde leer no daría un borrador con datos reales.
    if (aiudita === "cobranza.redactar_recordatorio") return puede("cobranza.consultar_cartera");
    return true;
  }).map(([, pregunta]) => pregunta);
  return [...lista.slice(0, 3), "¿Qué sabes hacer?"];
}

/** Chat con el ayudante: sus herramientas y persona se arman en el backend desde sus
 *  aiuditas activas. En el chat solo consulta; las escrituras viven en los flujos. */
function AyudanteChat({
  id,
  name,
  activos,
  fill,
}: {
  id: string;
  name: string;
  activos: Record<string, AiuditaConfig>;
  fill?: boolean;
}) {
  const [messages, setMessages] = useState<ChatterMessage[]>([]);
  const [thinking, setThinking] = useState(false);
  const historyRef = useRef<{ role: string; body: string }[]>([]);

  async function send(body: string) {
    const now = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      { id: `u-${historyRef.current.length}-${now}`, side: "me", label: "Tú", body, time: now },
    ]);
    historyRef.current.push({ role: "user", body });
    setThinking(true);
    try {
      const { reply } = await api.ayudanteChat(id, body, historyRef.current);
      historyRef.current.push({ role: "agent", body: reply });
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${historyRef.current.length}-${reply.slice(0, 6)}`,
          side: "them",
          label: name,
          body: reply,
          time: new Date().toISOString(),
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${historyRef.current.length}`,
          side: "them",
          label: name,
          body: "No pude responder en este momento. Intenta de nuevo en un momento.",
        },
      ]);
    } finally {
      setThinking(false);
    }
  }

  return (
    <Chatter
      messages={messages}
      onSend={send}
      thinking={thinking}
      thinkingLabel={name}
      fill={fill}
      placeholder={`Pregúntale a ${name}…`}
      emptyTitle={`Habla con ${name}`}
      emptyHint={`Consulta lo que sabe hacer o pídele que proponga un siguiente paso. ${name} propone; tú decides qué sale.`}
      suggestions={preguntasDeArranque(activos)}
    />
  );
}

/** Dado: "apariencia al azar". Mismo trazo de línea que el resto de iconos. */
function DiceIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2.5" y="2.5" width="11" height="11" rx="3" />
      <circle cx="6" cy="6" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="10" cy="10" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="10" cy="6" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="6" cy="10" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  );
}

/**
 * Estudio de apariencia compacto: preview en vivo + pestañas de categoría (una visible a la
 * vez) + "Al azar". Mismo lenguaje que la maqueta de la landing; aquí editas la cara real del
 * ayudante. Reemplaza las siete filas apiladas por una sola fila de pestañas y su escenario, así
 * la apariencia (secundaria frente a las aiuditas) deja de comerse la pantalla.
 */
function AppearancePicker({
  app,
  onChange,
}: {
  app: Appearance;
  onChange: (patch: Partial<Appearance>) => void;
}) {
  const [tab, setTab] = useState<string>("color");
  const tabs: { key: string; label: string }[] = [
    { key: "color", label: "Color" },
    ...PART_META.map((p) => ({ key: p.cat, label: p.label })),
    { key: "symbol", label: "Símbolo" },
  ];

  const shuffle = () => {
    const pick = <T,>(a: readonly T[]): T => a[Math.floor(Math.random() * a.length)];
    onChange({
      color: Math.floor(Math.random() * ACCENT_COLORS.length),
      hair: pick(PART_KEYS.hair),
      eyes: pick(PART_KEYS.eyes),
      mouth: pick(PART_KEYS.mouth),
      hat: pick(PART_KEYS.hat),
      accessory: pick(PART_KEYS.accessory),
      symbol: pick(SYMBOL_KEYS),
    });
  };

  return (
    <section className="mb-6 rounded-lg border border-line bg-surface px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-rotulo font-semibold uppercase tracking-[0.07em] text-ink-3">
          Apariencia
        </h2>
        <button
          onClick={shuffle}
          className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-sello font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
        >
          <DiceIcon />
          Al azar
        </button>
      </div>

      <div className="flex items-start gap-5">
        <Avatar size={72} {...app} className="mt-0.5 shrink-0" />

        <div className="min-w-0 flex-1">
          {/* Pestañas de categoría */}
          <div role="tablist" className="flex flex-wrap gap-0.5">
            {tabs.map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => setTab(t.key)}
                className={`rounded-md px-2.5 py-1 text-sello font-medium transition-colors ${
                  tab === t.key
                    ? "bg-accent-soft text-accent-ink"
                    : "text-ink-3 hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Escenario: solo las opciones de la categoría activa */}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {tab === "color"
              ? ACCENT_COLORS.map((c, i) => (
                  <button
                    key={c}
                    onClick={() => onChange({ color: i })}
                    aria-label={`Color ${i + 1}`}
                    className="h-7 w-7 rounded-full transition-transform hover:scale-110"
                    style={{
                      background: c,
                      boxShadow:
                        app.color === i ? `0 0 0 2px var(--color-surface), 0 0 0 4px ${c}` : undefined,
                    }}
                  />
                ))
              : tab === "symbol"
                ? SYMBOL_KEYS.map((s) => (
                    <button
                      key={s}
                      onClick={() => onChange({ symbol: s })}
                      aria-label={`Símbolo ${s}`}
                      className={`flex h-9 w-9 items-center justify-center rounded-md border transition-colors ${
                        app.symbol === s
                          ? "border-accent bg-accent-soft text-accent-ink"
                          : "border-line text-ink-2 hover:border-line-strong hover:text-ink"
                      }`}
                    >
                      <RoleIcon symbol={s} className="h-5 w-5" />
                    </button>
                  ))
                : PART_KEYS[tab as PartCategory].map((opt) => (
                    <button
                      key={opt}
                      onClick={() => onChange({ [tab]: opt } as Partial<Appearance>)}
                      aria-label={`${tab}: ${opt}`}
                      className={`flex h-9 w-9 items-center justify-center rounded-md border transition-colors ${
                        app[tab as PartCategory] === opt
                          ? "border-accent bg-accent-soft"
                          : "border-line hover:border-line-strong"
                      }`}
                    >
                      <Avatar size={26} {...{ ...app, [tab]: opt }} />
                    </button>
                  ))}
          </div>
        </div>
      </div>
    </section>
  );
}

