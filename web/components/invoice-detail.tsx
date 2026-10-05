"use client";

// El panel de una factura. Aquí viven TODAS sus acciones (redactar el recordatorio,
// registrar el pago, marcar una promesa como cumplida): las listas de Cartera solo
// abren este panel. Se pinta igual en el panel lateral (apilado) y en su página propia
// (`rail`, a dos columnas).

import { useState } from "react";
import Link from "next/link";
import { api, apiUrl, TONE_LABEL, type InvoiceDetail, type Cfdi } from "@/lib/api";
import { fecha, fechaDM, telefonoMx } from "@/lib/format";
import { toast } from "@/components/toast";
import { SOURCE_LABEL, SOURCE_LOGO } from "@/components/ui";
import { WritebackStatus } from "@/components/writeback-status";
import { InyectarButton } from "@/components/inyectar-button";
import { ConfirmarPago } from "@/components/confirmar-pago";
import { FalloAccion } from "@/components/cartera-partes";
import { oficioDe } from "@/lib/oficios";
import { atraso, dinero, leerFallo, RUTA, TRAMO_MARCA, type Fallo } from "@/lib/cartera";

const ESTADO_RECORDATORIO: Record<string, string> = {
  draft: "en borrador",
  pending_approval: "espera tu aprobación",
  approved: "aprobado, por salir",
  sent: "enviado",
  rejected: "rechazado",
  failed: "no salió",
};

type Recordatorio = InvoiceDetail["reminders"][number] & {
  /** Por qué aiuda lo sacó de lo pendiente (la factura se pagó o se canceló). */
  retirado?: string | null;
};

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-rotulo text-ink-3">{label}</dt>
      <dd className="mt-0.5 text-cuerpo text-ink">{children}</dd>
    </div>
  );
}

