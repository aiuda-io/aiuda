"use client";

// Pestaña Pagos de Cartera: el dinero que entró y a qué factura corresponde. Por cada
// depósito, aiuda propone la factura (o facturas) que paga y dice por qué; el dueño
// confirma, cambia o rechaza. Nada se cierra solo.
//
// Sus tres vistas (por confirmar, lo que el cliente dice que pagó, lo ya resuelto) son
// un FILTRO de la lista, no pestañas dentro de la pestaña.

import { useEffect, useMemo, useState } from "react";
import {
  api,
  CONCILIACION_ORIGEN,
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
  PrimaryButton,
  SecondaryButton,
  Skeleton,
  inputCls,
  useApi,
} from "@/components/ui";
import { toast } from "@/components/toast";
import { ExportButton } from "@/components/export-button";
import { Drawer } from "@/components/drawer";
import { BancoUpload } from "@/components/banco-upload";
import { Filtro } from "@/components/cartera-partes";
import { dinero, dineroPorMoneda, leerFallo, plural, totalesPorMoneda } from "@/lib/cartera";

type Vista = "pendientes" | "dichos" | "resueltos";

/** Una opción elegible para aplicar el pago: una factura sola o un grupo de facturas. */
type Opcion = {
  key: string; // "inv:<invoice_id>" | "grp:<n>", estable dentro del pago
  invoiceIds: string[];
  etiqueta: string;
  monto: number; // saldo (factura) o total (grupo)
  detalle: string;
  reason: string;
  cuadra: boolean;
  parcial: boolean;
  saldoRestante: number; // si es un pago parcial: lo que quedaría abierto
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
          ? `le falta esto de ${dinero(c.amount, item.currency)}, vence ${fechaDM(c.due_date)}`
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
  // El orden respeta la propuesta: si se propone el grupo, va primero.
  return item.propuesta_tipo === "grupo" ? [...grupos, ...singles] : [...singles, ...grupos];
}

function defaultKey(item: ReconcileItem): string {
  // Si hay varias igual de probables no se preselecciona ninguna: elige el dueño.
  if (item.ambiguo) return "";
  return opcionesDe(item)[0]?.key ?? "";
}

