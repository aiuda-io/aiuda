"use client";

// Organigrama vivo del negocio: TÚ arriba, tus ayudantes debajo, y por cada uno lo que sabe
// hacer (sus aiuditas) con la fuente de la que lee y su estado REAL. El detalle de cada ayudante
// abre como VENTANA lateral (no acordeón vertical): su autonomía en tono profesional y lo que
// sabe hacer, con conectar-en-el-sitio. "Suma un ayudante" abre el alta ahí mismo: el nuevo
// aparece en el árbol sin cambiarte de pantalla.
import { type ReactNode, useMemo, useState } from "react";
import Link from "next/link";
import type { AiuditaConfig, AiuditaSpec, AiuditasCatalog, Fuente, IntegrationNode } from "@/lib/api";
import {
  createAyudante,
  setAiudita,
  useAyudantes,
  useCatalog,
  type Ayudante,
} from "@/lib/ayudantes-store";
import { Avatar } from "@/components/avatar";
import { appearanceForSlug, lookForAiuditas, normalizeAppearance } from "@/lib/look";
import { Skeleton } from "@/components/ui";
import { Drawer } from "@/components/drawer";

// "lista" = tiene una fuente conectada de donde leer; "hueco" = lee de una fuente pero ninguna
// está conectada (no corre hasta que conectes una); "accion" = no lee datos (redacta/envía), no
// cuenta como hueco.
type RowKind = "lista" | "hueco" | "accion";

type CapRow = {
  spec: AiuditaSpec;
  kind: RowKind;
  connectedKey: string | null;
};

type Resolved = {
  a: Ayudante;
  rows: CapRow[];
  listas: number; // aiuditas con fuente LISTA
  total: number; // aiuditas que leen de una fuente
  huecos: number; // aiuditas en rojo
};

/** Oficio del ayudante = los perfiles con al menos una aiudita activa, unidos con " · ". Mismo
 *  criterio que la ficha de ayudantes. */
function oficioDe(catalog: AiuditasCatalog, a: Ayudante): string {
  const activos = new Set(Object.keys(a.aiuditas));
  const perfiles = catalog.perfiles.filter((p) =>
    catalog.aiuditas.some((c) => c.perfil === p.slug && activos.has(c.id)),
  );
  return perfiles.length > 0 ? perfiles.map((p) => p.name).join(" · ") : "Sin oficio todavía";
}

/** La lógica central: por cada aiudita activa del ayudante, resuelve de dónde lee y su estado. */
function resolveAyudante(
  a: Ayudante,
  catalog: AiuditasCatalog,
  systemByKey: Record<string, IntegrationNode>,
): Resolved {
  const rows: CapRow[] = [];
  // Recorremos el catálogo (orden estable y lógico) y tomamos solo las activas del ayudante.
  for (const spec of catalog.aiuditas) {
    if (!(spec.id in a.aiuditas)) continue;
    if (spec.fuentes && spec.fuentes.length > 0) {
      const chosenRaw = a.aiuditas[spec.id]?._fuente;
      const chosen = typeof chosenRaw === "string" ? chosenRaw : undefined;
      const connectedKey =
        chosen && systemByKey[chosen]?.connected
          ? chosen
          : (spec.fuentes.find((f) => systemByKey[f.key]?.connected)?.key ?? null);
      rows.push({ spec, kind: connectedKey ? "lista" : "hueco", connectedKey });
    } else {
      // Acción pura (o capacidad sin fuentes ofrecibles): fila honesta sin chips, no es hueco.
      rows.push({ spec, kind: "accion", connectedKey: null });
    }
  }
  const conFuente = rows.filter((r) => r.kind !== "accion");
  const listas = conFuente.filter((r) => r.kind === "lista").length;
  const huecos = conFuente.filter((r) => r.kind === "hueco").length;
  return { a, rows, listas, total: conFuente.length, huecos };
}

// --- Autonomía ------------------------------------------------------------
// Cuánta autonomía le diste, en tono profesional y en tus palabras. Se deriva de la perilla
// `autonomia` de su aiudita de envío (hoy: enviar por WhatsApp de cobranza). Es un interruptor
// honesto: apagado, te propone todo; prendido, manda sola la cobranza de rutina (bajo el atraso
// que fijes) y te pide aprobación en lo demás. El tope crítico NO es opcional: aiuda siempre te
// pide en lo crítico. Refleja el gate real del motor (engine._auto_send).
const AUTONOMY_KEY = "autonomia";
const UMBRAL_KEY = "umbral_auto_dias";
const UMBRAL_DEFAULT = 7;

