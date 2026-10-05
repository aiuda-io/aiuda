"use client";

import { useState } from "react";
import { api, type InvoiceDetail, type PagoRegistrado } from "@/lib/api";
import { Modal } from "@/components/modal";
import { PrimaryButton, SecondaryButton, SOURCE_LABEL, useApi } from "@/components/ui";
import { dinero, leerFallo } from "@/lib/cartera";

// La ÚNICA puerta para dar una factura por pagada. El dueño ve cliente, folio y monto,
// y a dónde más se va a escribir, ANTES de confirmar; y al confirmar ve qué pasó y
// cuándo llega a su sistema.
//
// Lee la factura al abrir (no confía en lo que traiga la fila): el monto y el destino
// del pago son los que el server va a usar en ese momento. Cierra la factura por el
// monto completo: no hay pago parcial aquí. Tampoco hay "Deshacer", porque no existe
// una ruta que revierta un pago; por eso se dice que no se deshace.
//
// CUÁNDO llega a Odoo (verificado en core/aiuda_core/engine/writeback.py y en el
// scheduler): registrar el pago solo lo deja anotado para mandarse. Quien lo manda es
// la revisión que aiuda hace una vez por hora de reloj, y solo corre con aiuda
// abierta. No es al instante, y así se dice.
export function ConfirmarPago({
  invoiceId,
  onClose,
  onDone,
}: {
  /** null = cerrado. */
  invoiceId: string | null;
  onClose: () => void;
  /** El pago quedó registrado y el dueño ya leyó cómo quedó. */
  onDone: (factura: InvoiceDetail) => void;
}) {
  if (!invoiceId) return null;
  // `key`: cada factura abre con su propio estado (sin error ni datos de la anterior).
  return <Confirmacion key={invoiceId} invoiceId={invoiceId} onClose={onClose} onDone={onDone} />;
}

/** Cuándo llega el pago al sistema de origen, con palabras del dueño. */
function cuandoLlega(fuente: string, conectada: boolean, yaRegistrado: boolean): string {
  if (!conectada) {
    return `${fuente} no está conectado ahora. El pago queda guardado aquí y se registrará en ${fuente} cuando lo vuelvas a conectar.`;
  }
  return yaRegistrado
    ? `Todavía no está en ${fuente}. aiuda lo manda en su siguiente revisión, que hace cada hora en punto mientras está abierta.`
    : `También se registrará en ${fuente}, pero no al instante: aiuda lo manda en su siguiente revisión, que hace cada hora en punto mientras está abierta.`;
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
  const [hecho, setHecho] = useState<PagoRegistrado | null>(null);

  const reportado = data?.payment_reported ?? false;
  const regreso = data?.pago_regresa_a ?? null;
  const fuente = regreso ? (SOURCE_LABEL[regreso.fuente] ?? regreso.fuente) : null;
  const yaCerrada = data ? data.status !== "open" : false;

  // Mientras se guarda no se cierra: el pago ya va en camino y hay que ver cómo quedó.
  // Ya registrado, cerrar es terminar: quien abrió la ventana refresca su lista.
  const cerrar = () => {
    if (guardando) return;
    if (hecho && data) onDone(data);
    else onClose();
  };

  async function confirmar() {
    if (!data) return;
    setGuardando(true);
    setFallo(null);
    try {
      setHecho(await api.pay(data.id));
    } catch (e) {
      setFallo(leerFallo(e).mensaje);
    } finally {
      setGuardando(false);
    }
  }

  const titulo = hecho ? "Pago registrado" : reportado ? "Confirmar pago" : "Registrar pago";

  return (
    <Modal open onClose={cerrar} size="sm" title={titulo}>
      {loading && !data ? (
        <div className="space-y-2.5">
          <div className="skeleton h-5 w-2/3 rounded" />
          <div className="skeleton h-9 w-1/2 rounded" />
          <div className="skeleton h-5 w-full rounded" />
        </div>
      ) : error || !data ? (
        <div className="space-y-4">
          <p role="alert" className="text-cuerpo text-ink">
            No se pudo abrir la factura. No se registró ningún pago.
          </p>
          <div className="flex justify-end">
            <SecondaryButton onClick={cerrar}>Cerrar</SecondaryButton>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          <div>
            <p className="text-cuerpo font-medium text-ink">{data.customer}</p>
            <p className="tnum text-apoyo text-ink-3">Factura {data.folio}</p>
            <p className="hero-num mt-3 text-cifra leading-none text-ink">
              {dinero(data.amount, data.currency)}
            </p>
          </div>

          {hecho ? (
            <ul className="space-y-2 text-cuerpo text-ink-2">
              <li>La factura pasó a Pagadas, como confirmada por ti.</li>
              {fuente && (
                <li className="font-medium text-ink">{cuandoLlega(fuente, regreso!.conectada, true)}</li>
              )}
              {(hecho.promesas_cumplidas ?? 0) > 0 && (
                <li>
                  {hecho.promesas_cumplidas === 1
                    ? "Su promesa de pago quedó cumplida."
                    : `Sus ${hecho.promesas_cumplidas} promesas de pago quedaron cumplidas.`}
                </li>
              )}
              {(hecho.recordatorios_retirados ?? 0) > 0 && (
                <li>
                  {hecho.recordatorios_retirados === 1
                    ? "Se retiró el recordatorio que estaba por salir: ya no se le cobra."
                    : `Se retiraron los ${hecho.recordatorios_retirados} recordatorios que estaban por salir: ya no se le cobra.`}
                </li>
              )}
            </ul>
          ) : yaCerrada ? (
            <p className="text-cuerpo text-ink-2">
              Esta factura ya no está abierta. No hay pago que registrar.
            </p>
          ) : (
            <div className="space-y-2 text-cuerpo text-ink-2">
              {reportado && <p>El cliente dijo que ya pagó. Confirma solo si ya viste el dinero.</p>}
              <p>La factura pasa a Pagadas por el monto completo, como confirmada por ti.</p>
              {fuente && (
                <p className="font-medium text-ink">{cuandoLlega(fuente, regreso!.conectada, false)}</p>
              )}
              <p className="text-ink-3">Esto no se puede deshacer desde aiuda.</p>
            </div>
          )}

          {fallo && (
            <p role="alert" className="flex items-start gap-2 text-cuerpo text-ink">
              <span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-danger" />
              <span>{fallo} No se registró ningún pago.</span>
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            {hecho ? (
              <PrimaryButton onClick={cerrar}>Listo</PrimaryButton>
            ) : (
              <>
                <SecondaryButton onClick={cerrar} disabled={guardando}>
                  {yaCerrada ? "Cerrar" : "Cancelar"}
                </SecondaryButton>
                {!yaCerrada && (
                  <PrimaryButton onClick={confirmar} disabled={guardando}>
                    {guardando ? "Registrando…" : reportado ? "Sí, confirmar pago" : "Sí, registrar pago"}
                  </PrimaryButton>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