export function CarteraPagos({ onChanged }: { onChanged?: () => void }) {
  const { data, error, loading, refetch, refetchQuiet } = useApi<ReconcileBandeja>(api.reconciliation);
  const [vista, setVista] = useState<Vista>("pendientes");
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [registrar, setRegistrar] = useState(false);
  const [subirEstado, setSubirEstado] = useState(false);

  const items = useMemo(() => data?.pending ?? [], [data]);
  const dichos = useMemo(() => data?.dichos ?? [], [data]);

  // El historial se pide solo cuando se elige verlo.
  const resueltosApi = useApi<{ resueltos: ReconcileResuelto[]; count: number }>(
    () =>
      vista === "resueltos" ? api.reconcileResueltos() : Promise.resolve({ resueltos: [], count: 0 }),
    [vista],
  );

  const entrado = useMemo(
    () => totalesPorMoneda(items, (it) => it.amount, (it) => it.currency),
    [items],
  );

  const cambio = () => {
    refetchQuiet();
    onChanged?.();
  };

  async function confirmar(item: ReconcileItem, opcion: Opcion) {
    setBusy(item.id);
    try {
      const res = await api.confirmReconcile(item.id, opcion.invoiceIds);
      const cerradas = res.invoices.filter((i) => i.cerrada);
      const abonos = res.invoices.filter((i) => !i.cerrada);
      const partes = [
        cerradas.length > 0 &&
          `${cerradas.map((i) => i.folio).join(", ")} ${cerradas.length > 1 ? "pasan" : "pasa"} a Pagadas`,
        abonos.length > 0 &&
          abonos
            .map((i) => `${i.folio} sigue abierta, le faltan ${dinero(i.saldo, item.currency)}`)
            .join("; "),
      ].filter(Boolean);
      toast(`Pago confirmado: ${partes.join(". ")}.`, "success");
      cambio();
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setBusy(null);
    }
  }

  async function rechazar(item: { id: string }) {
    setBusy(item.id);
    try {
      await api.ignoreReconcile(item.id);
      toast("Pago rechazado. Queda en Resueltos y no toca ninguna factura.", "info");
      cambio();
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setBusy(null);
    }
  }

  async function confirmarDicho(d: DichoPago) {
    if (!d.respaldo) return;
    setBusy(d.invoice_id);
    try {
      await api.confirmReconcile(d.respaldo.payment_id, [d.invoice_id]);
      toast(`Pago confirmado: ${d.folio} pasa a Pagadas.`, "success");
      cambio();
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <ErrorState message={error} retry={refetch} />;

  const cargando = loading && !data;
  // Sin nada por confirmar, el botón de subir el estado de cuenta ES la pantalla: va
  // relleno en el vacío y no se repite arriba.
  const vacioPendientes = !cargando && vista === "pendientes" && items.length === 0;

  return (
    <div className="min-w-0">
      <RegistrarPagoSheet open={registrar} onClose={() => setRegistrar(false)} onSaved={cambio} />
      <Drawer
        open={subirEstado}
        onClose={() => setSubirEstado(false)}
        title="Subir estado de cuenta"
        subtitle="El PDF que te manda tu banco cada mes"
      >
        <BancoUpload onImported={cambio} />
      </Drawer>

      {!cargando && items.length > 0 && vista === "pendientes" && (
        <div className="reveal mb-10 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="hero-num text-cifra text-ink">{dineroPorMoneda(entrado)}</span>
          <span className="text-cuerpo text-ink-2">
            en {plural(items.length, "pago que espera", "pagos que esperan")} tu confirmación
          </span>
        </div>
      )}

      <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-3">
        <Filtro
          label="Qué pagos ver"
          activo={vista}
          onChange={setVista}
          opciones={[
            { key: "pendientes", label: "Por confirmar", count: items.length },
            { key: "dichos", label: "El cliente dice que pagó", count: dichos.length },
            { key: "resueltos", label: "Resueltos" },
          ]}
        />
        <span className="flex flex-wrap items-center gap-2 md:ml-auto">
          {/* Se exporta lo resuelto: lo pendiente todavía no es un hecho. */}
          {vista === "resueltos" && <ExportButton entidad="conciliacion" />}
          <button onClick={() => setRegistrar(true)} className="btn btn-quiet">
            Registrar un pago
          </button>
          {!vacioPendientes && (
            <SecondaryButton onClick={() => setSubirEstado(true)}>Subir estado de cuenta</SecondaryButton>
          )}
        </span>
      </div>

      {cargando ? (
        <div className="space-y-4">
          <Skeleton className="h-40 w-full rounded-[14px]" />
          <Skeleton className="h-40 w-full rounded-[14px]" />
        </div>
      ) : (
        data && (
          <>
            {vista === "pendientes" &&
              (items.length === 0 ? (
                <EmptyState
                  title="No hay pagos por confirmar"
                  action={
                    <PrimaryButton onClick={() => setSubirEstado(true)}>
                      Subir estado de cuenta
                    </PrimaryButton>
                  }
                >
                  Sube el PDF del estado de cuenta de tu banco. aiuda acomoda cada depósito con
                  la factura que paga y tú confirmas.
                </EmptyState>
              ) : (
                <ListaPendientes
                  items={items}
                  choice={choice}
                  setChoice={setChoice}
                  busy={busy}
                  onConfirm={confirmar}
                  onReject={rechazar}
                />
              ))}
            {vista === "dichos" && (
              <ListaDichos dichos={dichos} busy={busy} onConfirmar={confirmarDicho} />
            )}
            {vista === "resueltos" && (
              <ListaResueltos data={resueltosApi.data?.resueltos ?? []} loading={resueltosApi.loading} />
            )}
            {vista === "pendientes" && items.length > 0 && (
              <Tolerancia config={data.config} onSaved={cambio} />
            )}
          </>
        )
      )}
    </div>
  );
}

// ── Por confirmar: el pago, lo que paga, y por qué ───────────────────────────

function Veredicto({ item, sel, diff }: { item: ReconcileItem; sel: Opcion | null; diff: number }) {
  const [color, texto] = !sel
    ? ["var(--color-ink-3)", item.ambiguo ? "Elige tú cuál es" : "Sin factura que coincida"]
    : sel.cuadra
      ? ["var(--color-ok)", "El monto cuadra"]
      : sel.parcial
        ? ["var(--color-warn)", "Pago parcial"]
        : ["var(--color-warn)", `Hay ${dinero(Math.abs(diff), item.currency)} de diferencia`];
  return (
    <span className="mark" style={{ "--mark": color } as React.CSSProperties}>
      {texto}
    </span>
  );
}

function ListaPendientes({
  items,
  choice,
  setChoice,
  busy,
  onConfirm,
  onReject,
}: {
  items: ReconcileItem[];
  choice: Record<string, string>;
  setChoice: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  busy: string | null;
  onConfirm: (item: ReconcileItem, opcion: Opcion) => void;
  onReject: (item: { id: string }) => void;
}) {
  return (
    <ul className="reveal-stagger space-y-4">
      {items.map((item) => {
        const opts = opcionesDe(item);
        const selKey = choice[item.id] ?? defaultKey(item);
        const sel = opts.find((o) => o.key === selKey) ?? null;
        const diff = sel ? item.amount - sel.monto : 0;
        const elegir = opts.length > (item.ambiguo ? 0 : 1);
        return (
          <li key={item.id} className="rounded-[14px] bg-panel p-5">
            <div className="grid gap-x-10 gap-y-5 sm:grid-cols-2">
              <div className="min-w-0">
                <p className="eyebrow">Entró</p>
                <p className="tnum mt-1.5 text-titulo font-semibold leading-none text-ink">
                  {dinero(item.amount, item.currency)}
                </p>
                <p className="mt-2 text-apoyo text-ink-2">
                  {CONCILIACION_ORIGEN[item.source] ?? item.source}, {fechaDM(item.paid_at)}
                </p>
                {item.counterparty && (
                  <p className="mt-0.5 truncate text-apoyo text-ink-2" title={item.counterparty}>
                    {item.counterparty}
                  </p>
                )}
                {item.origen && <p className="mt-0.5 text-apoyo text-ink-3">{item.origen}</p>}
                {item.reference && (
                  <p className="mt-0.5 truncate text-apoyo text-ink-3" title={item.reference}>
                    Referencia {item.reference}
                  </p>
                )}
              </div>

              <div className="min-w-0">
                <p className="eyebrow">
                  {sel && sel.invoiceIds.length > 1 ? "Paga estas facturas" : "Paga esta factura"}
                </p>
                {sel ? (
                  <>
                    <p className="mt-1.5 text-seccion font-semibold text-ink">{sel.etiqueta}</p>
                    <p className="tnum mt-1 text-apoyo text-ink-2">
                      {dinero(sel.monto, item.currency)}, {sel.detalle}
                    </p>
                  </>
                ) : (
                  <p className="mt-1.5 text-cuerpo text-ink-2">
                    {item.ambiguo
                      ? `Hay ${opts.length} facturas igual de probables.`
                      : "No se encontró una factura abierta que coincida."}
                  </p>
                )}
                <p className="mt-2">
                  <Veredicto item={item} sel={sel} diff={diff} />
                </p>
              </div>
            </div>

            {elegir && (
              <fieldset className="mt-5 border-t border-line-strong/60 pt-4">
                <legend className="sr-only">Facturas posibles</legend>
                <p className="eyebrow">{item.ambiguo ? "Elige la que corresponde" : "Si es otra, cámbiala"}</p>
                <div className="mt-1">
                  {opts.map((o) => (
                    <label key={o.key} className="flex cursor-pointer items-start gap-3 py-2">
                      <input
                        type="radio"
                        name={`opcion-${item.id}`}
                        checked={selKey === o.key}
                        onChange={() => setChoice((c) => ({ ...c, [item.id]: o.key }))}
                        className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-accent)]"
                      />
                      <span className="min-w-0">
                        <span className="block text-cuerpo font-medium text-ink">
                          {o.etiqueta}{" "}
                          <span className="tnum font-normal text-ink-2">
                            {dinero(o.monto, item.currency)}
                            {o.parcial ? ", pago parcial" : ""}
                          </span>
                        </span>
                        <span className="block text-apoyo text-ink-3">{o.reason}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

            <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-3">
              <div className="mr-auto min-w-0 text-apoyo text-ink-2">
                {sel?.reason && !elegir && <p>Por qué: {sel.reason}.</p>}
                {sel?.parcial && (
                  <p>
                    Se aplican {dinero(item.amount, item.currency)} y la factura sigue abierta: le
                    faltarían {dinero(sel.saldoRestante, item.currency)}.
                  </p>
                )}
              </div>
              <button onClick={() => onReject(item)} disabled={busy !== null} className="btn btn-quiet">
                Rechazar
              </button>
              <SecondaryButton
                onClick={() => sel && onConfirm(item, sel)}
                disabled={busy !== null || !sel}
                className="bg-fill-strong"
              >
                {busy === item.id ? "Confirmando…" : sel?.parcial ? "Aplicar pago parcial" : "Confirmar pago"}
              </SecondaryButton>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ── El cliente dice que pagó: se contrasta contra lo que entró al banco ──────

function ListaDichos({
  dichos,
  busy,
  onConfirmar,
}: {
  dichos: DichoPago[];
  busy: string | null;
  onConfirmar: (d: DichoPago) => void;
}) {
  if (dichos.length === 0) {
    return (
      <EmptyState title="Ningún cliente dice que ya pagó">
        Cuando un cliente te escriba que ya pagó, su factura aparece aquí hasta que el depósito
        llegue a tu banco. Que lo diga no la cierra.
      </EmptyState>
    );
  }
  return (
    <ul className="reveal-stagger space-y-4">
      {dichos.map((d) => (
        <li key={d.invoice_id} className="rounded-[14px] bg-panel p-5">
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
            <div className="min-w-0">
              <p className="text-seccion font-semibold text-ink">
                {d.folio} · {d.customer}
              </p>
              <p className="tnum mt-1 text-apoyo text-ink-2">
                {d.saldo < d.amount
                  ? `le faltan ${dinero(d.saldo)} de ${dinero(d.amount)}`
                  : dinero(d.amount)}
                , vence {fechaDM(d.due_date)}
              </p>
              <p
                className="mark mt-3 text-cuerpo"
                style={
                  {
                    "--mark": d.respaldo ? "var(--color-ok)" : "var(--color-ink-3)",
                    whiteSpace: "normal",
                  } as React.CSSProperties
                }
              >
                {d.respaldo
                  ? `Sí entró: ${dinero(d.respaldo.amount)} por ${(CONCILIACION_ORIGEN[d.respaldo.source] ?? d.respaldo.source).toLowerCase()} el ${fechaDM(d.respaldo.paid_at)}`
                  : "Todavía no entra ningún depósito que lo confirme"}
              </p>
            </div>
            {d.respaldo && (
              <SecondaryButton
                onClick={() => onConfirmar(d)}
                disabled={busy !== null}
                className="shrink-0 bg-fill-strong"
              >
                {busy === d.invoice_id ? "Confirmando…" : "Confirmar pago"}
              </SecondaryButton>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

// ── Resueltos: qué se decidió con cada pago ──────────────────────────────────

function ListaResueltos({ data, loading }: { data: ReconcileResuelto[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  }
  if (data.length === 0) {
    return (
      <EmptyState title="Aún no hay pagos resueltos">
        Aquí queda cada pago que confirmes o rechaces: a qué factura se aplicó y cuándo.
      </EmptyState>
    );
  }
  return (
    <ul>
      {data.map((r) => (
        <li key={r.id} className="border-b border-line py-4 last:border-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="tnum text-cuerpo font-semibold text-ink">
              {dinero(r.amount, r.currency)}
              <span className="ml-2 text-apoyo font-normal text-ink-3">
                {CONCILIACION_ORIGEN[r.source] ?? r.source}, {fechaDM(r.paid_at)}
              </span>
            </p>
            <span
              className="mark"
              style={
                { "--mark": r.status === "conciliado" ? "var(--color-ok)" : "var(--color-ink-3)" } as React.CSSProperties
              }
            >
              {r.status === "conciliado" ? "Confirmado" : "Rechazado"}
            </span>
          </div>
          {r.counterparty && <p className="mt-0.5 truncate text-apoyo text-ink-3">{r.counterparty}</p>}
          {r.origen && <p className="mt-0.5 text-apoyo text-ink-3">{r.origen}</p>}
          {r.aplicaciones.length > 0 && (
            <p className="mt-1.5 text-apoyo text-ink-2">
              {r.aplicaciones
                .map((a) =>
                  a.cerrada
                    ? `${a.folio} quedó pagada con ${dinero(a.aplicado, r.currency)}`
                    : `${a.folio} recibió ${dinero(a.aplicado, r.currency)} y le faltan ${dinero(a.saldo, r.currency)}`,
                )
                .join(". ")}
              {r.excedente > 0 ? `. Sobraron ${dinero(r.excedente, r.currency)}` : ""}.
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

// ── Registrar un pago a mano: entra a Por confirmar, no cierra nada solo ─────

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
        // Solo una pista: a qué factura se aplica lo sigue decidiendo el dueño.
        invoice_id: invoiceId || undefined,
      });
      toast("Pago registrado. Ya está en Por confirmar.", "success");
      onSaved();
      onClose();
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Registrar un pago"
      subtitle="Un depósito que no llegó por tu banco conectado: efectivo o transferencia"
    >
      <div className="space-y-4">
        <p className="text-cuerpo text-ink-2">
          El pago entra a Por confirmar. Ahí ves a qué factura se propone aplicarlo y tú
          confirmas; ninguna factura se cierra sola.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-rotulo text-ink-3">Monto</span>
            <input
              className={`${inputCls} mt-1`}
              inputMode="decimal"
              value={monto}
              onChange={(e) => setMonto(e.target.value)}
              placeholder="0.00"
            />
          </label>
          <label className="block">
            <span className="text-rotulo text-ink-3">Fecha</span>
            <input
              className={`${inputCls} mt-1`}
              type="date"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-rotulo text-ink-3">Referencia (opcional)</span>
            <input
              className={`${inputCls} mt-1`}
              value={referencia}
              onChange={(e) => setReferencia(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-rotulo text-ink-3">Quién depositó (opcional)</span>
            <input className={`${inputCls} mt-1`} value={quien} onChange={(e) => setQuien(e.target.value)} />
          </label>
        </div>
        <label className="block">
          <span className="text-rotulo text-ink-3">Factura (opcional)</span>
          <select
            className={`${inputCls} mt-1`}
            value={invoiceId}
            onChange={(e) => setInvoiceId(e.target.value)}
          >
            <option value="">Que la proponga aiuda</option>
            {abiertas.map((inv) => (
              <option key={inv.id} value={inv.id}>
                {inv.folio} · {inv.customer} · {dinero(inv.amount, inv.currency)}
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

// ── Cuánta diferencia entre pago y factura se acepta ─────────────────────────

function Tolerancia({
  config,
  onSaved,
}: {
  config: { tolerancia_pct: number; tolerancia_abs: number };
  onSaved: () => void;
}) {
  const [abierto, setAbierto] = useState(false);
  const [pct, setPct] = useState(String(config.tolerancia_pct));
  const [abs, setAbs] = useState(String(config.tolerancia_abs));
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setPct(String(config.tolerancia_pct));
    setAbs(String(config.tolerancia_abs));
  }, [config.tolerancia_pct, config.tolerancia_abs]);

  const dirty = pct !== String(config.tolerancia_pct) || abs !== String(config.tolerancia_abs);

  async function guardar() {
    const nPct = Number(pct);
    const nAbs = Number(abs);
    if (!Number.isFinite(nPct) || !Number.isFinite(nAbs) || nPct < 0 || nAbs < 0) {
      toast("Escribe un número igual o mayor a cero.", "error");
      return;
    }
    setSaving(true);
    try {
      await api.saveReconcileConfig({ tolerancia_pct: nPct, tolerancia_abs: nAbs });
      toast("Guardado. Las propuestas se volvieron a calcular.", "success");
      onSaved();
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-8">
      <button
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto}
        className="text-apoyo font-medium text-accent-ink hover:underline"
      >
        {abierto ? "Ocultar" : "Cambiar"} la diferencia que se acepta entre un pago y su factura
      </button>
      {abierto && (
        <div className="mt-4 max-w-md space-y-3">
          <p className="text-apoyo text-ink-2">
            Por redondeos o comisiones, un pago puede no ser idéntico a su factura. Hasta esta
            diferencia se toma como el mismo monto; cuenta la mayor de las dos.
          </p>
          <label className="flex items-center justify-between gap-3">
            <span className="text-cuerpo text-ink">Porcentaje</span>
            <span className="flex items-center gap-2">
              <input
                type="number"
                min="0"
                max="100"
                step="0.5"
                value={pct}
                onChange={(e) => setPct(e.target.value)}
                className={`${inputCls} tnum w-24 text-right`}
              />
              <span className="w-3 text-cuerpo text-ink-3">%</span>
            </span>
          </label>
          <label className="flex items-center justify-between gap-3">
            <span className="text-cuerpo text-ink">Cantidad fija</span>
            <span className="flex items-center gap-2">
              <input
                type="number"
                min="0"
                step="1"
                value={abs}
                onChange={(e) => setAbs(e.target.value)}
                className={`${inputCls} tnum w-24 text-right`}
              />
              <span className="w-3 text-cuerpo text-ink-3">$</span>
            </span>
          </label>
          {dirty && (
            <SecondaryButton onClick={guardar} disabled={saving}>
              {saving ? "Guardando…" : "Guardar"}
            </SecondaryButton>
          )}
        </div>
      )}
    </section>
  );
}
