"use client";

/* Centro de mando · el Tablero es LA vista, cableado a datos reales.
 *
 * Una pantalla, un tablero de TRES estados reales (Espera tu OK · En curso · Hecho)
 * + Rechazados cuando los hay. Tocar una tarjeta abre la MESA (el artefacto + tu
 * acción) en el mismo Drawer que el resto de la consola. No hay un endpoint único:
 * se juntan tres que ya existen (/v1/reminders, /v1/reconciliation, /v1/promises) en
 * una sola cola, y las acciones reusan los handlers de siempre. Cero datos de ejemplo:
 * tenant vacío = tablero vacío.
 */

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  api,
  mxn,
  CONCILIACION_ORIGEN,
  type CustomerDetail,
  type PromiseItem,
  type ReconcileItem,
  type ReminderItem,
} from "@/lib/api";
import { fechaDM, haceTiempo } from "@/lib/format";
import { BucketPill, EmptyState, ErrorState, SecondaryLink, Skeleton, SourceBadge, useApi } from "@/components/ui";
import { WaText } from "@/components/wa-text";
import { Avatar as Mascota } from "@/components/avatar";
import { appearanceForSlug } from "@/lib/look";
import { agentDisplayName } from "@/lib/asistentes";
import { toast } from "@/components/toast";
import { Drawer } from "@/components/drawer";
import { Modal } from "@/components/modal";
import { usePageTrail } from "@/components/rastro";

type Tone = "warn" | "ok" | "ink";
type WorkType = "recordatorio" | "conciliacion" | "promesa" | "cotizacion";
type ColKey = "por_aprobar" | "sin_enviar" | "enviados" | "rechazados";

type WorkItem = {
  id: string; // prefijado (r-/c-/p-) para no chocar entre fuentes
  type: WorkType;
  agent: string;
  // El ayudante que el DUEÑO creó y que redactó esto (Reminder.meta.ayudante_id).
  // `agent` es el slug del runtime, interno: el dueño nunca creó a nadie con ese
  // nombre, así que verlo en la tarjeta es ver un fantasma trabajando por él.
  ayudante: string | null;
  kind: string;
  customer: string;
  customerId: string | null;
  amount: number | null;
  time: string;
  tag: { label: string; tone: Tone } | null;
  reminder?: ReminderItem;
  reconcile?: ReconcileItem;
  promise?: PromiseItem;
};

const tagCls: Record<Tone, string> = {
  warn: "bg-warn-soft text-warn",
  ok: "bg-ok-soft text-ok",
  ink: "bg-line/70 text-ink-2",
};


// ── Normalizadores: cada fuente real → un WorkItem ────────────────
function fromReminder(r: ReminderItem): WorkItem {
  const cotiz = r.bucket === "cotizacion";
  const correo = r.bucket === "respuesta_correo";
  return {
    id: `r-${r.id}`,
    type: cotiz ? "cotizacion" : "recordatorio",
    agent: r.agent,
    ayudante: r.propuesto_por ?? null,
    kind: cotiz ? "Cotización pedida" : correo ? "Respuesta de correo" : "Recordatorio de pago",
    customer: r.customer ?? r.title ?? "Sin nombre",
    customerId: r.customer_id,
    amount: r.amount,
    time: haceTiempo(r.created_at),
    tag: cotiz ? { label: "nuevo", tone: "ink" } : null, // recordatorio usa BucketPill
    reminder: r,
  };
}

function fromReconcile(item: ReconcileItem): WorkItem {
  const sel = item.proposal;
  return {
    id: `c-${item.id}`,
    type: "conciliacion",
    agent: "diego",
    ayudante: null, // la conciliación todavía no se atribuye a un ayudante del dueño

    kind: "Conciliación de pago",
    customer: item.counterparty ?? sel?.customer ?? "Pago recibido",
    customerId: null, // el payload de conciliación no trae customer_id (es factura)
    amount: item.amount,
    time: haceTiempo(item.paid_at),
    tag: sel?.cuadra ? { label: "cuadra", tone: "ok" } : { label: "revisar", tone: "warn" },
    reconcile: item,
  };
}

function fromPromise(p: PromiseItem): WorkItem {
  const tag: { label: string; tone: Tone } =
    p.days_left === 0
      ? { label: "vence hoy", tone: "warn" }
      : p.days_left < 0
        ? { label: `venció hace ${-p.days_left} d`, tone: "warn" }
        : { label: `en ${p.days_left} d`, tone: "ink" };
  return {
    id: `p-${p.id}`,
    type: "promesa",
    agent: "mariana",
    ayudante: null, // la promesa la registra el cliente, no la redacta un ayudante

    kind: "Promesa de pago",
    customer: p.customer,
    customerId: p.customer_id,
    amount: p.amount,
    time: `prometió ${fechaDM(p.promised_date)}`,
    tag,
    promise: p,
  };
}

function Avatar({ slug, size = 32 }: { slug?: string; size?: number }) {
  const look = slug ? appearanceForSlug(slug) : { color: 0, symbol: "spark" };
  return <Mascota name="" size={size} {...look} />;
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">{children}</p>
  );
}

function MontoLinea({
  monto,
  estado,
  fuente,
}: {
  monto: string;
  estado?: { label: string; tone: Tone };
  fuente?: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span className="tnum text-cifra font-semibold tracking-tight text-ink">{monto}</span>
        {estado && (
          <span
            className={`text-cuerpo font-medium ${estado.tone === "warn" ? "text-warn" : estado.tone === "ok" ? "text-ok" : "text-ink-3"}`}
          >
            {estado.label}
          </span>
        )}
      </div>
      {fuente && <div className="mt-1.5 text-cuerpo text-ink-3">{fuente}</div>}
    </div>
  );
}

export default function CentroPage() {
  // useSearchParams (deep-link ?r=) exige un límite de Suspense en Next.
  return (
    <Suspense fallback={<div className="h-[calc(100dvh-8.5rem)] min-h-[480px] rounded-xl border border-line bg-panel/30" />}>
      <CentroDeMando />
    </Suspense>
  );
}