function Seccion({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line pt-5">
      <h3 className="text-cuerpo font-semibold text-ink">{titulo}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function EstadoGrande({ data }: { data: InvoiceDetail }) {
  const [color, texto] =
    data.status === "paid"
      ? ["var(--color-ok)", `Pagada${data.paid_at ? ` el ${fechaDM(data.paid_at)}` : ""}`]
      : data.status === "cancelled"
        ? [
            "var(--color-ink-3)",
            data.motivo_cierre === "cancelada en el SAT" ? "Cancelada en el SAT" : "Cancelada",
          ]
        : data.payment_reported
          ? ["var(--color-warn)", "El cliente dice que ya pagó"]
          : data.bucket === "cotizacion"
            ? ["var(--color-ink-3)", "Cotización"]
            : [TRAMO_MARCA[data.bucket] ?? "var(--color-ink-3)", atraso(data.days_overdue)];
  return (
    <span className="mark tnum text-cuerpo" style={{ "--mark": color } as React.CSSProperties}>
      {texto}
    </span>
  );
}

export function InvoiceDetailContent({
  data,
  onChanged,
  rail = false,
}: {
  data: InvoiceDetail;
  onChanged?: () => void;
  /** En la página, reparte el contenido en dos columnas (principal + contexto). En el
   *  panel lateral, que es angosto, va apilado. */
  rail?: boolean;
}) {
  const presence = Object.entries(data.presence ?? {});
  const cfdi: Cfdi | null = data.cfdi && (data.cfdi as Cfdi).uuid ? (data.cfdi as Cfdi) : null;
  // ¿El total del comprobante cuadra con lo que aiuda tiene por cobrar?
  const cfdiCuadra = cfdi?.total != null ? Math.abs(cfdi.total - data.amount) < 0.01 : null;
  const monedaCfdi = cfdi?.moneda ?? data.currency;
  const [redactando, setRedactando] = useState(false);
  const [confirmarPago, setConfirmarPago] = useState(false);
  // Lo que salió mal al pedir el recordatorio se queda junto al botón (no en un aviso
  // que se va solo): si lo que falta es la IA, trae la liga para conectarla.
  const [fallo, setFallo] = useState<Fallo | null>(null);
  const [cumpliendo, setCumpliendo] = useState<string | null>(null);
  // Al mandar la factura a otro sistema hay que recargar "Lo que aiuda escribió".
  const [inyKey, setInyKey] = useState(0);
  const recordatorios = data.reminders as Recordatorio[];
  // Si ya hay un recordatorio en curso no se redacta otro: se lleva a verlo.
  const enCurso = recordatorios.find((r) => ["draft", "pending_approval", "approved"].includes(r.status));
  const abierta = data.status === "open";

  async function redactar() {
    setRedactando(true);
    setFallo(null);
    try {
      const r = await api.remind(data.id);
      toast(
        r.status === "pending_approval"
          ? "Recordatorio redactado. Te espera en Hoy, en Por aprobar."
          : "Recordatorio redactado.",
        "success",
      );
      onChanged?.();
    } catch (e) {
      setFallo(leerFallo(e));
    } finally {
      setRedactando(false);
    }
  }

  async function cumplir(promesaId: string) {
    setCumpliendo(promesaId);
    try {
      await api.fulfill(promesaId);
      toast("Promesa marcada como cumplida.", "success");
      onChanged?.();
    } catch (e) {
      toast(leerFallo(e).mensaje, "error");
    } finally {
      setCumpliendo(null);
    }
  }

  const montoEstado = (
    <div>
      <p className="hero-num text-cifra leading-none text-ink">{dinero(data.amount, data.currency)}</p>
      <p className="mt-3">
        <EstadoGrande data={data} />
      </p>
    </div>
  );

  const acciones =
    data.status === "cancelled" ? (
      <p className="text-cuerpo text-ink-2">
        Esta factura ya no se cobra{data.motivo_cierre ? `: ${data.motivo_cierre}` : ""}. Salió de
        tu cartera y no se le mandan recordatorios.
      </p>
    ) : (
      abierta && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {enCurso ? (
              <Link href={`${RUTA.hoy}?r=${enCurso.id}`} className="btn btn-primary">
                Ver recordatorio
              </Link>
            ) : (
              <button onClick={redactar} disabled={redactando} className="btn btn-primary">
                {redactando ? "Redactando…" : "Redactar recordatorio"}
              </button>
            )}
            <button
              onClick={() => setConfirmarPago(true)}
              disabled={redactando}
              className="btn btn-secondary"
            >
              {data.payment_reported ? "Confirmar pago" : "Registrar pago"}
            </button>
            {/* Mandar la factura a otro sistema; solo sale si hay a dónde y aún no vive allá. */}
            <InyectarButton
              entidad="factura"
              id={data.id}
              presence={data.presence}
              onQueued={() => {
                setInyKey((n) => n + 1);
                onChanged?.();
              }}
            />
          </div>
          {fallo && <FalloAccion fallo={fallo} />}
          <ConfirmarPago
            invoiceId={confirmarPago ? data.id : null}
            onClose={() => setConfirmarPago(false)}
            onDone={() => {
              setConfirmarPago(false);
              onChanged?.();
            }}
          />
        </div>
      )
    );

  const campos = (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-4 border-t border-line pt-5">
      <Campo label="Cliente">{data.customer}</Campo>
      <Campo label="WhatsApp">
        {data.customer_phone ? (
          <span className="tnum">{telefonoMx(data.customer_phone)}</span>
        ) : (
          <span className="text-ink-3">Sin teléfono</span>
        )}
      </Campo>
      <Campo label="Emitida">{fecha(data.issued_date)}</Campo>
      <Campo label="Vence">{fecha(data.due_date)}</Campo>
      {data.verified === "verificada" && <Campo label="Pago">Confirmado con tu banco</Campo>}
    </dl>
  );

  const actividad = (recordatorios.length > 0 || data.promises.length > 0) && (
    <Seccion titulo="Lo que ha pasado">
      <ul className="space-y-4">
        {data.promises.map((p) => (
          <li key={p.id}>
            <p className="text-cuerpo text-ink">
              Prometió pagar el {fecha(p.promised_date)}
              {p.fulfilled && <span className="text-ink-2">, cumplida</span>}
            </p>
            {p.note && <p className="text-apoyo text-ink-3">&ldquo;{p.note}&rdquo;</p>}
            {!p.fulfilled && abierta && (
              <button
                onClick={() => cumplir(p.id)}
                disabled={cumpliendo !== null}
                title="Solo marca la promesa. Para cerrar la factura, registra el pago."
                className="btn btn-sm btn-secondary mt-2"
              >
                {cumpliendo === p.id ? "Marcando…" : "Marcar cumplida"}
              </button>
            )}
          </li>
        ))}
        {recordatorios.map((r) => (
          <li key={r.id}>
            <Link href={`${RUTA.hoy}?r=${r.id}`} className="group block min-w-0">
              <p className="text-cuerpo text-ink group-hover:text-accent-ink">
                {/* El ayudante que el dueño creó, no el nombre interno. */}
                {r.propuesto_por || oficioDe(r.agent)} redactó un recordatorio
              </p>
              <p className="text-apoyo text-ink-3">
                {r.retirado
                  ? `Retirado: ${r.retirado}`
                  : `Tono ${TONE_LABEL[r.tone] ?? r.tone}, ${ESTADO_RECORDATORIO[r.status] ?? r.status}`}
                {r.sent_at ? ` el ${fecha(r.sent_at)}` : ""}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </Seccion>
  );

  const cfdiSection = cfdi && (
    <Seccion titulo={`Comprobante fiscal${cfdi.version ? ` (CFDI ${cfdi.version})` : ""}`}>
      {cfdiCuadra !== null && (
        <p
          className="mark mb-4"
          style={{ "--mark": cfdiCuadra ? "var(--color-ok)" : "var(--color-warn)" } as React.CSSProperties}
        >
          {cfdiCuadra ? "Su total cuadra con lo que debe" : "Su total no cuadra con lo que debe"}
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
        <div className="col-span-2 min-w-0">
          <dt className="text-rotulo text-ink-3">Folio fiscal</dt>
          <dd className="tnum mt-0.5 break-all text-apoyo text-ink">{cfdi.uuid}</dd>
        </div>
        <Campo label="Emisor">
          {cfdi.emisor?.nombre ?? "·"}
          {cfdi.emisor?.rfc && <span className="tnum block text-apoyo text-ink-3">{cfdi.emisor.rfc}</span>}
        </Campo>
        <Campo label="Receptor">
          {cfdi.receptor?.nombre ?? "·"}
          {cfdi.receptor?.rfc && (
            <span className="tnum block text-apoyo text-ink-3">{cfdi.receptor.rfc}</span>
          )}
        </Campo>
        <Campo label="Subtotal">{cfdi.subtotal != null ? dinero(cfdi.subtotal, monedaCfdi) : "·"}</Campo>
        <Campo label="IVA">{cfdi.iva ? dinero(cfdi.iva, monedaCfdi) : "·"}</Campo>
        <Campo label="Total">
          <span className="font-medium">{cfdi.total != null ? dinero(cfdi.total, monedaCfdi) : "·"}</span>
        </Campo>
        <Campo label="Timbrado">{fecha(cfdi.fecha_timbrado)}</Campo>
      </dl>
      {(data.has_xml || data.has_pdf) && (
        <div className="mt-4 flex gap-2">
          {data.has_xml && (
            <a
              href={apiUrl(`/v1/invoices/${data.id}/cfdi.xml`)}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-sm btn-secondary"
            >
              Ver XML
            </a>
          )}
          {data.has_pdf && (
            <a
              href={apiUrl(`/v1/invoices/${data.id}/cfdi.pdf`)}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-sm btn-secondary"
            >
              Ver PDF
            </a>
          )}
        </div>
      )}
    </Seccion>
  );

  const presencia = (
    <Seccion titulo="De dónde viene">
      {presence.length === 0 ? (
        <p className="text-cuerpo text-ink-2">{SOURCE_LABEL[data.source] ?? data.source}</p>
      ) : (
        <ul className="-my-1">
          {presence.map(([sys, info]) => {
            const nombre = SOURCE_LABEL[sys] ?? sys;
            const detalle = [info.file, info.at ? `subido el ${fechaDM(info.at)}` : "", info.ref]
              .filter(Boolean)
              .join(", ");
            const cuerpo = (
              <>
                {SOURCE_LOGO[sys] && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={SOURCE_LOGO[sys]} alt="" className="h-4 w-4 shrink-0" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block text-cuerpo text-ink">{nombre}</span>
                  {detalle && <span className="block truncate text-apoyo text-ink-3">{detalle}</span>}
                </span>
                {info.url && <span className="shrink-0 text-apoyo font-medium text-accent-ink">Abrir</span>}
              </>
            );
            return (
              <li key={sys}>
                {info.url ? (
                  <a
                    href={info.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-3 py-2 hover:opacity-75"
                  >
                    {cuerpo}
                  </a>
                ) : (
                  <span className="flex items-center gap-3 py-2">{cuerpo}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Seccion>
  );

  // Si el pago confirmado ya quedó escrito en el sistema de origen. Se recarga cuando la
  // factura cambia (al pagar) o al mandarla a otro sistema desde esta ficha.
  const writeback = (
    <WritebackStatus
      invoiceId={data.id}
      refreshKey={`${data.status}-${data.paid_at ?? ""}-${inyKey}`}
    />
  );

  const atajos = (
    <div className="flex flex-wrap gap-2 border-t border-line pt-5">
      <Link href={`/clientes/detalle?id=${data.customer_id}`} className="btn btn-sm btn-secondary">
        Ver cliente
      </Link>
      {data.conversation_id && (
        <Link href={`/conversaciones?id=${data.conversation_id}`} className="btn btn-sm btn-secondary">
          Ver mensajes
        </Link>
      )}
    </div>
  );

  // En la página: dos columnas que se apilan en pantallas angostas (nada se esconde).
  // En el panel lateral: apilado, lo que se decide primero.
  if (rail) {
    return (
      <div className="grid gap-x-14 gap-y-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 max-w-2xl space-y-6">
          {montoEstado}
          {acciones}
          {campos}
          {actividad}
          {cfdiSection}
          {atajos}
        </div>
        <aside className="min-w-0 space-y-6 lg:[&>section:first-child]:border-t-0 lg:[&>section:first-child]:pt-0">
          {presencia}
          {writeback}
        </aside>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {montoEstado}
      {acciones}
      {campos}
      {actividad}
      {cfdiSection}
      {presencia}
      {writeback}
      {atajos}
    </div>
  );
}
