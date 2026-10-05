"use client";

import { useState } from "react";
import Link from "next/link";
import { api, errorDeIA, mxn, type PromiseItem } from "@/lib/api";
import { fechaDM } from "@/lib/format";
import { ConfirmarPago } from "@/components/confirmar-pago";
import { Cabeza, Fila, Marca } from "@/components/hoy/piezas";
import { idPromesa, type Ejecutar } from "@/components/hoy/tipos";

/** Una promesa de pago que ya venció con la factura todavía abierta: el cliente
 *  quedó de pagar y no lo hizo, así que toca decidir. */
export function RenglonPromesa({
  p,
  ocupado,
  saliendo,
  ejecutar,
}: {
  p: PromiseItem;
  ocupado: boolean;
  saliendo: boolean;
  ejecutar: Ejecutar;
}) {
  const id = idPromesa(p);
  // La factura cuyo pago se está por registrar: abre la confirmación con monto.
  const [pagoDe, setPagoDe] = useState<string | null>(null);
  const [faltaIA, setFaltaIA] = useState(false);
  const quieto = ocupado || saliendo;
  const dias = -p.days_left;

  async function recordar() {
    setFaltaIA(false);
    await ejecutar(
      () =>
        api.remind(p.invoice_id).catch((e) => {
          // Redactar lo hace la IA del dueño: si no está conectada, además del aviso
          // queda aquí la liga para resolverlo.
          if (errorDeIA(e)) setFaltaIA(true);
          throw e;
        }),
      "Tu ayudante redactó un nuevo recordatorio. Está en esta lista, por aprobar.",
    );
  }

  return (
    <Fila id={id} saliendo={saliendo}>
      <Cabeza nombre={p.customer} clienteId={p.customer_id} monto={mxn(p.amount)}>
        <span className="font-medium text-ink-2">Promesa vencida</span>
        <span className="tnum">Factura {p.folio}</span>
        <Marca color="warn">
          {dias === 1 ? "venció ayer" : `venció hace ${dias} días`}
        </Marca>
      </Cabeza>

      <div className="mt-4 max-w-2xl rounded-[14px] bg-panel px-4 py-3">
        <p className="text-cuerpo leading-relaxed text-ink">
          Quedó de pagar el <span className="font-semibold">{fechaDM(p.promised_date)}</span> y la
          factura sigue abierta.
        </p>
        {p.note && <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">“{p.note}”</p>}
      </div>

      {faltaIA && (
        <p role="alert" className="mt-3 text-cuerpo text-ink-2">
          Falta conectar tu IA para redactar el recordatorio.{" "}
          <Link
            href="/configuracion?seccion=ia"
            className="font-medium text-accent-ink underline-offset-2 hover:underline"
          >
            Tu IA
          </Link>
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setPagoDe(p.invoice_id)}
          disabled={quieto}
          className="btn btn-primary"
        >
          Registrar pago
        </button>
        <button type="button" onClick={recordar} disabled={quieto} className="btn btn-quiet">
          Recordar de nuevo
        </button>
      </div>

      {/* La misma confirmación que en Cartera: cliente, folio, monto y a dónde más se escribe. */}
      <ConfirmarPago
        invoiceId={pagoDe}
        onClose={() => setPagoDe(null)}
        onDone={() => {
          setPagoDe(null);
          // El pago ya quedó en el server: aquí solo se avisa y se refresca la lista.
          ejecutar(() => Promise.resolve(), "Pago registrado. La factura pasa a Pagadas.", id);
        }}
      />
    </Fila>
  );
}