function CentroDeMando() {
  usePageTrail("Centro de mando");
  const { data, error, loading, refetch, refetchQuiet } = useApi(async () => {
    const [pendientes, recon, promesas, agentes, enviados, aprobados, rechazados, fallidos, sombra] =
      await Promise.all([
        api.reminders("pending_approval"),
        api.reconciliation(),
        api.promises("active"),
        api.agents(),
        api.reminders("sent"),
        // Aprobados-pero-no-enviados: en modo sombra TODO queda aquí (nunca llega a "sent").
        // Sin esto, al aprobar el recordatorio desaparecía de todas las colas.
        api.reminders("approved"),
        api.reminders("rejected"),
        // Fallidos: el envío se intentó y no salió (canal caído, número inválido). Se muestran
        // para que no desaparezcan en silencio; si no, parecería que todo salió bien.
        api.reminders("failed"),
        api.shadowMode().catch(() => ({ modo_sombra: false })),
      ]);
    return {
      pendientes,
      recon: recon.pending,
      promesas,
      agentes,
      enviados,
      aprobados,
      rechazados,
      fallidos,
      sombra: sombra.modo_sombra,
    };
  }, []);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Ids (prefijados) de trabajos que se están resolviendo: su tarjeta colapsa con
  // .row-leaving mientras se re-baja la lista. Mismo patrón que /promesas.
  const [leaving, setLeaving] = useState<Set<string>>(new Set());

  // Deep-link: /centro?r=<reminderId> abre ese borrador en la Mesa (una vez, tras cargar).
  const targetId = useSearchParams().get("r");
  const deepLinkDone = useRef(false);
  useEffect(() => {
    if (deepLinkDone.current || !targetId || !data) return;
    deepLinkDone.current = true;
    setSelectedId(`r-${targetId}`);
  }, [targetId, data]);
  const [channelSel, setChannelSel] = useState<Record<string, string>>({});
  const [invoiceSel, setInvoiceSel] = useState<Record<string, string>>({});

  const pending = useMemo<WorkItem[]>(() => {
    if (!data) return [];
    return [
      ...data.pendientes.map(fromReminder),
      ...data.recon.map(fromReconcile),
      ...data.promesas.map(fromPromise),
    ];
  }, [data]);

  const sombra = data?.sombra ?? false;
  // "Hecho" solo lista lo que salió DE VERDAD (sent_at real). Lo aprobado-retenido
  // (sombra, canal sin conectar, en cola) y lo fallido viven en "En curso": nada
  // desaparece, pero la columna de hecho ya no miente.
  const sent = useMemo<WorkItem[]>(
    () => (data ? data.enviados.filter((r) => r.sent_at).map(fromReminder) : []),
    [data],
  );
  const unsent = useMemo<WorkItem[]>(() => {
    if (!data) return [];
    // Los fallidos primero (piden atención), luego los aprobados retenidos. Cada uno
    // dice POR QUÉ no ha salido: falló / esperando canal / retenido en prueba / en cola.
    const fallidos = data.fallidos.map((r) => ({
      ...fromReminder(r),
      tag: { label: "no salió", tone: "warn" as const },
    }));
    const retenidos = data.aprobados.map((r) => ({
      ...fromReminder(r),
      tag: {
        label: sombra ? "retenido en prueba" : r.pendiente ? "esperando canal" : "en cola de envío",
        tone: "ink" as const,
      },
    }));
    return [...fallidos, ...retenidos];
  }, [data, sombra]);
  const rejected = useMemo<WorkItem[]>(
    () => (data ? data.rechazados.map(fromReminder) : []),
    [data],
  );

  // Un solo item seleccionado abre la Mesa (Drawer), venga de la columna que venga.
  const allItems = useMemo<WorkItem[]>(
    () => [...pending, ...unsent, ...sent, ...rejected],
    [pending, unsent, sent, rejected],
  );
  const selected = selectedId ? (allItems.find((w) => w.id === selectedId) ?? null) : null;
  // Accionable (editar/aprobar/corregir) = por aprobar o rechazado. Solo-lectura
  // (reintentar/enviar/registro) = en curso o hecho.
  const readOnly = selected
    ? unsent.some((w) => w.id === selected.id) || sent.some((w) => w.id === selected.id)
    : false;

  const customerId = selected?.customerId ?? null;
  const { data: customer } = useApi<CustomerDetail | null>(
    () => (customerId ? api.customerDetail(customerId) : Promise.resolve(null)),
    [customerId],
  );

  const vacio =
    !loading && pending.length + unsent.length + sent.length + rejected.length === 0;

  if (error) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-bg">
        <ErrorState message={error} retry={refetch} />
      </div>
    );
  }

  // `ok` puede derivarse de la respuesta del server: el toast dice lo que DE VERDAD
  // pasó (p.ej. "se enviará cuando conectes WhatsApp"), no lo que se deseaba.
  async function run<T>(
    fn: () => Promise<T>,
    ok: string | ((res: T) => string),
    leavingId?: string,
  ) {
    setBusy(true);
    try {
      const res = await fn();
      toast(typeof ok === "function" ? ok(res) : ok, "success");
      setSelectedId(null);
      if (leavingId) {
        // Salida honesta: el trabajo se colapsa del tablero SOLO tras confirmar el
        // server (no optimista · es cobranza real). Colapsa (forwards lo mantiene) y a
        // los 250ms refresca en SILENCIO (sin flash de skeletons; la lista se asienta
        // sola). La marca se limpia JUSTO cuando llegó el dato nuevo: si el item se fue
        // ya está desmontado (sin rebote); si no se fue (raro), reaparece · honesto.
        setLeaving((s) => new Set(s).add(leavingId));
        setTimeout(() => {
          refetchQuiet().finally(() =>
            setLeaving((s) => {
              const n = new Set(s);
              n.delete(leavingId);
              return n;
            }),
          );
        }, 250);
      } else {
        refetchQuiet();
      }
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    // Cockpit embebido en la consola: vive dentro del shell (sidebar + topbar) como un panel
    // con marco que llena el área de contenido. El aviso de modo prueba lo pone el ShadowBanner
    // global del shell.
    <div className="flex h-[calc(100dvh-8.5rem)] min-h-[480px] flex-col gap-2.5 text-ink">
      <div className="shrink-0">
        <h1 className="text-titulo font-semibold text-ink">Despacha tu día</h1>
        <p className="text-cuerpo text-ink-2">Lo que tu equipo dejó listo. Tú decides.</p>
      </div>

      {loading && !data ? (
        <BoardSkeleton />
      ) : vacio ? (
        <div className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-line bg-surface px-6">
          <EmptyState
            title="Tablero limpio"
            action={<SecondaryLink href="/facturas">Revisar tu cartera</SecondaryLink>}
          >
            Nada por revisar. Tu equipo redacta lo siguiente cuando sincronices tus fuentes, o
            cuando se lo pidas desde una factura.
          </EmptyState>
        </div>
      ) : (
        <Tablero
          pending={pending}
          unsent={unsent}
          sent={sent}
          rejected={rejected}
          leaving={leaving}
          sombra={sombra}
          busy={busy}
          run={run}
          onOpen={(id) => setSelectedId(id)}
        />
      )}

      {selected && (
        <Drawer
          open
          size="lg"
          onClose={() => setSelectedId(null)}
          title={selected.kind}
          subtitle={selected.customer}
        >
          <div key={selected.id} className="page-enter-fwd space-y-5">
            <div className="flex flex-wrap items-center gap-1.5 text-cuerpo text-ink-3">
              por
              <Avatar slug={selected.agent} size={18} />
              <span className="font-medium text-ink-2">{agentDisplayName(selected.agent)}</span>
              {/* Trazabilidad HITL: qué ayudante del dueño gobernó esta propuesta */}
              {selected.reminder?.propuesto_por && (
                <span className="truncate">· de tu ayudante {selected.reminder.propuesto_por}</span>
              )}
            </div>
            <ContextoInline item={selected} customer={customer ?? null} />
            <Mesa
              item={selected}
              readOnly={readOnly}
              busy={busy}
              sombra={sombra}
              channelSel={channelSel}
              setChannelSel={setChannelSel}
              invoiceSel={invoiceSel}
              setInvoiceSel={setInvoiceSel}
              run={run}
            />
          </div>
        </Drawer>
      )}
    </div>
  );
}

