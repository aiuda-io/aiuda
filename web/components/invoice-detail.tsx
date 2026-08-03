"use client";

import { useState } from "react";
import Link from "next/link";
import { api, BUCKET_META, mxn, TONE_LABEL, type InvoiceDetail, type Cfdi } from "@/lib/api";
import { fecha, fechaDM } from "@/lib/format";
import { toast } from "@/components/toast";
import { SOURCE_LABEL, SOURCE_LOGO } from "@/components/ui";
import { RailLayout } from "@/components/rail";
import { WritebackStatus } from "@/components/writeback-status";
import { InyectarButton } from "@/components/inyectar-button";
import { agentDisplayName } from "@/lib/asistentes";
const STATUS_LABEL: Record<string, string> = {
  draft: "Borrador",
  pending_approval: "Por aprobar",
  approved: "Aprobado",
  sent: "Enviado",
  rejected: "Rechazado",
  failed: "Falló",
};

const fmtDate = (iso: string | null) => fecha(iso);
const fmtShort = (iso?: string) => (iso ? fechaDM(iso) : "");

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-rotulo uppercase tracking-[0.06em] text-ink-3">{label}</p>
      <p className="mt-0.5 text-cuerpo text-ink">{value}</p>
    </div>
  );
}

export function InvoiceDetailContent({
  data,
  onChanged,
  rail = false,
}: {
  data: InvoiceDetail;
  onChanged?: () => void;
  /** En la página, reparte el contenido en dos columnas (principal + riel de contexto) para
   *  no dejar todo pegado a un lado. En el drawer (angosto) va apilado. Mismo patrón que el
   *  detalle de cliente, para que ambas fichas se lean igual. */
  rail?: boolean;
}) {
  const presence = Object.entries(data.presence ?? {});
  const cfdi: Cfdi | null = data.cfdi && (data.cfdi as Cfdi).uuid ? (data.cfdi as Cfdi) : null;
  // ¿El total del CFDI cuadra con lo que aiuda tiene de saldo? (la verdad fiscal)
  const cfdiCuadra = cfdi?.total != null ? Math.abs(cfdi.total - data.amount) < 0.01 : null;
  const [busy, setBusy] = useState<"pay" | "remind" | null>(null);
  // Tras encolar una inyección, recargar el "Regreso a la fuente" (su refreshKey
  // no cambia solo: el estado de la factura sigue igual, lo nuevo es el outbox).
  const [inyKey, setInyKey] = useState(0);
  // Si ya hay un recordatorio en curso, no bloqueamos: llevamos al usuario a él.
  const activeReminder = data.reminders.find((r) =>
    ["draft", "pending_approval", "approved"].includes(r.status),
  );

  function inyeccionEncolada() {
    setInyKey((n) => n + 1);
    onChanged?.();
  }

  async function recordar() {
    setBusy("remind");
    try {
      await api.remind(data.id);
      toast("Borrador listo en Aprobaciones.", "success");
      onChanged?.();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function registrarPago() {
    setBusy("pay");
    try {
      await api.pay(data.id);
      toast("Pago confirmado. La factura pasa a Pagadas.", "success");
      onChanged?.();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  const montoEstado = (
    /* Monto + estado */
    <div className="flex items-end justify-between">
      <div>
        <p className="tnum text-cifra font-semibold leading-none text-ink">{mxn(data.amount)}</p>
        <p className="mt-1 text-cuerpo text-ink-3">{data.currency}</p>
      </div>
      {data.status === "paid" ? (
        <span className="rounded-full bg-ok-soft px-2.5 py-1 text-sello font-medium text-ok">Pagada</span>
      ) : data.payment_reported ? (
        <span className="rounded-full bg-warn-soft px-2.5 py-1 text-rotulo font-medium text-warn">
          Cliente reporta pago
        </span>
      ) : (
        <span className="rounded-full bg-panel px-2.5 py-1 text-sello font-medium text-ink-2">
          {BUCKET_META[data.bucket]?.label ??
            (data.bucket === "cotizacion" ? "Cotización" : "Abierta")}
        </span>
      )}
    </div>
  );

  const acciones = data.status !== "paid" && (
    /* Acciones del registro: las mismas que en la lista, donde vive el registro.
       Si ya hay un recordatorio, en vez de bloquear, lleva a verlo. */
    <div className="flex flex-wrap gap-2">
      {activeReminder ? (
        <Link
          href={`/centro?r=${activeReminder.id}`}
          className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong"
        >
          Ver recordatorio
        </Link>
      ) : (
        <button
          onClick={recordar}
          disabled={busy !== null}
          className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
        >
          {busy === "remind" ? "Redactando…" : "Recordar"}
        </button>
      )}
      <button
        onClick={registrarPago}
        disabled={busy !== null}
        className="rounded-md border border-line bg-surface px-3.5 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
      >
        {busy === "pay" ? "Registrando…" : "Registrar pago"}
      </button>
      {/* Empujar la factura al maestro elegido; solo si hay destinos y no vive ya allá. */}
      <InyectarButton
        entidad="factura"
        id={data.id}
        presence={data.presence}
        onQueued={inyeccionEncolada}
      />
    </div>
  );

  const campos = (
    /* Campos */
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-y border-line/70 py-4">
      <Field label="Cliente" value={data.customer} />
      <Field label="WhatsApp" value={<span className="tnum">{data.customer_phone}</span>} />
      <Field label="Emitida" value={fmtDate(data.issued_date)} />
      <Field label="Vence" value={fmtDate(data.due_date)} />
      <Field
        label="Atraso"
        value={
          data.status === "paid" ? (
            "Pagada"
          ) : data.days_overdue > 0 ? (
            <span className="font-medium text-danger">{data.days_overdue} días</span>
          ) : (
            <span className="text-ink-2">vence en {-data.days_overdue} días</span>
          )
        }
      />
      <Field
        label="Verificación"
        value={
          data.verified === "verificada" ? (
            <span className="text-ok">Verificada</span>
          ) : (
            <span className="text-ink-3">Sin verificar</span>
          )
        }
      />
    </div>
  );

  const cfdiSection = cfdi && (
        <section className="rounded-lg border border-line bg-panel/40 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-cuerpo font-semibold text-ink">
              Comprobante fiscal{cfdi.version ? ` · CFDI ${cfdi.version}` : ""}
            </h3>
            {cfdiCuadra !== null &&
              (cfdiCuadra ? (
                <span className="rounded-full bg-ok-soft px-2 py-0.5 text-rotulo font-medium text-ok">
                  Cuadra con el saldo
                </span>
              ) : (
                <span className="rounded-full bg-warn-soft px-2 py-0.5 text-rotulo font-medium text-warn">
                  No cuadra con el saldo
                </span>
              ))}
          </div>
          <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2.5">
            <div className="col-span-2">
              <p className="text-rotulo uppercase tracking-[0.06em] text-ink-3">Folio fiscal (UUID)</p>
              <p className="tnum mt-0.5 break-all text-cuerpo text-ink">{cfdi.uuid}</p>
            </div>
            <Field
              label="Emisor"
              value={
                <>
                  {cfdi.emisor?.nombre ?? "·"}
                  {cfdi.emisor?.rfc && (
                    <span className="tnum block text-apoyo text-ink-3">{cfdi.emisor.rfc}</span>
                  )}
                </>
              }
            />
            <Field
              label="Receptor"
              value={
                <>
                  {cfdi.receptor?.nombre ?? "·"}
                  {cfdi.receptor?.rfc && (
                    <span className="tnum block text-apoyo text-ink-3">{cfdi.receptor.rfc}</span>
                  )}
                </>
              }
            />
            <Field label="Subtotal" value={cfdi.subtotal != null ? mxn(cfdi.subtotal) : "·"} />
            <Field label="IVA" value={cfdi.iva ? mxn(cfdi.iva) : "·"} />
            <Field
              label="Total"
              value={<span className="font-medium">{cfdi.total != null ? mxn(cfdi.total) : "·"}</span>}
            />
            <Field label="Timbrado" value={fmtDate(cfdi.fecha_timbrado)} />
          </dl>
          {(data.has_xml || data.has_pdf) && (
            <div className="mt-3 flex gap-2">
              {data.has_xml && (
                <a
                  href={`/api/v1/invoices/${data.id}/cfdi.xml`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
                >
                  Ver XML
                </a>
              )}
              {data.has_pdf && (
                <a
                  href={`/api/v1/invoices/${data.id}/cfdi.pdf`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
                >
                  Ver PDF
                </a>
              )}
            </div>
          )}
        </section>
  );

  const presencia = (
      /* Presencia multi-sistema */
      <section>
        <h3 className="text-cuerpo font-semibold text-ink">Dónde vive este registro</h3>
        <p className="mt-0.5 text-apoyo text-ink-3">
          El mismo registro puede existir en varios sistemas. Salta a cualquiera.
        </p>
        <ul className="mt-2.5 space-y-1.5">
          {presence.length === 0 && (
            <li className="text-cuerpo text-ink-3">Origen: {SOURCE_LABEL[data.source] ?? data.source}</li>
          )}
          {presence.map(([sys, info]) => (
            <li key={sys}>
              <a
                href={info.url ?? "/integraciones"}
                target={info.url ? "_blank" : undefined}
                rel={info.url ? "noopener noreferrer" : undefined}
                className="group flex items-center gap-2.5 rounded-md border border-line bg-surface px-3 py-2 transition-colors hover:border-line-strong"
              >
                {SOURCE_LOGO[sys] ? (
                  <img src={SOURCE_LOGO[sys]} alt="" className="h-4 w-4" />
                ) : (
                  <span className="flex h-4 w-4 items-center justify-center rounded bg-panel text-sello font-bold text-ink-2">
                    {(SOURCE_LABEL[sys] ?? sys).slice(0, 2)}
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block text-cuerpo font-medium text-ink">{SOURCE_LABEL[sys] ?? sys}</span>
                  {(info.file || info.at) && (
                    <span className="block truncate text-apoyo text-ink-3">
                      {info.file}
                      {info.file && info.at ? " · " : ""}
                      {info.at ? `subido ${fmtShort(info.at)}` : ""}
                    </span>
                  )}
                </span>
                {info.ref && <span className="tnum text-apoyo text-ink-3">{info.ref}</span>}
                {info.url && (
                  <svg viewBox="0 0 12 12" className="h-3 w-3 text-ink-3 transition-transform group-hover:translate-x-0.5" fill="none">
                    <path d="M4 2h6v6M10 2 3 9" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </a>
            </li>
          ))}
        </ul>
      </section>
  );

  // Write-back: si el pago confirmado ya quedó escrito en la fuente. El refreshKey recarga
  // cuando la factura cambia (p.ej. al pagar) o al encolar una inyección desde esta ficha.
  const writeback = (
    <WritebackStatus
      invoiceId={data.id}
      refreshKey={`${data.status}-${data.paid_at ?? ""}-${inyKey}`}
    />
  );

  const actividad = (data.reminders.length > 0 || data.promises.length > 0) && (
        /* Actividad del equipo */
        <section>
          <h3 className="text-cuerpo font-semibold text-ink">Actividad del equipo</h3>
          <ul className="mt-2.5 space-y-2.5">
            {data.promises.map((p) => (
              <li key={p.id} className="flex gap-2.5">
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-accent" />
                <div>
                  <p className="text-cuerpo text-ink">
                    Promesa de pago para el {fmtDate(p.promised_date)}
                    {p.fulfilled && <span className="text-ok"> · cumplida</span>}
                  </p>
                  {p.note && <p className="text-apoyo text-ink-3">“{p.note}”</p>}
                </div>
              </li>
            ))}
            {data.reminders.map((r) => (
              <li key={r.id} className="flex gap-2.5">
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-ink-3" />
                <Link href={`/centro?r=${r.id}`} className="group min-w-0">
                  <p className="text-cuerpo text-ink group-hover:text-accent-ink">
                    {/* El ayudante que el dueño creó, no el slug del runtime. */}
                    {r.propuesto_por || agentDisplayName(r.agent)} redactó un recordatorio
                    <span className="text-ink-3"> · {STATUS_LABEL[r.status] ?? r.status}</span>
                  </p>
                  <p className="text-apoyo text-ink-3">
                    Tono {TONE_LABEL[r.tone] ?? r.tone}
                    {r.sent_at ? ` · enviado ${fmtDate(r.sent_at)}` : ""}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
  );

  const atajos = (
    /* Atajos */
    <div className="flex flex-wrap gap-2 border-t border-line/70 pt-4">
      {data.conversation_id && (
        <Link
          href={`/conversaciones?id=${data.conversation_id}`}
          className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
        >
          Ver conversación
        </Link>
      )}
      <Link
        href={`/clientes/detalle?id=${data.customer_id}`}
        className="rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
      >
        Ver cliente
      </Link>
    </div>
  );

  const principal = (
    <>
      {montoEstado}
      {acciones}
      {campos}
      {cfdiSection}
    </>
  );

  // En la página: dos columnas (principal + riel de contexto), como el detalle de cliente,
  // para que no quede todo pegado a un lado. En el drawer angosto: apilado, como siempre.
  if (rail) {
    return (
      <RailLayout
        rail={
          <>
            {presencia}
            {writeback}
            {actividad}
          </>
        }
      >
        <div className="space-y-5 rounded-xl border border-line bg-surface p-5">
          {principal}
          {atajos}
        </div>
      </RailLayout>
    );
  }

  return (
    <div className="space-y-5">
      {principal}
      {presencia}
      {writeback}
      {actividad}
      {atajos}
    </div>
  );
}
