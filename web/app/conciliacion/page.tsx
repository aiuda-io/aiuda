"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api,
  CONCILIACION_ORIGEN,
  mxn,
  type DichoPago,
  type InvoiceItem,
  type ReconcileBandeja,
  type ReconcileItem,
  type ReconcileResuelto,
} from "@/lib/api";
import { fechaDM } from "@/lib/format";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  PrimaryButton,
  SecondaryButton,
  SecondaryLink,
  Skeleton,
  Tabs,
  useApi,
} from "@/components/ui";
import { RailLayout, RailSection, RailStat } from "@/components/rail";
import { toast } from "@/components/toast";
import { ExportButton } from "@/components/export-button";
import { Drawer } from "@/components/drawer";
import { settingsInputCls } from "@/components/settings";
import { BancoUpload } from "@/components/banco-upload";

// Entró dinero: flecha hacia abajo a una línea (depósito).
const IconDeposit = (
  <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 2.5v6.5M5.3 6.3 8 9l2.7-2.7" />
    <path d="M3 12.5h10" />
  </svg>
);
// Factura: documento.
const IconDoc = (
  <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4.5 2.5h5L12 5v8.5H4.5z" />
    <path d="M9 2.5V5h3" />
  </svg>
);

/** Una opción elegible para aplicar el pago: una factura sola o un grupo de facturas. */
type Opcion = {
  key: string; // "inv:<invoice_id>" | "grp:<n>" — estable dentro del pago
  invoiceIds: string[];
  etiqueta: string; // "F-104 · Papelería Bic"
  monto: number; // saldo (factura) o total (grupo)
  detalle: string; // "vence 31 may" | "2 facturas"
  reason: string;
  cuadra: boolean;
  parcial: boolean;
  saldoRestante: number; // si es abono: lo que quedaría abierto
};

function opcionesDe(item: ReconcileItem): Opcion[] {
  const singles = [item.proposal, ...item.alternates]
    .filter((c): c is NonNullable<typeof c> => c !== null)
    .map((c) => ({
      key: `inv:${c.invoice_id}`,
      invoiceIds: [c.invoice_id],
      etiqueta: `${c.folio} · ${c.customer}`,
      monto: c.saldo,
      detalle:
        c.saldo < c.amount
          ? `saldo de ${mxn(c.amount)} · vence ${fechaDM(c.due_date)}`
          : `vence ${fechaDM(c.due_date)}`,
      reason: c.reason,
      cuadra: c.cuadra,
      parcial: c.parcial,
      saldoRestante: Math.max(0, c.saldo - item.amount),
    }));
  const grupos = item.grupos.map((g, n) => ({
    key: `grp:${n}`,
    invoiceIds: g.invoice_ids,
    etiqueta: `${g.folios.join(" + ")} · ${g.customer}`,
    monto: g.total,
    detalle: `${g.folios.length} facturas juntas`,
    reason: g.reason,
    cuadra: g.cuadra,
    parcial: false,
    saldoRestante: 0,
  }));
  // El orden respeta la propuesta: si el ayudante propone el grupo, va primero.
  return item.propuesta_tipo === "grupo" ? [...grupos, ...singles] : [...singles, ...grupos];
}

function defaultKey(item: ReconcileItem): string {
  // Ambiguo = el ayudante NO preselecciona: el humano elige a mano.
  if (item.ambiguo) return "";
  const opts = opcionesDe(item);
  return opts[0]?.key ?? "";
}