// ── La Mesa, según el tipo ──────────────────────────────────────────
function Mesa({
  item,
  readOnly,
  busy,
  sombra,
  channelSel,
  setChannelSel,
  invoiceSel,
  setInvoiceSel,
  run,
}: {
  item: WorkItem;
  readOnly: boolean;
  busy: boolean;
  sombra: boolean;
  channelSel: Record<string, string>;
  setChannelSel: (f: (s: Record<string, string>) => Record<string, string>) => void;
  invoiceSel: Record<string, string>;
  setInvoiceSel: (f: (s: Record<string, string>) => Record<string, string>) => void;
  run: <T>(fn: () => Promise<T>, ok: string | ((res: T) => string), leavingId?: string) => void;
}) {
  // Borrador en edición, atado al item (no se fuga al cambiar de trabajo).
  const [draft, setDraft] = useState<{ id: string; text: string } | null>(null);
  if (item.type === "recordatorio" || item.type === "cotizacion") {
    const r = item.reminder!;
    const connected = r.channels.filter((c) => c.connected);
    const sel = channelSel[item.id] ?? connected[0]?.key ?? r.channel ?? "whatsapp";
    const selLabel = r.channels.find((c) => c.key === sel)?.label ?? "WhatsApp";
    const editing = draft?.id === item.id ? draft.text : null;
    return (
      <>
        {item.amount != null && (
          <MontoLinea
            monto={mxn(item.amount)}
            fuente={
              r.procedencia ? (
                <span className="inline-flex items-center gap-1.5">
                  {r.procedencia.que ?? "De dónde sale"}:
                  <SourceBadge source={r.procedencia.source} presence={r.procedencia.presence} />
                </span>
              ) : null
            }
          />
        )}
        <div className="mt-7 flex items-center justify-between">
          <Label>Tu ayudante redactó este mensaje</Label>
          {!readOnly && editing === null && (
            <button
              onClick={() => setDraft({ id: item.id, text: r.message })}
              className="text-apoyo text-ink-3 underline-offset-2 hover:text-ink hover:underline"
            >
              Editar
            </button>
          )}
        </div>
        {editing === null ? (
          <div className="mt-2.5 max-w-md rounded-2xl rounded-tl-sm border border-line bg-panel/50 px-4 py-3">
            <WaText className="text-cuerpo leading-relaxed text-ink">{r.message}</WaText>
          </div>
        ) : (
          <div className="mt-2.5 max-w-md">
            <textarea
              value={editing}
              onChange={(e) => setDraft({ id: item.id, text: e.target.value })}
              rows={4}
              autoFocus
              className="w-full resize-y rounded-2xl rounded-tl-sm border border-accent/40 bg-panel/50 px-4 py-3 text-cuerpo leading-relaxed text-ink outline-none focus:border-accent"
            />
            <div className="mt-1 flex items-center gap-2 text-apoyo text-ink-3">
              <span>Tú lo editas; tu ayudante aprende de tus cambios.</span>
              <button
                onClick={() => setDraft(null)}
                className="underline-offset-2 hover:text-ink hover:underline"
              >
                Cancelar
              </button>
            </div>
          </div>
        )}
        {!readOnly && (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <span className="text-apoyo text-ink-3">Enviar por</span>
              {r.channels.map((c) => (
                <button
                  key={c.key}
                  disabled={!c.connected}
                  onClick={() => c.connected && setChannelSel((s) => ({ ...s, [item.id]: c.key }))}
                  title={c.connected ? c.label : `${c.label} · por conectar`}
                  className={`rounded-full px-2 py-0.5 text-sello font-medium transition-colors ${
                    !c.connected
                      ? "cursor-default border border-dashed border-line text-ink-3"
                      : sel === c.key
                        ? "bg-accent-soft text-accent-ink"
                        : "border border-line text-ink-2 hover:border-line-strong"
                  }`}
                >
                  {c.label}
                  {!c.connected && " · por conectar"}
                </button>
              ))}
            </div>
            <Actions
              primary={
                busy
                  ? sombra
                    ? "Guardando…"
                    : "Enviando…"
                  : sombra
                    ? `${r.status === "rejected" ? "Corregir" : "Aprobar"} · sombra (no se envía)`
                    : `${r.status === "rejected" ? "Corregir y enviar" : "Aprobar y enviar"} por ${selLabel}`
              }
              onPrimary={() =>
                run(
                  () => api.approve(r.id, sel, editing ?? undefined),
                  // El toast dice lo que DE VERDAD pasó: sin canal conectado el server
                  // avisa "se enviará cuando conectes…" (queda aprobado, no failed).
                  (res) =>
                    res.aviso ??
                    (sombra
                      ? "Retenido en modo prueba · no se envió. Queda en En curso."
                      : `Aprobado · enviando a ${r.correo?.para ?? r.customer_phone ?? selLabel}`),
                  item.id,
                )
              }
              secondary={
                r.status === "rejected"
                  ? undefined
                  : {
                      label: "Rechazar",
                      onClick: () =>
                        run(() => api.reject(r.id), "Rechazado · queda en Rechazados", item.id),
                    }
              }
              busy={busy}
            />
          </>
        )}
        {readOnly &&
          (r.status === "failed" ? (
            <div className="mt-5">
              <p className="text-cuerpo text-danger">
                No se pudo enviar a {r.correo?.para ?? r.customer_phone ?? "el destinatario"}
                {r.motivo_fallo ? `: ${r.motivo_fallo}` : ""}. Revisa el canal y reintenta.
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  onClick={() =>
                    run(
                      () => api.approve(r.id, sel),
                      (res) =>
                        res.aviso ??
                        `Reintentando envío a ${r.correo?.para ?? r.customer_phone ?? selLabel}`,
                      item.id,
                    )
                  }
                  disabled={busy}
                  className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                >
                  {busy ? "Reintentando…" : "Reintentar envío"}
                </button>
                <SecondaryLink href="/integraciones">Revisar canales</SecondaryLink>
              </div>
            </div>
          ) : r.status === "approved" && !sombra ? (
            <div className="mt-5">
              <p className="text-cuerpo text-ink-3">
                {r.pendiente ??
                  `Aprobado. Aún no se ha enviado a ${r.correo?.para ?? r.customer_phone ?? "el destinatario"}.`}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  onClick={() =>
                    run(
                      () => api.sendReminder(r.id),
                      `Enviando a ${r.correo?.para ?? r.customer_phone ?? selLabel}`,
                      item.id,
                    )
                  }
                  disabled={busy}
                  className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
                >
                  {busy ? "Enviando…" : "Enviar ahora"}
                </button>
                {r.pendiente && <SecondaryLink href="/integraciones">Conectar canal</SecondaryLink>}
              </div>
            </div>
          ) : (
            <p className="mt-5 text-cuerpo text-ink-3">
              {r.status === "rejected"
                ? "Lo descartaste. Si quieres recordarle, pídelo de nuevo desde la factura."
                : r.status === "approved"
                  ? `Modo prueba: se retuvo el envío a ${r.correo?.para ?? r.customer_phone ?? "el destinatario"}. Apágalo en Configuración para que salga.`
                  : `Enviado a ${r.correo?.para ?? r.customer_phone ?? "el destinatario"}.`}
            </p>
          ))}
      </>
    );
  }

  if (item.type === "conciliacion") {
    const it = item.reconcile!;
    const opts = [it.proposal, ...it.alternates].filter(
      (c): c is NonNullable<typeof c> => c !== null,
    );
    const selectedId = invoiceSel[item.id] ?? it.proposal?.invoice_id ?? "";
    const sel = opts.find((c) => c.invoice_id === selectedId) ?? opts[0] ?? null;
    const diff = sel ? it.amount - sel.amount : 0;
    return (
      <>
        <Label>Tu ayudante encontró a qué factura corresponde este depósito</Label>
        <div className="mt-3 grid grid-cols-1 items-stretch gap-2.5 sm:grid-cols-[1fr_auto_1fr]">
          <div className="rounded-xl border border-line bg-ok-soft/40 px-4 py-3">
            <p className="text-rotulo font-medium uppercase tracking-[0.05em] text-ink-3">
              Pago recibido
            </p>
            <p className="tnum mt-1 text-seccion font-semibold text-ink">{mxn(it.amount)}</p>
            <p className="mt-0.5 text-cuerpo text-ink-3">
              {CONCILIACION_ORIGEN[it.source] ?? it.source} · {fechaDM(it.paid_at)}
              {it.counterparty ? ` · ${it.counterparty}` : ""}
            </p>
          </div>
          <div className="flex items-center justify-center">
            <span
              className={`tnum rounded-full px-2 py-1 text-sello font-semibold ${
                !sel
                  ? "bg-panel text-ink-3"
                  : sel.cuadra
                    ? "bg-ok text-surface"
                    : "bg-warn-soft text-warn"
              }`}
            >
              {!sel ? "sin factura" : sel.cuadra ? "cuadra" : `≠ ${mxn(Math.abs(diff))}`}
            </span>
          </div>
          <div className="rounded-xl border border-line bg-surface px-4 py-3">
            <p className="text-rotulo font-medium uppercase tracking-[0.05em] text-ink-3">
              Factura por cobrar
            </p>
            {sel ? (
              <>
                <p className="tnum mt-1 text-cuerpo font-semibold text-ink">
                  {sel.folio} · {mxn(sel.amount)}
                </p>
                <p className="mt-0.5 text-cuerpo text-ink-3">
                  {sel.customer} · vence {fechaDM(sel.due_date)}
                </p>
                {opts.length > 1 && !readOnly && (
                  <select
                    value={selectedId}
                    onChange={(e) => setInvoiceSel((s) => ({ ...s, [item.id]: e.target.value }))}
                    className="mt-2 w-full rounded-md border border-line bg-surface px-2 py-1 text-cuerpo text-ink focus:border-accent focus:outline-none"
                  >
                    {opts.map((c) => (
                      <option key={c.invoice_id} value={c.invoice_id}>
                        {c.folio} · {c.customer} · {mxn(c.amount)}
                      </option>
                    ))}
                  </select>
                )}
              </>
            ) : (
              <p className="mt-1 text-cuerpo text-ink-3">Sin factura abierta que coincida.</p>
            )}
          </div>
        </div>
        {sel?.reason && (
          <p className="mt-5 max-w-lg text-cuerpo leading-relaxed text-ink-2">
            <span className="font-medium text-ink">¿Por qué cuadra?</span> {sel.reason}
          </p>
        )}
        {!readOnly && (
          <Actions
            primary={busy ? "Conciliando…" : "Confirmar conciliación"}
            disabledPrimary={!sel}
            onPrimary={() =>
              sel &&
              run(
                () => api.confirmReconcile(it.id, sel.invoice_id),
                "Conciliado, la factura pasa a Pagadas",
                item.id,
              )
            }
            secondary={{
              label: "No es esta",
              onClick: () =>
                run(() => api.ignoreReconcile(it.id), "Pago descartado de la bandeja", item.id),
            }}
            link={sel ? { label: "Ver factura", href: "/facturas" } : undefined}
            busy={busy}
          />
        )}
      </>
    );
  }

  // promesa
  const p = item.promise!;
  return (
    <>
      <MontoLinea
        monto={mxn(p.amount)}
        estado={
          p.days_left === 0
            ? { label: "vence hoy", tone: "warn" }
            : p.days_left < 0
              ? { label: `venció hace ${-p.days_left} d`, tone: "warn" }
              : { label: `vence en ${p.days_left} d`, tone: "ink" }
        }
        fuente={`Factura ${p.folio}`}
      />
      <div className="mt-7">
        <Label>La promesa</Label>
      </div>
      <div className="mt-2.5 max-w-md rounded-xl border border-line bg-surface px-4 py-3 text-cuerpo leading-relaxed text-ink-2">
        {p.customer} prometió pagar <span className="tnum font-medium text-ink">{mxn(p.amount)}</span>{" "}
        de la factura {p.folio} para el{" "}
        <span className="font-medium text-ink">{fechaDM(p.promised_date)}</span>.
        {p.note && <span className="mt-1 block text-cuerpo text-ink-3">“{p.note}”</span>}
      </div>
      {!readOnly && (
        <Actions
          primary={busy ? "Guardando…" : "Registrar pago"}
          onPrimary={() =>
            run(() => api.pay(p.invoice_id), "Pago registrado, la factura pasa a Pagadas")
          }
          secondary={{
            label: "Recordar de nuevo",
            onClick: () =>
              run(() => api.remind(p.invoice_id), "Tu ayudante preparó un nuevo recordatorio"),
          }}
          busy={busy}
        />
      )}
    </>
  );
}