type Autonomia = { aiuditaId: string; auto: boolean; umbral: number; config: AiuditaConfig };

/** La aiudita del ayudante que gobierna su autonomía, con su config actual. null si ninguna
 *  de sus aiuditas activas tiene perilla de autonomía (entonces solo propone, sin ajuste). */
function autonomiaDe(a: Ayudante, catalog: AiuditasCatalog): Autonomia | null {
  for (const spec of catalog.aiuditas) {
    if (!(spec.id in a.aiuditas)) continue;
    if (spec.perillas?.some((p) => p.key === AUTONOMY_KEY)) {
      const config = a.aiuditas[spec.id] ?? {};
      const raw = config[AUTONOMY_KEY];
      const umbralRaw = config[UMBRAL_KEY];
      const umbral = Number(umbralRaw);
      return {
        aiuditaId: spec.id,
        auto: raw === "auto_bajo_umbral",
        umbral: Number.isFinite(umbral) && umbral > 0 ? umbral : UMBRAL_DEFAULT,
        config,
      };
    }
  }
  return null;
}

const CHEVRON = (
  <path
    d="M4.5 3 8 6l-3.5 3"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
  />
);

const CANDADO = (
  <svg viewBox="0 0 14 14" className="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.2">
    <rect x="3" y="6" width="8" height="5.5" rx="1" />
    <path d="M4.8 6V4.6a2.2 2.2 0 0 1 4.4 0V6" />
  </svg>
);

/** El interruptor de autonomía dentro de la ventana de detalle. Escribe la perilla real
 *  (`autonomia` + `umbral_auto_dias`) del ayudante. Sin metáforas, sin niveles. */
