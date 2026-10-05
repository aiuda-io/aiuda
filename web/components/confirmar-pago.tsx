"use client";

import { useState } from "react";
import { api, mxn, type InvoiceDetail } from "@/lib/api";
import { Modal } from "@/components/modal";
import { PrimaryButton, SecondaryButton, SOURCE_LABEL, useApi } from "@/components/ui";

// La ÚNICA puerta para dar una factura por pagada. Antes "Registrar pago" cerraba la
// factura con un clic, sin decir cuánto ni de quién, y si la factura venía de Odoo
// también mandaba el pago de regreso a Odoo sin avisar. Aquí el dueño ve cliente,
// folio y monto, y a dónde más se va a escribir, ANTES de confirmar.
//
// Lee la factura al abrir (no confía en lo que traiga la fila): el monto y el destino
// del pago son los que el server va a usar en ese momento. No hay "Deshacer" porque
// no existe una ruta que revierta un pago; por eso se dice que no se deshace.
export function ConfirmarPago({
  invoiceId,
  onClose,
  onDone,
}: {
  /** null = cerrado. */
  invoiceId: string | null;
  onClose: () => void;
  /** El pago quedó registrado en el server. */
  onDone: (factura: InvoiceDetail) => void;
}) {
  if (!invoiceId) return null;
  // `key`: cada factura abre con su propio estado (sin error ni datos de la anterior).
  return <Confirmacion key={invoiceId} invoiceId={invoiceId} onClose={onClose} onDone={onDone} />;
}

function Confirmacion({
  invoiceId,
  onClose,
  onDone,
}: {
  invoiceId: string;
  onClose: () => void;
  onDone: (factura: InvoiceDetail) => void;
}) {
  const { data, error, loading } = useApi<InvoiceDetail>(
    () => api.invoiceDetail(invoiceId),
    [invoiceId],
  );
  const [guardando, setGuardando] = useState(false);
  const [fallo, setFallo] = useState<string | null>(null);

  const reportado = data?.payment_reported ?? false;
  const regreso = data?.pago_regresa_a ?? null;
  const fuente = regreso ? (SOURCE_LABEL[regreso.fuente] ?? regreso.fuente) : null;
  const yaCerrada = data ? data.status !== "open" : false;

  // Mientras se guarda no se cierra: el pago ya va en camino y hay que ver cómo quedó.
  const cerrar = () => {
    if (!guardando) onClose();
  };

  async function confirmar() {
    if (!data) return;
    setGuardando(true);
    setFallo(null);
    try {
      await api.pay(data.id);
      onDone(data);
    } catch (e) {
      setFallo((e as Error).message);
      setGuardando(false);
    }
  }

  return (
    <Modal
      open
      onClose={cerrar}
      size="sm"
      title={reportado ? "Confirmar pago" : "Registrar pago"}
    >
      {loading && !data ? (
        <div className="space-y-2.5">
          <div className="skeleton h-5 w-2/3 rounded" />
          <div className="skeleton h-9 w-1/2 rounded" />
          <div className="skeleton h-5 w-full rounded" />
        </div>
      ) : error || !data ? (
        <div className="space-y-4">
          <p role="alert" className="text-cuerpo leading-relaxed text-danger">
            No se pudo abrir la factura. No se registró ningún pago.
          </p>
          <div className="flex justify-end">
            <SecondaryButton onClick={cerrar}>Cerrar</SecondaryButton>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="text-cuerpo font-medium text-ink">{data.customer}</p>
            <p className="tnum text-apoyo text-ink-3">Factura {data.folio}</p>
            <p className="tnum mt-2 text-cifra font-semibold leading-none text-ink">
              {mxn(data.amount)}
              <span className="ml-1.5 text-apoyo font-normal text-ink-3">{data.currency}</span>
            </p>
          </div>

          {yaCerrada ? (
            <p className="text-cuerpo leading-relaxed text-ink-2">
              Esta factura ya no está abierta. No hay pago que registrar.
            </p>
          ) : (
            <div className="space-y-1.5 text-cuerpo leading-relaxed text-ink-2">
              {reportado && (
                <p>El cliente dijo que ya pagó. Confirma solo si ya viste el dinero.</p>
              )}
              <p>
                La factura pasa a Pagadas por el monto completo, como confirmada por ti.
              </p>
              {fuente &&
                (regreso!.conectada ? (
                  <p className="font-medium text-ink">También se registrará en {fuente}.</p>
                ) : (
                  <p className="font-medium text-ink">
                    También se registrará en {fuente}, en cuanto vuelvas a conectarlo: ahora no
                    está conectado.
                  </p>
                ))}
              <p className="text-ink-3">Esto no se puede deshacer desde aiuda.</p>
            </div>
          )}

          {fallo && (
            <p role="alert" className="text-cuerpo leading-snug text-danger">
              {fallo}
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            <SecondaryButton onClick={cerrar} disabled={guardando}>
              {yaCerrada ? "Cerrar" : "Cancelar"}
            </SecondaryButton>
            {!yaCerrada && (
              <PrimaryButton onClick={confirmar} disabled={guardando}>
                {guardando ? "Registrando…" : reportado ? "Sí, confirmar pago" : "Sí, registrar pago"}
              </PrimaryButton>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
