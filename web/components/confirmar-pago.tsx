"use client";

import { useEffect, useState } from "react";
import { api, type InvoiceDetail, type PagoRegistrado } from "@/lib/api";
import { Modal } from "@/components/modal";
import { PrimaryButton, QuietButton, SecondaryButton, SOURCE_LABEL, useApi } from "@/components/ui";
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
// CUÁNDO llega a Odoo: al registrar el pago el servidor lo manda en ese momento, en
// segundo plano (no detiene la respuesta). Aquí NO se da por hecho: se le pregunta a
// la cola (/v1/writeback) y se dice lo que pasó de verdad. Si llegó, "ya quedó en
// Odoo". Si Odoo no respondió, queda en la cola y lo reintenta la revisión que aiuda
// hace cada hora en punto mientras está abierta.
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

/** En qué va el pago rumbo a su sistema de origen. */
type Llegada = "enviando" | "llego" | "pendiente";

/** Cuántas veces y cada cuánto se le pregunta a la cola si el pago ya llegó. */
const PREGUNTAS = 8;
const CADA_MS = 1200;

/** Qué pasa con el pago en el sistema de origen, con palabras del dueño y sin
 *  prometer de más: antes de registrar, y después según lo que de verdad pasó. */
function cuandoLlega(fuente: string, conectada: boolean, llegada: Llegada | null): string {
  if (!conectada) {
    return `${fuente} no está conectado ahora. El pago queda guardado aquí y se registrará en ${fuente} cuando lo vuelvas a conectar.`;
  }
  if (llegada === null) {
    return `También se registra en ${fuente} en cuanto lo confirmes. Si ${fuente} no responde, aiuda lo reintenta en su siguiente revisión, que hace cada hora en punto mientras está abierta.`;
  }
  if (llegada === "enviando") return `Mandándolo a ${fuente}…`;
  if (llegada === "llego") return `Ya quedó registrado en ${fuente}.`;
  return `Todavía no está en ${fuente}: no respondió. aiuda lo reintenta en su siguiente revisión, que hace cada hora en punto mientras está abierta. En la ficha de la factura puedes ver en qué va.`;
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
  const [llegada, setLlegada] = useState<Llegada>("enviando");

  // Registrado el pago, se le pregunta a la cola si ya llegó a su sistema. No se
  // supone: "llegó" solo si la entrada quedó registrada allá. Si tras unos segundos
  // sigue en espera (o ya falló un intento), se dice que queda para la revisión.
  const writebackId = hecho?.writeback_id ?? null;
  useEffect(() => {
    if (!writebackId) return;
    let vivo = true;
    let preguntas = 0;
    let reloj: ReturnType<typeof setTimeout>;
    const preguntar = async () => {
      preguntas += 1;
      try {
        const { entries } = await api.writeback({ invoice_id: invoiceId });
        const entrada = entries.find((e) => e.id === writebackId);
        if (!vivo) return;
        if (entrada?.estado === "inyectada") return setLlegada("llego");
        // Un intento que YA falló deja escrito su error. `attempts` solo no sirve:
        // el servidor lo sube antes de hablar con el sistema, así que un pago que va
        // en camino también lo trae en 1, y se decía "no respondió" de uno que
        // llegaba un segundo después.
        if (entrada && (entrada.estado !== "pendiente" || entrada.last_error)) {
          return setLlegada("pendiente");
        }
      } catch {
        // Sin respuesta de la cola no se afirma nada: se sigue preguntando.
      }
      if (!vivo) return;
      if (preguntas >= PREGUNTAS) setLlegada("pendiente");
      else reloj = setTimeout(preguntar, CADA_MS);
    };
    reloj = setTimeout(preguntar, 600);
    return () => {
      vivo = false;
      clearTimeout(reloj);
    };
  }, [writebackId, invoiceId]);

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
                <li className="font-medium text-ink" aria-live="polite">
                  {cuandoLlega(fuente, regreso!.conectada, writebackId ? llegada : "pendiente")}
                </li>
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
                <p className="font-medium text-ink">{cuandoLlega(fuente, regreso!.conectada, null)}</p>
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
                <QuietButton onClick={cerrar} disabled={guardando}>
                  {yaCerrada ? "Cerrar" : "Cancelar"}
                </QuietButton>
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