function AutonomiaControl({ info, ayudanteId }: { info: Autonomia; ayudanteId: string }) {
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(String(info.umbral));
  // Reflejo optimista: el interruptor cambia YA al tocarlo (sin esperar el ida-y-vuelta),
  // y si el guardado falla lo revertimos y lo decimos. Antes `save` no tenía catch: un
  // fallo dejaba el interruptor mudo (se veía "no funciona").
  const [pendiente, setPendiente] = useState<boolean | null>(null);
  const [error, setError] = useState(false);
  const auto = pendiente ?? info.auto;

  async function save(patch: AiuditaConfig) {
    setBusy(true);
    setError(false);
    try {
      await setAiudita(ayudanteId, info.aiuditaId, { ...info.config, ...patch });
    } catch {
      setError(true);
    } finally {
      setBusy(false);
      setPendiente(null); // reconcilia con la verdad del servidor (info ya trae el valor nuevo)
    }
  }

  function toggle() {
    if (busy) return;
    const siguiente = !auto;
    setPendiente(siguiente);
    save({ [AUTONOMY_KEY]: siguiente ? "auto_bajo_umbral" : "siempre_pedir" });
  }

  function commitUmbral() {
    const n = Math.max(1, Math.min(44, Math.round(Number(draft) || UMBRAL_DEFAULT)));
    setDraft(String(n));
    if (n !== info.umbral) save({ [UMBRAL_KEY]: n });
  }

  return (
    <div className="rounded-xl border border-line bg-panel p-3.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-ink">
            Enviar la cobranza de rutina sin pedir aprobación
          </p>
          <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
            {auto ? (
              <>
                Manda sola los recordatorios de{" "}
                <span className="font-semibold text-ink">menos de {info.umbral} días de atraso</span>.
                Arriba de eso, y en casos delicados,{" "}
                <span className="font-semibold text-ink">siempre te pide aprobación</span>.
              </>
            ) : (
              <>
                Ahorita <span className="font-semibold text-ink">te propone cada recordatorio</span> y
                no manda nada sin tu aprobación.
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={auto}
          aria-label="Enviar la cobranza de rutina sin pedir aprobación"
          disabled={busy}
          onClick={toggle}
          className={`relative mt-0.5 h-6 w-[42px] shrink-0 rounded-full transition-colors disabled:cursor-wait ${
            auto ? "bg-accent" : "bg-line-strong"
          }`}
        >
          <span
            className={`absolute top-[3px] h-[18px] w-[18px] rounded-full bg-surface shadow-sm transition-transform ${
              auto ? "translate-x-[21px]" : "translate-x-[3px]"
            }`}
          />
        </button>
      </div>

      {auto && (
        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3 text-[12px] text-ink-2">
          Solo por debajo de
          <input
            type="number"
            min={1}
            max={44}
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitUmbral}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
            className="tnum w-14 rounded-md border border-line bg-surface px-2 py-1 text-center text-[12.5px] text-ink focus:border-accent focus:outline-none"
          />
          días de atraso.
        </div>
      )}

      {error && (
        <p className="mt-3 rounded-lg bg-warn-soft px-2.5 py-1.5 text-[11.5px] text-warn">
          No se pudo guardar el cambio. Revisa tu conexión y vuelve a intentarlo.
        </p>
      )}

      <div className="mt-3 flex items-center gap-2 text-[11.5px] text-ink-3">
        {CANDADO}
        Los casos críticos siempre requieren tu aprobación.
      </div>
    </div>
  );
}

function Stat({ n, label, tone }: { n: number; label: string; tone: "ok" | "warn" | "danger" }) {
  const color = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-danger";
  return (
    <div className="min-w-[80px] rounded-lg border border-line bg-surface px-3 py-1.5 text-right">
      <span className={`tnum block text-[17px] font-bold leading-none ${color}`}>{n}</span>
      <span className="text-[10px] text-ink-3">{label}</span>
    </div>
  );
}

function YouNode({ businessName }: { businessName: string }) {
  const clean = businessName.trim();
  const name = clean || "Tu negocio";
  const glyph = (clean[0] ?? "T").toUpperCase();
  return (
    <div className="flex items-center gap-2.5 rounded-xl bg-navy px-4 py-2.5 text-surface shadow-[0_12px_32px_-20px_rgba(13,45,62,0.7)]">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-white/15 text-[14px] font-bold">
        {glyph}
      </span>
      <div className="leading-tight">
        <div className="text-[13.5px] font-semibold">{name}</div>
        <div className="text-[10px] uppercase tracking-[0.11em] text-surface/70">Tú</div>
      </div>
    </div>
  );
}

/** Tallo + riel horizontal. Cada tarjeta cuelga con su propio stub (abajo), así se lee como
 *  un organigrama de verdad y no una sola bajada al centro. Sobrio: sin glow. */
function Trunk() {
  return (
    <>
      <span className="h-5 w-px bg-line-strong" />
      <span className="h-px w-full max-w-[820px] bg-line-strong" />
    </>
  );
}

/** Envuelve una tarjeta con su stub vertical, que la cuelga del riel del árbol. */
function Hangs({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center">
      <span className="h-4 w-px bg-line-strong" />
      {children}
    </div>
  );
}

function Chips({
  row,
  systemByKey,
  onConnect,
}: {
  row: CapRow;
  systemByKey: Record<string, IntegrationNode>;
  onConnect: (node: IntegrationNode) => void;
}) {
  const fuentes: Fuente[] = row.spec.fuentes ?? [];
  return (
    <div className="ml-3.5 mt-2 flex flex-wrap gap-1.5">
      {fuentes.map((f) => {
        const node = systemByKey[f.key];
        if (node?.connected) {
          return (
            <span
              key={f.key}
              className="inline-flex items-center gap-1.5 rounded-full border border-ok px-2 py-0.5 text-[11px] font-medium text-ok"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-ok" />
              {f.name}
            </span>
          );
        }
        const base =
          "inline-flex items-center gap-1.5 rounded-full border border-dashed border-line-strong px-2 py-0.5 text-[11px] font-medium text-ink-3";
        // Solo se ofrece conectar la fuente si existe como sistema en el grafo (si es del
        // catálogo pero no está en systems, no la ofrecemos: se muestra informativa).
        if (node) {
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => onConnect(node)}
              title={`Conectar ${f.name} sin salir de aquí`}
              className={`${base} transition-colors hover:border-accent hover:bg-accent-soft hover:text-accent-ink`}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-line-strong" />
              {f.name} · conectar
            </button>
          );
        }
        return (
          <span key={f.key} title="Aún no se puede conectar desde aquí" className={base}>
            <span className="h-1.5 w-1.5 rounded-full bg-line-strong" />
            {f.name}
          </span>
        );
      })}
    </div>
  );
}