export default function ConciliacionPage() {
  const { data, error, loading, refetch } = useApi<ReconcileBandeja>(api.reconciliation);
  const [tab, setTab] = useState<"pendientes" | "dichos" | "resueltos">("pendientes");
  // Opción elegida por pago (default: la que propone el ayudante; vacío si es ambiguo).
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [registrar, setRegistrar] = useState(false);
  const [subirEstado, setSubirEstado] = useState(false);

  const items = useMemo(() => data?.pending ?? [], [data]);
  const dichos = useMemo(() => data?.dichos ?? [], [data]);

  // Historial solo cuando se abre su pestaña.
  const resueltosApi = useApi<{ resueltos: ReconcileResuelto[]; count: number }>(
    () =>
      tab === "resueltos"
        ? api.reconcileResueltos()
        : Promise.resolve({ resueltos: [], count: 0 }),
    [tab],
  );

  const resumen = useMemo(
    () => ({
      pagos: items.length,
      monto: items.reduce((a, it) => a + it.amount, 0),
      cuadran: items.filter((it) => it.proposal?.cuadra || it.propuesta_tipo === "grupo").length,
      ambiguos: items.filter((it) => it.ambiguo).length,
    }),
    [items],
  );

  async function confirmar(item: ReconcileItem, opcion: Opcion) {
    setBusy(item.id);
    try {
      const res = await api.confirmReconcile(item.id, opcion.invoiceIds);
      const cerradas = res.invoices.filter((i) => i.cerrada);
      const abonos = res.invoices.filter((i) => !i.cerrada);
      const partes = [
        cerradas.length > 0 &&
          `${cerradas.map((i) => i.folio).join(", ")} pasa${cerradas.length > 1 ? "n" : ""} a Pagadas`,
        abonos.length > 0 &&
          `${abonos.map((i) => `${i.folio} queda abierta con saldo de ${mxn(i.saldo)}`).join("; ")}`,
      ].filter(Boolean);
      toast(`Conciliado: ${partes.join(". ")}.`, "success");
      refetch();
      resueltosApi.refetch();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function rechazar(item: { id: string }) {
    setBusy(item.id);
    try {
      await api.ignoreReconcile(item.id);
      toast("Pago rechazado: queda en Resueltos, no toca ninguna factura.", "info");
      refetch();
      resueltosApi.refetch();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function conciliarDicho(d: DichoPago) {
    if (!d.respaldo) return;
    setBusy(d.invoice_id);
    try {
      await api.confirmReconcile(d.respaldo.payment_id, [d.invoice_id]);
      toast(`Conciliado: ${d.folio} pasa a Pagadas.`, "success");
      refetch();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Conciliación"
        subtitle="Lo trabaja tu ayudante de conciliación. Por cada pago que entró, propone la factura (o facturas) que liquida y te dice por qué; tú confirmas, cambias o rechazas. Nada se cierra solo."
        right={
          <div className="flex items-center gap-2">
            {/* El export baja el historial (resueltos): lo pendiente aún no es un hecho. */}
            {tab === "resueltos" && <ExportButton entidad="conciliacion" />}
            <SecondaryButton onClick={() => setSubirEstado(true)}>
              Subir estado de cuenta
            </SecondaryButton>
            <PrimaryButton onClick={() => setRegistrar(true)}>Registrar un pago</PrimaryButton>
          </div>
        }
      />

      <RegistrarPagoSheet
        open={registrar}
        onClose={() => setRegistrar(false)}
        onSaved={refetch}
      />

      <Drawer
        open={subirEstado}
        onClose={() => setSubirEstado(false)}
        title="Subir estado de cuenta"
        subtitle="El PDF que te manda tu banco cada mes; los depósitos entran aquí"
      >
        <BancoUpload onImported={refetch} />
      </Drawer>

      <Tabs
        tabs={[
          { key: "pendientes", label: "Por conciliar", count: items.length },
          { key: "dichos", label: "Dichos de pago", count: dichos.length },
          { key: "resueltos", label: "Resueltos" },
        ]}
        active={tab}
        onChange={(k) => setTab(k as typeof tab)}
      />

      {loading && (
        <div className="space-y-4">
          <Skeleton className="h-40 w-full rounded-xl" />
          <Skeleton className="h-40 w-full rounded-xl" />
        </div>
      )}

      {!loading && data && (
        <RailLayout
          rail={
            <>
              <RailSection label="Por conciliar">
                <RailStat label="Pagos" value={String(resumen.pagos)} strong />
                <RailStat label="Monto entrado" value={mxn(resumen.monto)} />
                <RailStat
                  label="Con propuesta clara"
                  value={String(resumen.cuadran)}
                  hint={resumen.cuadran > 0 ? "listos para confirmar" : undefined}
                />
                {resumen.ambiguos > 0 && (
                  <RailStat
                    label="Decides tú"
                    value={String(resumen.ambiguos)}
                    hint="candidatas parejas, sin propuesta"
                  />
                )}
              </RailSection>
              <FuentesRail fuentes={data.fuentes} />
              <ToleranciaRail config={data.config} onSaved={refetch} />
            </>
          }
        >
          {tab === "pendientes" && (
            <ListaPendientes
              items={items}
              choice={choice}
              setChoice={setChoice}
              busy={busy}
              onConfirm={confirmar}
              onReject={rechazar}
              onRegistrar={() => setRegistrar(true)}
              onSubirEstado={() => setSubirEstado(true)}
            />
          )}
          {tab === "dichos" && (
            <ListaDichos dichos={dichos} busy={busy} onConciliar={conciliarDicho} />
          )}
          {tab === "resueltos" && (
            <ListaResueltos
              data={resueltosApi.data?.resueltos ?? []}
              loading={resueltosApi.loading}
            />
          )}
        </RailLayout>
      )}
    </div>
  );
}

// ── Pendientes: el pago y sus opciones, con la evidencia ─────────────────────

function ListaPendientes({
  items,
  choice,
  setChoice,
  busy,
  onConfirm,
  onReject,
  onRegistrar,
  onSubirEstado,
}: {
  items: ReconcileItem[];
  choice: Record<string, string>;
  setChoice: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  busy: string | null;
  onConfirm: (item: ReconcileItem, opcion: Opcion) => void;
  onReject: (item: { id: string }) => void;
  onRegistrar: () => void;
  onSubirEstado: () => void;
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="Nada por conciliar"
        action={
          <div className="flex flex-wrap items-center justify-center gap-2">
            <SecondaryButton onClick={onSubirEstado}>Subir estado de cuenta</SecondaryButton>
            <SecondaryButton onClick={onRegistrar}>Registrar un pago</SecondaryButton>
            <SecondaryLink href="/integraciones">Conectar tu banco</SecondaryLink>
          </div>
        }
      >
        Sube el PDF del estado de cuenta que te manda tu banco y los depósitos entran aquí:
        tu ayudante los empareja con la factura que liquidan y tú confirmas. ¿Te depositaron
        por fuera? Regístralo a mano y entra a esta misma bandeja.
      </EmptyState>
    );
  }
  return (
    <ul className="reveal-stagger space-y-4">
      {items.map((item) => {
        const opts = opcionesDe(item);
        const selKey = choice[item.id] ?? defaultKey(item);
        const sel = opts.find((o) => o.key === selKey) ?? null;
        const diff = sel ? item.amount - sel.monto : 0;
        return (
          <li key={item.id} className="overflow-hidden rounded-xl border border-line bg-surface">
            <div className="grid grid-cols-1 items-stretch sm:grid-cols-[1fr_auto_1fr]">
              {/* PAGO RECIBIDO — el dinero que entró */}
              <div className="bg-accent-soft/40 p-4">
                <p className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-accent-ink">
                  {IconDeposit} Pago recibido
                </p>
                <p className="tnum mt-2 text-[20px] font-semibold leading-none text-ink">
                  {mxn(item.amount)}
                </p>
                <p className="mt-1.5 text-[11.5px] text-ink-3">
                  {CONCILIACION_ORIGEN[item.source] ?? item.source} · {fechaDM(item.paid_at)}
                </p>
                {item.origen && (
                  <p className="mt-0.5 text-[11px] text-ink-3">{item.origen}</p>
                )}
                {item.counterparty && (
                  <p className="mt-0.5 truncate text-[12px] text-ink-2" title={item.counterparty}>
                    {item.counterparty}
                  </p>
                )}
                {item.reference && (
                  <p className="mt-0.5 truncate text-[11.5px] text-ink-3" title={item.reference}>
                    ref. {item.reference}
                  </p>
                )}
              </div>

              {/* Indicador de match: compara los montos */}
              <div className="flex items-center justify-center border-line bg-panel/30 px-3 py-1 sm:flex-col sm:border-x">
                <span
                  className={`tnum rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                    !sel
                      ? "bg-panel text-ink-3"
                      : sel.cuadra
                        ? "bg-ok-soft text-ok"
                        : sel.parcial
                          ? "bg-warn-soft text-warn"
                          : "bg-warn-soft text-warn"
                  }`}
                >
                  {!sel
                    ? item.ambiguo
                      ? "elige tú"
                      : "sin factura"
                    : sel.cuadra
                      ? "= cuadra"
                      : sel.parcial
                        ? "abono"
                        : `≠ ${mxn(Math.abs(diff))}`}
                </span>
              </div>

              {/* LO QUE LIQUIDA — factura sola o grupo */}
              <div className="border-t border-line p-4 sm:border-t-0">
                <p className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                  {IconDoc} {sel && sel.invoiceIds.length > 1 ? "Facturas por cobrar" : "Factura por cobrar"}
                </p>
                {sel ? (
                  <>
                    <p className="mt-2 text-[14px] font-semibold leading-tight text-ink">
                      {sel.etiqueta}
                    </p>
                    <p className="tnum mt-1 text-[12.5px] text-ink-2">{mxn(sel.monto)}</p>
                    <p className="mt-0.5 text-[11.5px] text-ink-3">{sel.detalle}</p>
                  </>
                ) : item.ambiguo ? (
                  <p className="mt-2 text-[12.5px] text-ink-2">
                    {opts.length} opciones parejas. Elige abajo cuál liquida este pago.
                  </p>
                ) : (
                  <p className="mt-2 text-[12.5px] text-ink-3">
                    Tu ayudante no encontró una factura abierta que coincida.
                  </p>
                )}
              </div>
            </div>

            {/* Ambiguo: el ayudante lo dice y no elige */}
            {item.ambiguo && (
              <p className="border-t border-line bg-warn-soft/40 px-4 py-2 text-[12px] text-warn">
                {item.nota}
              </p>
            )}

            {/* Opciones (radio): facturas solas y grupos, cada una con su evidencia */}
            {opts.length > (item.ambiguo ? 0 : 1) && (
              <div className="border-t border-line px-4 py-3">
                <p className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-ink-3">
                  {item.ambiguo ? "Elige la que corresponde" : "¿Es otra? Cámbiala"}
                </p>
                <div className="mt-2 space-y-1.5">
                  {opts.map((o) => (
                    <label
                      key={o.key}
                      className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 transition-colors ${
                        selKey === o.key
                          ? "border-accent bg-accent-soft/30"
                          : "border-line hover:border-line-strong"
                      }`}
                    >
                      <input
                        type="radio"
                        name={`opcion-${item.id}`}
                        checked={selKey === o.key}
                        onChange={() => setChoice((c) => ({ ...c, [item.id]: o.key }))}
                        className="mt-1 accent-[var(--color-accent)]"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-baseline gap-x-2 text-[12.5px] font-medium text-ink">
                          {o.etiqueta}
                          <span className="tnum font-normal text-ink-2">{mxn(o.monto)}</span>
                          {o.parcial && (
                            <span className="rounded bg-warn-soft px-1.5 text-[10.5px] font-semibold text-warn">
                              abono
                            </span>
                          )}
                          {o.invoiceIds.length > 1 && (
                            <span className="rounded bg-line/60 px-1.5 text-[10.5px] font-semibold text-ink-2">
                              {o.invoiceIds.length} facturas
                            </span>
                          )}
                        </span>
                        <span className="mt-0.5 block text-[11.5px] leading-snug text-ink-3">
                          {o.reason}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Por qué + qué va a pasar + acciones */}
            <div className="flex flex-wrap items-center gap-2 border-t border-line bg-panel/20 px-4 py-3">
              <div className="mr-auto min-w-0">
                {sel?.reason && opts.length <= 1 && (
                  <p className="text-[11.5px] text-ink-3">
                    <span className="font-medium text-ink-2">Por qué: </span>
                    {sel.reason}
                  </p>
                )}
                {sel?.parcial && (
                  <p className="text-[11.5px] text-warn">
                    Pago parcial: se abonan {mxn(item.amount)} y la factura queda abierta con
                    saldo de {mxn(sel.saldoRestante)}.
                  </p>
                )}
              </div>
              <button
                onClick={() => sel && onConfirm(item, sel)}
                disabled={busy !== null || !sel}
                className="rounded-md bg-accent px-3.5 py-1.5 text-[12.5px] font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
              >
                {busy === item.id
                  ? "Conciliando…"
                  : sel?.parcial
                    ? "Aplicar abono"
                    : "Confirmar pago"}
              </button>
              <button
                onClick={() => onReject(item)}
                disabled={busy !== null}
                className="rounded-md border border-line bg-surface px-3 py-1.5 text-[12.5px] font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
              >
                Rechazar
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ── Dichos de pago: el cliente dice que pagó; el banco lo confirma o no ──────

function ListaDichos({
  dichos,
  busy,
  onConciliar,
}: {
  dichos: DichoPago[];
  busy: string | null;
  onConciliar: (d: DichoPago) => void;
}) {
  if (dichos.length === 0) {
    return (
      <EmptyState title="Sin dichos de pago pendientes">
        Cuando un cliente diga por WhatsApp que ya pagó, la factura aparece aquí hasta que un
        movimiento del banco o Stripe lo respalde. Un dicho no es un pago.
      </EmptyState>
    );
  }
  return (
    <ul className="reveal-stagger space-y-3">
      {dichos.map((d) => (
        <li key={d.invoice_id} className="rounded-xl border border-line bg-surface p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[13.5px] font-semibold text-ink">
                {d.folio}
                <span className="font-normal text-ink-2"> · {d.customer}</span>
              </p>
              <p className="tnum mt-0.5 text-[12.5px] text-ink-2">
                {d.saldo < d.amount
                  ? `saldo ${mxn(d.saldo)} de ${mxn(d.amount)}`
                  : mxn(d.amount)}
                <span className="text-ink-3"> · vence {fechaDM(d.due_date)}</span>
              </p>
              <p className="mt-2 text-[12px] leading-relaxed text-ink-3">
                El cliente dice que ya pagó.{" "}
                {d.respaldo ? (
                  <span className="text-ok">
                    El banco lo respalda: entró {mxn(d.respaldo.amount)} (
                    {CONCILIACION_ORIGEN[d.respaldo.source] ?? d.respaldo.source}) el{" "}
                    {fechaDM(d.respaldo.paid_at)}.
                  </span>
                ) : (
                  <span>
                    Sin movimiento en banco o Stripe que lo respalde todavía; la factura sigue
                    abierta.
                  </span>
                )}
              </p>
            </div>
            {d.respaldo ? (
              <button
                onClick={() => onConciliar(d)}
                disabled={busy !== null}
                className="shrink-0 rounded-md bg-accent px-3.5 py-1.5 text-[12.5px] font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
              >
                {busy === d.invoice_id ? "Conciliando…" : "Conciliar y cerrar"}
              </button>
            ) : (
              <span className="shrink-0 rounded-full bg-panel px-2.5 py-1 text-[11px] font-semibold text-ink-3">
                sin respaldo aún
              </span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

// ── Resueltos: historial de decisiones (rastrear qué se hizo y por qué) ──────

function ListaResueltos({ data, loading }: { data: ReconcileResuelto[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-16 w-full rounded-xl" />
        <Skeleton className="h-16 w-full rounded-xl" />
      </div>
    );
  }
  if (data.length === 0) {
    return (
      <EmptyState title="Aún no hay pagos resueltos">
        Aquí queda el rastro de cada decisión: qué pago se aplicó a qué facturas, cuál se
        rechazó y cuándo.
      </EmptyState>
    );
  }
  return (
    <ul className="space-y-2.5">
      {data.map((r) => (
        <li key={r.id} className="rounded-xl border border-line bg-surface px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <p className="tnum text-[13.5px] font-semibold text-ink">
              {mxn(r.amount)}
              <span className="ml-2 text-[11.5px] font-normal text-ink-3">
                {CONCILIACION_ORIGEN[r.source] ?? r.source} · {fechaDM(r.paid_at)}
              </span>
            </p>
            <span
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                r.status === "conciliado" ? "bg-ok-soft text-ok" : "bg-line/60 text-ink-2"
              }`}
            >
              {r.status === "conciliado" ? "Conciliado" : "Rechazado"}
            </span>
          </div>
          {r.counterparty && (
            <p className="mt-0.5 truncate text-[11.5px] text-ink-3">{r.counterparty}</p>
          )}
          {r.origen && <p className="mt-0.5 text-[11px] text-ink-3">{r.origen}</p>}
          {r.aplicaciones.length > 0 && (
            <p className="mt-1.5 text-[12px] text-ink-2">
              {r.aplicaciones
                .map((a) =>
                  a.cerrada
                    ? `${a.folio} cerrada (${mxn(a.aplicado)})`
                    : `${a.folio} abono de ${mxn(a.aplicado)} (queda ${mxn(a.saldo)})`,
                )
                .join(" · ")}
              {r.excedente > 0 && (
                <span className="text-ink-3"> · excedente de {mxn(r.excedente)} registrado</span>
              )}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

// ── Registrar un pago a mano: entra a la bandeja, no cierra nada solo ────────

function hoyLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function RegistrarPagoSheet({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [monto, setMonto] = useState("");
  const [fecha, setFecha] = useState(hoyLocal());
  const [referencia, setReferencia] = useState("");
  const [quien, setQuien] = useState("");
  const [invoiceId, setInvoiceId] = useState("");
  const [abiertas, setAbiertas] = useState<InvoiceItem[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMonto("");
    setFecha(hoyLocal());
    setReferencia("");
    setQuien("");
    setInvoiceId("");
    setBusy(false);
    api.invoices("open").then(setAbiertas).catch(() => {});
  }, [open]);

  const nMonto = Number(monto);
  const valido = Number.isFinite(nMonto) && nMonto > 0 && Boolean(fecha);

  async function guardar() {
    setBusy(true);
    try {
      await api.createPayment({
        amount: nMonto,
        paid_at: fecha,
        reference: referencia.trim() || undefined,
        counterparty: quien.trim() || undefined,
        // Pista para el ayudante; la aplicación a la factura sigue siendo tu decisión.
        invoice_id: invoiceId || undefined,
      });
      toast(
        "Pago registrado: ya está en Por conciliar. Tu ayudante propone la factura y tú confirmas.",
        "success",
      );
      onSaved();
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Registrar un pago"
      subtitle="Un depósito que no llegó solo (efectivo, transferencia directa)"
    >
      <div className="space-y-3">
        <p className="rounded-lg border border-line bg-panel/40 px-3.5 py-3 text-[12px] leading-relaxed text-ink-2">
          El pago entra a la bandeja de conciliación como cualquier movimiento del banco: tu
          ayudante de conciliación propone la factura que liquida y tú confirmas. Nada se
          cierra solo.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.06em] text-ink-3">Monto</span>
            <input
              className={`${settingsInputCls} mt-1`}
              inputMode="decimal"
              value={monto}
              onChange={(e) => setMonto(e.target.value)}
              placeholder="0.00"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.06em] text-ink-3">Fecha</span>
            <input
              className={`${settingsInputCls} mt-1`}
              type="date"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.06em] text-ink-3">Referencia</span>
            <input
              className={`${settingsInputCls} mt-1`}
              value={referencia}
              onChange={(e) => setReferencia(e.target.value)}
              placeholder="SPEI 123 (opcional)"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-[0.06em] text-ink-3">Quién depositó</span>
            <input
              className={`${settingsInputCls} mt-1`}
              value={quien}
              onChange={(e) => setQuien(e.target.value)}
              placeholder="opcional"
            />
          </label>
        </div>
        <label className="block">
          <span className="text-[11px] uppercase tracking-[0.06em] text-ink-3">
            Factura (opcional, como pista)
          </span>
          <select
            className={`${settingsInputCls} mt-1`}
            value={invoiceId}
            onChange={(e) => setInvoiceId(e.target.value)}
          >
            <option value="">Que la proponga el ayudante</option>
            {abiertas.map((inv) => (
              <option key={inv.id} value={inv.id}>
                {inv.folio} · {inv.customer} · {mxn(inv.amount)}
              </option>
            ))}
          </select>
        </label>
        <PrimaryButton onClick={guardar} disabled={!valido || busy}>
          {busy ? "Registrando…" : "Registrar pago"}
        </PrimaryButton>
      </div>
    </Drawer>
  );
}

// ── Riel: fuentes de confirmación (honesto) y tolerancia ─────────────────────

const FUENTE_LABEL: Record<string, string> = { belvo: "Banco (Belvo)", stripe: "Stripe" };

function FuentesRail({
  fuentes,
}: {
  fuentes: Record<string, { configurada: boolean; verificada_en_vivo: boolean }>;
}) {
  return (
    <RailSection label="Fuentes de confirmación">
      <div className="space-y-2">
        {Object.entries(fuentes).map(([key, f]) => (
          <div key={key} className="border-b border-line/50 pb-2 last:border-0">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[12px] text-ink-2">{FUENTE_LABEL[key] ?? key}</span>
              <span
                className={`text-[11px] font-semibold ${f.configurada ? "text-ok" : "text-ink-3"}`}
              >
                {f.configurada ? "conectada" : "sin conectar"}
              </span>
            </div>
            {/* Honestidad: el conector existe y tiene contrato, pero nunca ha corrido
                contra la API real del proveedor. */}
            {!f.verificada_en_vivo && (
              <p className="mt-0.5 text-[11px] text-ink-3">pendiente de verificar en vivo</p>
            )}
          </div>
        ))}
      </div>
    </RailSection>
  );
}

function ToleranciaRail({
  config,
  onSaved,
}: {
  config: { tolerancia_pct: number; tolerancia_abs: number };
  onSaved: () => void;
}) {
  const [pct, setPct] = useState(String(config.tolerancia_pct));
  const [abs, setAbs] = useState(String(config.tolerancia_abs));
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setPct(String(config.tolerancia_pct));
    setAbs(String(config.tolerancia_abs));
  }, [config.tolerancia_pct, config.tolerancia_abs]);

  const dirty =
    pct !== String(config.tolerancia_pct) || abs !== String(config.tolerancia_abs);

  async function guardar() {
    const nPct = Number(pct);
    const nAbs = Number(abs);
    if (!Number.isFinite(nPct) || !Number.isFinite(nAbs) || nPct < 0 || nAbs < 0) {
      toast("La tolerancia debe ser un número igual o mayor a cero.", "error");
      return;
    }
    setSaving(true);
    try {
      await api.saveReconcileConfig({ tolerancia_pct: nPct, tolerancia_abs: nAbs });
      toast("Tolerancia guardada: las propuestas se recalculan.", "success");
      onSaved();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <RailSection label="Tolerancia de monto">
      <p className="text-[11.5px] leading-relaxed text-ink-3">
        Cuánta diferencia entre pago y factura sigue contando como match (redondeos,
        comisiones). Se toma la mayor de las dos.
      </p>
      <div className="mt-2.5 space-y-2">
        <label className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-ink-2">Porcentaje</span>
          <span className="flex items-center gap-1">
            <input
              type="number"
              min="0"
              max="100"
              step="0.5"
              value={pct}
              onChange={(e) => setPct(e.target.value)}
              className="tnum w-16 rounded-md border border-line bg-surface px-2 py-1 text-right text-[12px] text-ink focus:border-accent focus:outline-none"
            />
            <span className="text-[11.5px] text-ink-3">%</span>
          </span>
        </label>
        <label className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-ink-2">Mínimo en pesos</span>
          <span className="flex items-center gap-1">
            <span className="text-[11.5px] text-ink-3">$</span>
            <input
              type="number"
              min="0"
              step="1"
              value={abs}
              onChange={(e) => setAbs(e.target.value)}
              className="tnum w-16 rounded-md border border-line bg-surface px-2 py-1 text-right text-[12px] text-ink focus:border-accent focus:outline-none"
            />
          </span>
        </label>
        {dirty && (
          <button
            onClick={guardar}
            disabled={saving}
            className="w-full rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
          >
            {saving ? "Guardando…" : "Guardar tolerancia"}
          </button>
        )}
      </div>
    </RailSection>
  );
}