function Actions({
  primary,
  onPrimary,
  disabledPrimary,
  secondary,
  link,
  busy,
}: {
  primary: string;
  onPrimary: () => void;
  disabledPrimary?: boolean;
  secondary?: { label: string; onClick: () => void };
  link?: { label: string; href: string };
  busy: boolean;
}) {
  return (
    <div className="mt-7 flex flex-wrap items-center gap-2.5">
      <button
        onClick={onPrimary}
        disabled={busy || disabledPrimary}
        className="rounded-md bg-accent px-4 py-2 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
      >
        {primary}
      </button>
      {secondary && (
        <button
          onClick={secondary.onClick}
          disabled={busy}
          className="rounded-md border border-line bg-surface px-3.5 py-2 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
        >
          {secondary.label}
        </button>
      )}
      {link && (
        <Link
          href={link.href}
          className="rounded-md border border-line bg-surface px-3.5 py-2 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
        >
          {link.label}
        </Link>
      )}
    </div>
  );
}

// ── TABLERO (Kanban) · LA vista del Centro ──────────────────────────────────────
// Las colas ya derivadas se muestran como columnas de estado real: pending → "Espera tu
// OK", unsent → "En curso", sent → "Hecho", y Rechazados solo cuando los hay. No hay
// arrastre libre: aprobar/enviar avanza una tarjeta, y esos botones reusan los handlers
// de siempre (api.approve / reject / sendReminder). Tocar una tarjeta abre la Mesa (Drawer).
function Tablero({
  pending,
  unsent,
  sent,
  rejected,
  leaving,
  sombra,
  busy,
  run,
  onOpen,
}: {
  pending: WorkItem[];
  unsent: WorkItem[];
  sent: WorkItem[];
  rejected: WorkItem[];
  leaving: Set<string>;
  sombra: boolean;
  busy: boolean;
  run: <T>(fn: () => Promise<T>, ok: string | ((res: T) => string), leavingId?: string) => void;
  onOpen: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [fAgent, setFagent] = useState<string | null>(null);
  const [fType, setFtype] = useState<WorkType | null>(null);
  const [fVenc, setFvenc] = useState<string | null>(null);
  // Arrastre en curso + confirmación pendiente al soltar (nada sale sin tu OK).
  const [dragId, setDragId] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<ColKey | null>(null);
  const [confirm, setConfirm] = useState<{ item: WorkItem; target: DropTarget } | null>(null);

  const activeAll = [...pending, ...unsent, ...sent]; // puebla los filtros (sin lo rechazado)
  const agents = Array.from(new Set(activeAll.map((w) => w.agent)));
  const types = Array.from(new Set(activeAll.map((w) => w.type)));
  // Clientes disponibles para el buscador-con-lista, con cuántos trabajos tiene cada uno
  // (el que más debe, arriba). Así el dueño VE a quién puede filtrar, no adivina.
  const clientes = (() => {
    const m = new Map<string, number>();
    for (const w of activeAll) m.set(w.customer, (m.get(w.customer) ?? 0) + 1);
    return Array.from(m, ([name, count]) => ({ name, count })).sort(
      (a, b) => b.count - a.count || a.name.localeCompare(b.name),
    );
  })();
  // Solo se ofrecen los rangos de vencimiento que DE VERDAD hay en el tablero.
  const bucketsPresent = new Set(
    activeAll.map((w) => w.reminder?.bucket).filter(Boolean) as string[],
  );
  const vencOpts = VENC_OPCIONES.filter((o) => o.buckets.some((b) => bucketsPresent.has(b)));

  const q = search.trim().toLowerCase();
  const match = (w: WorkItem) =>
    (!fAgent || w.agent === fAgent) &&
    (!fType || w.type === fType) &&
    (!fVenc || (VENC_BY_KEY[fVenc]?.includes(w.reminder?.bucket ?? "") ?? false)) &&
    (!q || `${w.customer} ${w.kind}`.toLowerCase().includes(q));

  const fPending = pending.filter(match);
  const fUnsent = unsent.filter(match);
  const fSent = sent.filter(match);
  const fRejected = rejected.filter(match);

  const cols: { key: ColKey; title: string; dot: string; items: WorkItem[] }[] = [
    { key: "por_aprobar", title: "Espera tu OK", dot: "bg-accent", items: fPending },
    { key: "sin_enviar", title: "En curso", dot: "bg-warn", items: fUnsent },
    { key: "enviados", title: "Hecho", dot: "bg-ok", items: fSent },
  ];
  if (rejected.length > 0) {
    cols.push({ key: "rechazados", title: "Rechazados", dot: "bg-line-strong", items: fRejected });
  }
  const gridCols = cols.length === 4 ? "md:grid-cols-4" : "md:grid-cols-3";
  const total = fPending.length + fUnsent.length + fSent.length + fRejected.length;
  const nFilters = (fAgent ? 1 : 0) + (fType ? 1 : 0) + (fVenc ? 1 : 0) + (q ? 1 : 0);

  // A qué acción equivale soltar en cada columna (null = no es blanco válido).
  const targetOf = (col: ColKey): DropTarget | null =>
    col === "sin_enviar" || col === "enviados" ? "enviar" : col === "rechazados" ? "rechazar" : null;

  const onDropCol = (col: ColKey) => {
    const item = pending.find((w) => w.id === dragId);
    const target = targetOf(col);
    setOverCol(null);
    setDragId(null);
    if (item?.reminder && target) setConfirm({ item, target });
  };

  const doConfirm = (editedMessage?: string) => {
    if (!confirm) return;
    const r = confirm.item.reminder!;
    const canal = r.channels.filter((c) => c.connected)[0]?.key ?? r.channel ?? "whatsapp";
    if (confirm.target === "enviar") {
      run(
        () => api.approve(r.id, canal, editedMessage),
        (res) =>
          res.aviso ?? (sombra ? "Retenido en modo prueba, no se envió." : "Aprobado, enviando"),
        confirm.item.id,
      );
    } else {
      run(() => api.reject(r.id), "Rechazado", confirm.item.id);
    }
    setConfirm(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <FilterBar
        search={search}
        onSearch={setSearch}
        clientes={clientes}
        agents={agents}
        types={types}
        vencOpts={vencOpts}
        fAgent={fAgent}
        fType={fType}
        fVenc={fVenc}
        setFagent={setFagent}
        setFtype={setFtype}
        setFvenc={setFvenc}
        nFilters={nFilters}
        total={total}
        onReset={() => {
          setSearch("");
          setFagent(null);
          setFtype(null);
          setFvenc(null);
        }}
      />

      {/* Columnas: en móvil se apilan; en escritorio cada una tiene su scroll. Soltar una
          tarjeta en "En curso/Hecho" (enviar) o "Rechazados" abre el pop-up de confirmación. */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3 md:overflow-hidden">
        <div className={`grid grid-cols-1 gap-3 md:h-full ${gridCols}`}>
          {cols.map((col) => {
            const isTarget = dragId !== null && targetOf(col.key) !== null;
            const isOver = overCol === col.key && isTarget;
            return (
              <section
                key={col.key}
                onDragOver={(e) => {
                  if (!isTarget) return;
                  e.preventDefault();
                  if (overCol !== col.key) setOverCol(col.key);
                }}
                onDragLeave={(e) => {
                  if (!e.currentTarget.contains(e.relatedTarget as Node))
                    setOverCol((c) => (c === col.key ? null : c));
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  onDropCol(col.key);
                }}
                className={`flex flex-col rounded-xl border p-2 transition-colors md:min-h-0 ${
                  isOver
                    ? "border-accent bg-accent-soft/60"
                    : isTarget
                      ? "border-dashed border-accent/40 bg-panel/50"
                      : "border-line bg-panel/50"
                }`}
              >
                <header className="flex shrink-0 items-center gap-2 px-1.5 pb-2 pt-1">
                  <span className={`h-2 w-2 rounded-full ${col.dot}`} />
                  <span
                    className={`text-cuerpo font-semibold ${col.key === "rechazados" ? "text-ink-3" : "text-ink"}`}
                  >
                    {col.title}
                  </span>
                  <span className="tnum ml-auto rounded-full border border-line bg-surface px-2 py-px text-sello font-semibold text-ink-3">
                    {col.items.length}
                  </span>
                </header>
                <div className="reveal-stagger space-y-2 md:min-h-0 md:flex-1 md:overflow-y-auto">
                  {col.items.length === 0 ? (
                    <p className="px-1.5 py-4 text-apoyo text-ink-3">
                      {isOver
                        ? "Suéltala aquí"
                        : nFilters > 0
                          ? "Nada con este filtro."
                          : "Sin tarjetas."}
                    </p>
                  ) : (
                    col.items.map((w) => (
                      <TarjetaKanban
                        key={w.id}
                        w={w}
                        col={col.key}
                        draggable={col.key === "por_aprobar" && !!w.reminder}
                        dragging={dragId === w.id}
                        onDragStart={() => setDragId(w.id)}
                        onDragEnd={() => {
                          setDragId(null);
                          setOverCol(null);
                        }}
                        leaving={leaving.has(w.id)}
                        sombra={sombra}
                        busy={busy}
                        run={run}
                        onOpen={onOpen}
                      />
                    ))
                  )}
                </div>
              </section>
            );
          })}
        </div>
      </div>

      {/* Guardrail HITL, ahora que SÍ se arrastra: el gesto abre un confirm, no envía solo. */}
      <p className="flex shrink-0 items-center gap-2 border-t border-line px-3.5 py-2 text-apoyo leading-relaxed text-ink-2">
        <ShieldIcon />
        <span>Arrastra o toca una tarjeta y confirmas antes de que salga.</span>
      </p>

      {confirm && (
        <ConfirmSend
          item={confirm.item}
          target={confirm.target}
          sombra={sombra}
          busy={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={(msg) => doConfirm(msg)}
        />
      )}
    </div>
  );
}

// Una tarjeta del tablero. El cuerpo abre la Mesa (Drawer) con todo el detalle; abajo
// quedan las acciones rápidas de su columna, que reusan los handlers de siempre.
function TarjetaKanban({
  w,
  col,
  draggable,
  dragging,
  onDragStart,
  onDragEnd,
  leaving,
  sombra,
  busy,
  run,
  onOpen,
}: {
  w: WorkItem;
  col: ColKey;
  draggable: boolean;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  leaving: boolean;
  sombra: boolean;
  busy: boolean;
  run: <T>(fn: () => Promise<T>, ok: string | ((res: T) => string), leavingId?: string) => void;
  onOpen: (id: string) => void;
}) {
  const r = w.reminder;
  const failed = r?.status === "failed";
  const act = busy || leaving; // no re-accionar un trabajo que ya se está resolviendo
  const canal = r ? (r.channels.filter((c) => c.connected)[0]?.key ?? r.channel) : "whatsapp";
  const okBtn =
    "flex-1 rounded-md bg-accent px-2.5 py-1.5 text-apoyo font-semibold text-surface transition-colors hover:bg-accent-strong disabled:opacity-50";
  const ghBtn =
    "rounded-md border border-line bg-panel px-2.5 py-1.5 text-apoyo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50";
  return (
    <div
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      className={`rounded-lg border bg-surface px-3 py-2.5 shadow-[0_1px_2px_rgba(13,45,62,.05)] transition ${
        failed ? "border-danger/30" : "border-line"
      } ${leaving ? "row-leaving" : ""} ${
        draggable ? "cursor-grab active:cursor-grabbing" : ""
      } ${dragging ? "opacity-40" : ""}`}
    >
      {/* Cuerpo clickable → abre la Mesa (Drawer) */}
      <button type="button" onClick={() => onOpen(w.id)} className="block w-full text-left">
        <span className="flex items-center gap-2">
          <Avatar slug={w.agent} size={18} />
          <span className="min-w-0 truncate text-apoyo text-ink-3">
            de{" "}
            <span className="font-medium text-ink-2">
              {w.ayudante || agentDisplayName(w.agent)}
            </span>
          </span>
          {w.amount != null && (
            <span className="tnum ml-auto text-cuerpo font-semibold text-ink">{mxn(w.amount)}</span>
          )}
        </span>
        <span className="mt-1.5 block text-seccion font-semibold leading-snug text-ink">{w.customer}</span>
        <span className="mt-1 flex flex-wrap items-center gap-1.5">
          {w.type === "recordatorio" && r ? (
            <>
              <BucketPill bucket={r.bucket} />
              {w.tag && (
                <span className={`rounded px-1.5 py-px text-sello font-medium ${tagCls[w.tag.tone]}`}>
                  {w.tag.label}
                </span>
              )}
            </>
          ) : (
            w.tag && (
              <span className={`rounded px-1.5 py-px text-sello font-medium ${tagCls[w.tag.tone]}`}>
                {w.tag.label}
              </span>
            )
          )}
          <span className="ml-auto text-apoyo text-ink-3">{w.kind}</span>
        </span>
      </button>

      {/* Espera tu OK: recordatorio se aprueba/rechaza inline; el detalle (editar/canal) en la Mesa */}
      {col === "por_aprobar" &&
        (r ? (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <button
              onClick={() =>
                run(
                  () => api.approve(r.id, canal),
                  (res) =>
                    res.aviso ??
                    (sombra ? "Retenido en modo prueba, no se envió." : "Aprobado, enviando"),
                  w.id,
                )
              }
              disabled={act}
              className={okBtn}
            >
              {sombra ? "Aprobar (sombra)" : "Aprobar y enviar"}
            </button>
            <button
              onClick={() => run(() => api.reject(r.id), "Rechazado", w.id)}
              disabled={act}
              className={ghBtn}
            >
              Rechazar
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => onOpen(w.id)}
            disabled={act}
            className={`mt-2.5 w-full ${ghBtn}`}
          >
            Revisar
          </button>
        ))}

      {/* En curso: fallido reintenta (approve), aprobado envía (send); sombra retiene */}
      {col === "sin_enviar" && r && (failed || !sombra) && (
        <div className="mt-2.5">
          {failed ? (
            <button
              onClick={() =>
                run(() => api.approve(r.id, canal), (res) => res.aviso ?? "Reintentando envío", w.id)
              }
              disabled={act}
              className={`w-full ${okBtn}`}
            >
              Reintentar
            </button>
          ) : (
            <button
              onClick={() => run(() => api.sendReminder(r.id), "Enviando", w.id)}
              disabled={act}
              className={`w-full ${okBtn}`}
            >
              Enviar ahora
            </button>
          )}
        </div>
      )}

      {/* Hecho: solo lectura, con el sello de la hora real de envío */}
      {col === "enviados" && (
        <p className="mt-2 inline-flex items-center gap-1.5 text-sello font-semibold text-ok">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" />
          Enviado {r?.sent_at ? haceTiempo(r.sent_at) : w.time}
        </p>
      )}

      {/* Rechazados: el detalle deja corregir y reenviar */}
      {col === "rechazados" && (
        <button
          type="button"
          onClick={() => onOpen(w.id)}
          disabled={act}
          className={`mt-2.5 w-full ${ghBtn}`}
        >
          Corregir y enviar
        </button>
      )}
    </div>
  );
}

// ── Filtro dinámico (buscar + chips componibles, estilo Whop) ───────────────────
type DropTarget = "enviar" | "rechazar";

const TIPO_LABEL: Record<WorkType, string> = {
  recordatorio: "Recordatorio",
  conciliacion: "Conciliación",
  promesa: "Promesa",
  cotizacion: "Cotización",
};

// Vencimiento en lenguaje HUMANO, no jerga de buckets. Cada opción agrupa los buckets
// reales de antigüedad (los técnicos siguen mandando por dentro) y los nombra por cuánto
// llevan vencidas las facturas — que es lo que el dueño realmente entiende y decide.
const VENC_OPCIONES: { key: string; label: string; sub: string; buckets: string[] }[] = [
  { key: "por_vencer", label: "Todavía no vencen", sub: "dentro de plazo", buckets: ["por_vencer", "vence_pronto"] },
  { key: "reciente", label: "Vencidas hace poco", sub: "1 a 15 días", buckets: ["vencida_reciente"] },
  { key: "semanas", label: "Vencidas hace semanas", sub: "16 a 45 días", buckets: ["vencida"] },
  { key: "meses", label: "Vencidas hace meses", sub: "más de 45 días", buckets: ["critica"] },
];
const VENC_BY_KEY: Record<string, string[]> = Object.fromEntries(
  VENC_OPCIONES.map((o) => [o.key, o.buckets]),
);

function FilterBar({
  search,
  onSearch,
  clientes,
  agents,
  types,
  vencOpts,
  fAgent,
  fType,
  fVenc,
  setFagent,
  setFtype,
  setFvenc,
  nFilters,
  total,
  onReset,
}: {
  search: string;
  onSearch: (s: string) => void;
  clientes: { name: string; count: number }[];
  agents: string[];
  types: WorkType[];
  vencOpts: { key: string; label: string; sub: string; buckets: string[] }[];
  fAgent: string | null;
  fType: WorkType | null;
  fVenc: string | null;
  setFagent: (s: string | null) => void;
  setFtype: (t: WorkType | null) => void;
  setFvenc: (v: string | null) => void;
  nFilters: number;
  total: number;
  onReset: () => void;
}) {
  const vencActivo = fVenc ? vencOpts.find((o) => o.key === fVenc) : null;
  return (
    <div className="shrink-0 border-b border-line px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <ClienteBuscador value={search} onChange={onSearch} clientes={clientes} />

        {agents.length > 1 && (
          <FilterChip
            label="Ayudante"
            valueLabel={fAgent ? agentDisplayName(fAgent) : null}
            onClear={() => setFagent(null)}
            onPick={(k) => setFagent(k || null)}
            options={[
              { key: "", node: <span className="text-ink-2">Todos</span> },
              ...agents.map((a) => ({
                key: a,
                node: (
                  <span className="flex items-center gap-2">
                    <Avatar slug={a} size={16} />
                    {agentDisplayName(a)}
                  </span>
                ),
              })),
            ]}
          />
        )}

        {types.length > 1 && (
          <FilterChip
            label="Tipo"
            valueLabel={fType ? TIPO_LABEL[fType] : null}
            onClear={() => setFtype(null)}
            onPick={(k) => setFtype((k as WorkType) || null)}
            options={[
              { key: "", node: <span className="text-ink-2">Todos</span> },
              ...types.map((t) => ({ key: t, node: TIPO_LABEL[t] })),
            ]}
          />
        )}

        {vencOpts.length > 0 && (
          <FilterChip
            label="Vencimiento"
            valueLabel={vencActivo ? vencActivo.label : null}
            onClear={() => setFvenc(null)}
            onPick={(k) => setFvenc(k || null)}
            options={[
              { key: "", node: <span className="text-ink-2">Cualquier fecha</span> },
              ...vencOpts.map((o) => ({
                key: o.key,
                node: (
                  <span className="flex flex-col leading-tight">
                    <span className="text-ink">{o.label}</span>
                    <span className="text-apoyo text-ink-3">{o.sub}</span>
                  </span>
                ),
              })),
            ]}
          />
        )}

        {nFilters > 0 && (
          <button
            onClick={onReset}
            className="text-cuerpo font-medium text-accent-ink transition-colors hover:text-accent-strong"
          >
            Limpiar
          </button>
        )}
        <span className="tnum ml-auto shrink-0 text-apoyo text-ink-3">{total} en el tablero</span>
      </div>
    </div>
  );
}

// Buscar cliente CON la lista de disponibles a la vista: al enfocar muestra a todos (el
// que más debe arriba); al escribir, filtra. Elegir uno lo fija; también acepta texto
// libre. Nada de teclear a ciegas sin saber a quién puedes buscar.
function ClienteBuscador({
  value,
  onChange,
  clientes,
}: {
  value: string;
  onChange: (s: string) => void;
  clientes: { name: string; count: number }[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const q = value.trim().toLowerCase();
  const matches = q ? clientes.filter((c) => c.name.toLowerCase().includes(q)) : clientes;
  const shown = matches.slice(0, 8);

  return (
    <div ref={ref} className="relative min-w-[190px] flex-1 sm:max-w-xs">
      <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3">
        <SearchIcon />
      </span>
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Buscar cliente…"
        aria-label="Buscar cliente"
        className="w-full rounded-md border border-line bg-surface py-1.5 pl-8 pr-7 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
      />
      {value && (
        <button
          onClick={() => {
            onChange("");
            setOpen(false);
          }}
          aria-label="Limpiar búsqueda"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded px-1 text-cuerpo leading-none text-ink-3 transition-colors hover:text-ink"
        >
          &times;
        </button>
      )}
      {open && clientes.length > 0 && (
        <div className="absolute left-0 top-full z-30 mt-1.5 max-h-64 w-full min-w-[220px] overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-[0_12px_32px_-12px_oklch(0.3_0.04_235/0.28)]">
          {shown.length === 0 ? (
            <p className="px-2 py-2 text-cuerpo text-ink-3">Ningún cliente coincide.</p>
          ) : (
            shown.map((c) => (
              <button
                key={c.name}
                onClick={() => {
                  onChange(c.name);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-cuerpo text-ink transition-colors hover:bg-panel"
              >
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                <span className="tnum shrink-0 rounded-full bg-panel px-1.5 py-px text-sello text-ink-3">
                  {c.count}
                </span>
              </button>
            ))
          )}
          {matches.length > shown.length && (
            <p className="px-2 py-1 text-apoyo text-ink-3">
              +{matches.length - shown.length} más · sigue escribiendo para acotar
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// Un chip de filtro con popover (inactivo: "+ Etiqueta"; activo: "Etiqueta: valor ×").
function FilterChip({
  label,
  valueLabel,
  options,
  onPick,
  onClear,
}: {
  label: string;
  valueLabel: string | null;
  options: { key: string; node: React.ReactNode }[];
  onPick: (key: string) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const active = valueLabel !== null;
  return (
    <div ref={ref} className="relative shrink-0">
      <div
        className={`flex items-center rounded-full border text-cuerpo font-medium transition-colors ${
          active
            ? "border-accent/40 bg-accent-soft text-accent-ink"
            : "border-line bg-surface text-ink-2 hover:border-line-strong"
        }`}
      >
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex items-center gap-1.5 py-1 pl-2.5 pr-1.5"
        >
          {active ? (
            <>
              <span className="text-ink-3">{label}:</span>
              <span>{valueLabel}</span>
            </>
          ) : (
            <>
              <PlusIcon />
              {label}
            </>
          )}
        </button>
        {active && (
          <button
            onClick={onClear}
            aria-label={`Quitar filtro ${label}`}
            className="pr-2 text-cuerpo leading-none text-ink-3 transition-colors hover:text-ink"
          >
            &times;
          </button>
        )}
      </div>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1.5 max-h-64 min-w-[190px] overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-[0_12px_32px_-12px_oklch(0.3_0.04_235/0.28)]">
          {options.map((o) => (
            <button
              key={o.key}
              onClick={() => {
                onPick(o.key);
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-cuerpo text-ink transition-colors hover:bg-panel"
            >
              {o.node}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// El pop-up de confirmación al soltar una tarjeta: el detalle + la acción, para que
// arrastrar sea satisfactorio SIN romper el HITL (nada sale sin este OK explícito).
function ConfirmSend({
  item,
  target,
  sombra,
  busy,
  onCancel,
  onConfirm,
}: {
  item: WorkItem;
  target: DropTarget;
  sombra: boolean;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (editedMessage?: string) => void;
}) {
  const r = item.reminder!;
  const canalLabel = r.channels.filter((c) => c.connected)[0]?.label ?? "WhatsApp";
  const enviar = target === "enviar";
  const dest = r.correo?.para ?? r.customer_phone ?? item.customer;
  // Editar aquí mismo, igual que en la Mesa: null = burbuja de solo lectura;
  // un string = borrador editándose. Solo se ofrece al aprobar/enviar (no al rechazar).
  const [editing, setEditing] = useState<string | null>(null);
  return (
    <Modal
      open
      onClose={onCancel}
      size="sm"
      title={enviar ? (sombra ? "Aprobar (modo prueba)" : "Aprobar y enviar") : "Rechazar recordatorio"}
      subtitle={item.customer}
    >
      <div className="space-y-3.5">
        <div className="flex items-center gap-2 text-cuerpo text-ink-3">
          por
          <Avatar slug={item.agent} size={16} />
          <span className="font-medium text-ink-2">
            {item.ayudante || agentDisplayName(item.agent)}
          </span>
          {item.amount != null && (
            <span className="tnum ml-auto font-semibold text-ink">{mxn(item.amount)}</span>
          )}
        </div>
        {editing === null ? (
          <div>
            <div className="rounded-2xl rounded-tl-sm border border-line bg-panel/50 px-4 py-3">
              <WaText className="text-cuerpo leading-relaxed text-ink">{r.message}</WaText>
            </div>
            {enviar && (
              <button
                onClick={() => setEditing(r.message)}
                className="mt-1.5 text-apoyo text-ink-3 underline-offset-2 hover:text-ink hover:underline"
              >
                Editar
              </button>
            )}
          </div>
        ) : (
          <div>
            <textarea
              value={editing}
              onChange={(e) => setEditing(e.target.value)}
              rows={5}
              autoFocus
              className="w-full resize-y rounded-2xl rounded-tl-sm border border-accent/40 bg-panel/50 px-4 py-3 text-cuerpo leading-relaxed text-ink outline-none focus:border-accent"
            />
            <div className="mt-1 flex items-center gap-2 text-apoyo text-ink-3">
              <span>Tú lo editas; tu ayudante aprende de tus cambios.</span>
              <button
                onClick={() => setEditing(null)}
                className="underline-offset-2 hover:text-ink hover:underline"
              >
                Cancelar
              </button>
            </div>
          </div>
        )}
        <p className="text-cuerpo leading-relaxed text-ink-3">
          {enviar
            ? sombra
              ? `Modo prueba: se aprueba pero NO se envía a ${dest}. Queda en En curso.`
              : `Se envía por ${canalLabel} a ${dest}.`
            : "Queda en Rechazados. Puedes corregirlo y reenviarlo después."}
        </p>
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() =>
              onConfirm(
                enviar && editing !== null && editing !== r.message ? editing : undefined,
              )
            }
            disabled={busy}
            className={`rounded-md px-4 py-2 text-cuerpo font-medium text-surface transition-colors disabled:opacity-50 ${
              enviar ? "bg-accent hover:bg-accent-strong" : "bg-ink hover:bg-ink/90"
            }`}
          >
            {enviar
              ? sombra
                ? "Aprobar (no se envía)"
                : `Aprobar y enviar por ${canalLabel}`
              : "Rechazar"}
          </button>
          <button
            onClick={onCancel}
            className="rounded-md border border-line bg-surface px-3.5 py-2 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
          >
            Cancelar
          </button>
        </div>
      </div>
    </Modal>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden>
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="m11 11 3 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" aria-hidden>
      <path d="M6 2.5v7M2.5 6h7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

function BoardSkeleton() {
  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 md:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="rounded-xl border border-line bg-panel/50 p-2">
          <Skeleton className="mb-2 h-5 w-24 rounded" />
          <div className="space-y-2">
            {[0, 1].map((j) => (
              <Skeleton key={j} className="h-24 w-full rounded-lg" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
      className="mt-px shrink-0 text-accent-ink"
    >
      <path
        d="M8 1.5 14 5v3c0 4-2.7 6-6 6.5C4 14 1.5 12 1.5 8V5L8 1.5Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <path
        d="M5.5 8 7 9.5 10.5 6"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Contexto del cliente, plegado en la Mesa: una tira compacta con lo que ayuda a
//    decidir (quién es, cuánto debe, de dónde viene el dato). El nombre liga a la ficha.
function ContextoInline({
  item,
  customer,
}: {
  item: WorkItem;
  customer: CustomerDetail | null;
}) {
  const phone = customer?.phone ?? item.reminder?.customer_phone ?? null;
  const customerId = customer?.id ?? item.customerId ?? item.reminder?.customer_id ?? null;
  const presence = customer?.presence ?? item.reminder?.procedencia?.presence ?? null;
  const nombre = customer?.name ?? item.customer;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-line bg-panel/40 px-4 py-2.5 text-cuerpo">
      {customerId ? (
        <Link
          href={`/clientes/detalle?id=${customerId}`}
          className="font-semibold text-ink underline-offset-2 transition-colors hover:text-accent-ink hover:underline"
        >
          {nombre} ›
        </Link>
      ) : (
        <span className="font-semibold text-ink">{nombre}</span>
      )}
      {item.reminder?.correo?.para ? (
        <span className="tnum text-ink-3">Correo {item.reminder.correo.para}</span>
      ) : (
        phone && <span className="tnum text-ink-3">WhatsApp {phone}</span>
      )}
      {customer ? (
        <span className="text-ink-3">
          por cobrar · {customer.open_count} fact.{" "}
          <span className="tnum font-semibold text-ink">{mxn(customer.open_total)}</span>
        </span>
      ) : (
        item.amount != null && (
          <span className="text-ink-3">
            {item.type === "cotizacion" ? "cotización" : "monto"}{" "}
            <span className="tnum font-semibold text-ink">{mxn(item.amount)}</span>
          </span>
        )
      )}
      {presence && Object.keys(presence).length > 0 && (
        <span className="ml-auto">
          <SourceBadge source={item.reminder?.procedencia?.source ?? "odoo"} presence={presence} />
        </span>
      )}
    </div>
  );
}