function CapRowView({
  row,
  systemByKey,
  onConnect,
}: {
  row: CapRow;
  systemByKey: Record<string, IntegrationNode>;
  onConnect: (node: IntegrationNode) => void;
}) {
  const dot =
    row.kind === "lista" ? "bg-ok" : row.kind === "hueco" ? "bg-danger" : "bg-line-strong";
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
        <span className="text-[12.5px] font-semibold text-ink">{row.spec.label}</span>
      </div>
      <p className="ml-3.5 mt-0.5 text-[11.5px] leading-snug text-ink-3">{row.spec.linea}</p>
      {row.kind !== "accion" && (
        <Chips row={row} systemByKey={systemByKey} onConnect={onConnect} />
      )}
      {row.kind === "hueco" && (
        <div className="ml-3.5 mt-2 flex items-start gap-1.5 text-[11px] text-danger">
          <svg viewBox="0 0 12 12" className="mt-px h-3 w-3 shrink-0" fill="none">
            <path d="M6 1.5 11 10.5H1z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
            <path d="M6 5v2.4M6 9v.1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
          <span>
            <b className="font-semibold">Hueco:</b> &ldquo;{row.spec.label}&rdquo; no corre hasta
            que conectes una fuente.
          </span>
        </div>
      )}
    </div>
  );
}

/** Tarjeta punteada que cuelga del árbol: el MISMO gesto para "suma un ayudante" y para
 *  "conecta una fuente" (mismo tamaño, mismo borde punteado, mismo +). `destacada` la pone
 *  en acento cuando ese es el siguiente paso real del negocio. */
function TarjetaPunteada({
  title,
  hint,
  destacada,
  onClick,
}: {
  title: string;
  hint: string;
  destacada?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex h-full min-h-[104px] w-[248px] flex-col items-center justify-center rounded-lg border border-dashed bg-transparent px-4 py-6 text-center transition-colors hover:bg-accent-soft ${
        destacada ? "border-accent" : "border-line-strong hover:border-accent"
      }`}
    >
      <span
        className={`grid h-9 w-9 place-items-center rounded-lg border border-dashed text-[18px] leading-none ${
          destacada ? "border-accent bg-accent-soft text-accent-ink" : "border-line-strong text-ink-3"
        }`}
      >
        +
      </span>
      <span
        className={`mt-2 text-[12.5px] font-semibold ${destacada ? "text-accent-ink" : "text-ink-2"}`}
      >
        {title}
      </span>
      <span className={`mt-0.5 text-[11px] ${destacada ? "text-ink-2" : "text-ink-3"}`}>{hint}</span>
    </button>
  );
}

/** La tarjeta del ayudante en el árbol: un botón que abre su ventana de detalle. */
function AgentCard({
  r,
  catalog,
  onOpen,
}: {
  r: Resolved;
  catalog: AiuditasCatalog;
  onOpen: () => void;
}) {
  const { a } = r;
  const activo = Object.keys(a.aiuditas).length > 0;
  const oficio = oficioDe(catalog, a);
  const auto = autonomiaDe(a, catalog);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-[248px] overflow-hidden rounded-lg border border-line bg-surface text-left transition-colors hover:border-line-strong hover:shadow-md"
    >
      <span className="flex w-full items-center gap-2.5 p-3">
        <Avatar name={a.name} size={36} {...normalizeAppearance(a.appearance)} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="min-w-0 truncate text-[13.5px] font-semibold text-ink">{a.name}</span>
            {activo ? (
              <span className="shrink-0 rounded-full bg-ok-soft px-1.5 py-px text-[10px] font-semibold text-ok">
                activo
              </span>
            ) : (
              <span className="shrink-0 rounded-full border border-line bg-panel px-1.5 py-px text-[10px] font-medium text-ink-3">
                sin aiuditas
              </span>
            )}
          </span>
          <span className="block truncate text-[11.5px] text-ink-3">{oficio}</span>
        </span>
        <svg viewBox="0 0 12 12" className="h-3 w-3 shrink-0 text-ink-3" fill="none">
          {CHEVRON}
        </svg>
      </span>

      {r.total > 0 && (
        <span className="flex items-center gap-2 px-3 pb-3">
          <span className="flex h-1.5 flex-1 overflow-hidden rounded-full bg-panel">
            <span className="block h-full bg-ok" style={{ width: `${(r.listas / r.total) * 100}%` }} />
            <span
              className="block h-full bg-danger"
              style={{ width: `${((r.total - r.listas) / r.total) * 100}%` }}
            />
          </span>
          <span className="tnum text-[10.5px] text-ink-3">
            {r.listas} / {r.total} listas
          </span>
        </span>
      )}

      {auto && (
        <span className="flex items-center gap-1.5 border-t border-line px-3 py-2 text-[11px] text-ink-2">
          {CANDADO}
          {auto.auto ? "Envía la rutina · te pide lo demás" : "Aprobación manual"}
        </span>
      )}
    </button>
  );
}

/** La ventana de detalle del ayudante: su autonomía (profesional) y lo que sabe hacer, con
 *  conectar-en-el-sitio. Reusa el Drawer compartido (mismo gesto que el resto de la consola). */
function AyudanteDrawer({
  r,
  catalog,
  systemByKey,
  onClose,
  onConnect,
}: {
  r: Resolved;
  catalog: AiuditasCatalog;
  systemByKey: Record<string, IntegrationNode>;
  onClose: () => void;
  onConnect: (node: IntegrationNode) => void;
}) {
  const { a } = r;
  const oficio = oficioDe(catalog, a);
  const auto = autonomiaDe(a, catalog);
  return (
    <Drawer open onClose={onClose} title={a.name} subtitle={oficio}>
      <div className="space-y-6">
        {auto && (
          <section>
            <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
              Autonomía
            </p>
            <AutonomiaControl key={a.id} info={auto} ayudanteId={a.id} />
          </section>
        )}

        <section>
          <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
            Lo que sabe hacer
          </p>
          {r.rows.length > 0 ? (
            <div className="space-y-2">
              {r.rows.map((row) => (
                <CapRowView
                  key={row.spec.id}
                  row={row}
                  systemByKey={systemByKey}
                  onConnect={onConnect}
                />
              ))}
            </div>
          ) : (
            <p className="text-[12px] text-ink-3">
              Sin aiuditas todavía. Actívale lo que quieres que sepa hacer desde su ficha.
            </p>
          )}
        </section>

        <Link
          href={`/ayudantes/detalle?id=${a.id}`}
          className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-accent-ink hover:underline"
        >
          Abrir ficha completa
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M5 3l4 3.5L5 10" />
          </svg>
        </Link>
      </div>
    </Drawer>
  );
}

const SUGERENCIAS = ["tavo", "lucía", "abi", "gio"];

// Lo que cuelga del negocio son dos cosas: sus ayudantes y sus fuentes. Con ejemplos
// concretos, no categorías: el dueño reconoce su Excel antes que "cuentas por cobrar".
const FUENTE_HINT = "Odoo, tu Excel, WhatsApp, tu banco…";

/** Alta de un ayudante ahí mismo (sin cambiar de pantalla): nombre + con qué
 *  empieza (una plantilla con sus aiuditas, o desde cero). Al crear, aparece en
 *  el árbol y abrimos su ventana de detalle ya con su oficio activo. */
function CrearDrawer({
  count,
  onClose,
  onCreated,
}: {
  count: number;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const { catalog } = useCatalog();
  const [name, setName] = useState("");
  const [perfil, setPerfil] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const perfilSpec = catalog?.perfiles.find((p) => p.slug === perfil) ?? null;
  const aiuditasDelPerfil = useMemo(
    () => (catalog && perfil ? catalog.aiuditas.filter((a) => a.perfil === perfil).map((a) => a.id) : []),
    [catalog, perfil],
  );

  async function crear() {
    if (saving) return;
    setSaving(true);
    try {
      const nombre = name.trim() || perfilSpec?.name || "Sin nombre";
      const look = perfil ? appearanceForSlug(perfil) : lookForAiuditas([], count);
      const a = await createAyudante(nombre, look, aiuditasDelPerfil);
      onCreated(a.id);
    } catch {
      setSaving(false);
    }
  }

  return (
    <Drawer open onClose={onClose} title="Suma un ayudante" subtitle="Aparece en tu árbol al crearlo">
      <form
        className="space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          crear();
        }}
      >
        <div>
          <label htmlFor="nuevo-ayudante" className="mb-1.5 block text-[12px] font-semibold text-ink">
            ¿Cómo se va a llamar?
          </label>
          <input
            id="nuevo-ayudante"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={perfilSpec ? perfilSpec.name : "tavo, lucía, abi…"}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13.5px] text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
          />
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {SUGERENCIAS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setName(s)}
                className="rounded-full border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors hover:border-accent hover:bg-accent-soft hover:text-accent-ink"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-1.5 text-[12px] font-semibold text-ink">¿Con qué empieza?</p>
          <div className="space-y-1.5">
            <button
              type="button"
              onClick={() => setPerfil(null)}
              aria-pressed={perfil === null}
              className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-[12.5px] transition-colors ${
                perfil === null
                  ? "border-accent bg-accent-soft text-accent-ink"
                  : "border-line bg-surface text-ink-2 hover:border-line-strong"
              }`}
            >
              <span className="font-medium">Desde cero</span>
              <span className="text-[11px] opacity-80">le activas sus aiuditas después</span>
            </button>
            {(catalog?.perfiles ?? []).map((p) => {
              const items = catalog ? catalog.aiuditas.filter((a) => a.perfil === p.slug) : [];
              const activo = perfil === p.slug;
              return (
                <button
                  key={p.slug}
                  type="button"
                  onClick={() => setPerfil(activo ? null : p.slug)}
                  aria-pressed={activo}
                  className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-[12.5px] transition-colors ${
                    activo
                      ? "border-accent bg-accent-soft text-accent-ink"
                      : "border-line bg-surface text-ink-2 hover:border-line-strong"
                  }`}
                >
                  <span className="font-medium">{p.name}</span>
                  <span className="text-[11px] opacity-80">
                    {items.length} aiudita{items.length === 1 ? "" : "s"}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-md bg-accent px-3 py-2.5 text-[13px] font-semibold text-surface transition-colors hover:bg-accent-strong disabled:opacity-60"
        >
          {saving
            ? "Creando…"
            : perfilSpec
              ? `Crear con lo de ${perfilSpec.name}`
              : "Crear desde cero"}
        </button>

        <p className="text-[11.5px] leading-relaxed text-ink-3">
          Queda en tu organización con su oficio activo desde el primer momento; adentro ajustas
          sus perillas y de dónde lee. Sin cambiarte de pantalla.
        </p>
      </form>
    </Drawer>
  );
}

export function Organigrama({
  systems,
  businessName,
  onConnect,
  fuentesConectadas,
  onVerFuentes,
}: {
  systems: IntegrationNode[];
  businessName: string;
  onConnect: (node: IntegrationNode) => void;
  /** Cuántas fuentes tiene conectadas el negocio (catálogo + a la medida). */
  fuentesConectadas: number;
  /** Lleva a la lista completa de conectores de esta misma pantalla. */
  onVerFuentes: () => void;
}) {
  const { ayudantes, loading: loadingAy } = useAyudantes();
  const { catalog } = useCatalog();
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const systemByKey = useMemo(
    () => Object.fromEntries(systems.map((s) => [s.key, s])) as Record<string, IntegrationNode>,
    [systems],
  );

  const resolved = useMemo(
    () => (catalog ? ayudantes.map((a) => resolveAyudante(a, catalog, systemByKey)) : []),
    [ayudantes, catalog, systemByKey],
  );

  // Resumen global: fuentes únicas listas / por conectar, y # de aiuditas en rojo (huecos).
  const summary = useMemo(() => {
    const listasSet = new Set<string>();
    const porConectarSet = new Set<string>();
    let huecos = 0;
    for (const r of resolved) {
      for (const row of r.rows) {
        if (row.kind === "accion") continue;
        if (row.connectedKey) listasSet.add(row.connectedKey);
        for (const f of row.spec.fuentes ?? []) {
          if (!systemByKey[f.key]?.connected) porConectarSet.add(f.key);
        }
        if (row.kind === "hueco") huecos += 1;
      }
    }
    return { listas: listasSet.size, porConectar: porConectarSet.size, huecos };
  }, [resolved, systemByKey]);

  const loading = loadingAy || catalog === null;
  // Conectar una fuente ES el primer paso cuando no hay ninguna, o cuando hay trabajo
  // que no corre por falta de fuente (los huecos que el propio árbol ya cuenta). Ahí la
  // tarjeta llama la atención con acento sobrio, no con un banner aparte.
  const sinFuentes = fuentesConectadas === 0 || summary.huecos > 0;

  // Al conectar una fuente desde el detalle, cerramos la ventana del ayudante para no encimar
  // drawers: se abre la de conectar (IntegrationConfigDrawer, en el host).
  function connectFromDrawer(node: IntegrationNode) {
    setOpenId(null);
    onConnect(node);
  }

  if (loading) {
    return (
      <div className="mt-4 flex flex-col items-center">
        <Skeleton className="h-14 w-56 rounded-xl" />
        <span className="h-5 w-px bg-line" />
        <div className="flex flex-wrap justify-center gap-3.5">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[104px] w-[248px] rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  const openResolved = openId !== null ? resolved.find((r) => r.a.id === openId) : undefined;

  return (
    <div className="mt-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-[12.5px] text-ink-3">
          Tú arriba; tus ayudantes debajo; lo que cada uno sabe hacer y de dónde lo lee. Toca un
          ayudante para ver su detalle, o conecta una fuente donde falte, sin salir de aquí.
        </p>
        {ayudantes.length > 0 && (
          <div className="flex gap-2">
            <Stat n={summary.listas} label="fuentes listas" tone="ok" />
            <Stat n={summary.porConectar} label="por conectar" tone="warn" />
            <Stat
              n={summary.huecos}
              label={summary.huecos === 1 ? "hueco real" : "huecos reales"}
              tone="danger"
            />
          </div>
        )}
      </div>

      <div className="flex flex-col items-center">
        <YouNode businessName={businessName} />
        <Trunk />

        {ayudantes.length === 0 ? (
          <div className="flex w-full flex-wrap items-start justify-center gap-x-3.5 gap-y-5">
            <Hangs>
              <div className="w-[420px] max-w-full rounded-lg border border-dashed border-line-strong bg-surface px-6 py-8 text-center">
                <p className="text-[13px] font-semibold text-ink">Aún no tienes ayudantes</p>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-3">
                  Crea tu primer ayudante y aquí verás qué sabe hacer y de dónde lo lee, con su
                  estado real.
                </p>
                <button
                  type="button"
                  onClick={() => setCreating(true)}
                  className="mt-3 inline-block rounded-md bg-accent px-3.5 py-1.5 text-[12.5px] font-medium text-surface transition-colors hover:bg-accent-strong"
                >
                  Crear un ayudante
                </button>
              </div>
            </Hangs>

            <Hangs>
              <TarjetaPunteada
                title="Conecta una fuente"
                hint={FUENTE_HINT}
                destacada={sinFuentes}
                onClick={onVerFuentes}
              />
            </Hangs>
          </div>
        ) : (
          <div className="flex w-full flex-wrap items-start justify-center gap-x-3.5 gap-y-5">
            {resolved.map((r) => (
              <Hangs key={r.a.id}>
                <AgentCard r={r} catalog={catalog} onOpen={() => setOpenId(r.a.id)} />
              </Hangs>
            ))}

            <Hangs>
              <TarjetaPunteada
                title="Suma un ayudante"
                hint="Recepción, voz, contenido…"
                onClick={() => setCreating(true)}
              />
            </Hangs>

            {/* El gemelo de "suma un ayudante", para lo otro que cuelga del negocio: sus
                fuentes. Lleva a la lista completa de conectores, sin salir de la pantalla. */}
            <Hangs>
              <TarjetaPunteada
                title="Conecta una fuente"
                hint={FUENTE_HINT}
                destacada={sinFuentes}
                onClick={onVerFuentes}
              />
            </Hangs>
          </div>
        )}
      </div>

      {openResolved && (
        <AyudanteDrawer
          r={openResolved}
          catalog={catalog}
          systemByKey={systemByKey}
          onClose={() => setOpenId(null)}
          onConnect={connectFromDrawer}
        />
      )}

      {creating && (
        <CrearDrawer
          count={ayudantes.length}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setOpenId(id);
          }}
        />
      )}
    </div>
  );
}
