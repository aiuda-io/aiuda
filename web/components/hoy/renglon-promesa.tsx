"use client";

import { useState } from "react";
import Link from "next/link";
import { api, errorDeIA, type PromiseItem } from "@/lib/api";
import { dinero } from "@/lib/cartera";
import { fechaDM } from "@/lib/format";
import { ConfirmarPago } from "@/components/confirmar-pago";
import { Cabeza, Fila, Marca } from "@/components/hoy/piezas";
import { QuietButton, useConfirm } from "@/components/ui";
import { idPromesa, type Ejecutar } from "@/components/hoy/tipos";

/** Una promesa de pago que ya venció con la factura todavía abierta: el cliente
 *  quedó de pagar y no lo hizo, así que toca decidir. */
export function RenglonPromesa({
  p,
  ocupado,
  saliendo,
  ejecutar,
  principal,
}: {
  p: PromiseItem;
  ocupado: boolean;
  saliendo: boolean;
  ejecutar: Ejecutar;
  /** El renglón que lleva el ÚNICO botón relleno de la pantalla (el primero de la
   *  lista). En los demás, la misma acción va con contorno. */
  principal?: boolean;
}) {
  const id = idPromesa(p);
  // La factura cuyo pago se está por registrar: abre la confirmación con monto.
  const [pagoDe, setPagoDe] = useState<string | null>(null);
  const [faltaIA, setFaltaIA] = useState(false);
  const { confirm, dialog } = useConfirm();
  const quieto = ocupado || saliendo;
  const dias = -p.days_left;

  // La salida honesta cuando no hubo pago: la promesa se da por incumplida y deja de
  // pedir una decisión. No se marca cumplida ni se toca la factura.
  async function noCumplio() {
    const ok = await confirm({
      title: "Dar la promesa por incumplida",
      message: `${p.customer} quedó de pagar el ${fechaDM(p.promised_date)} y no pagó. La promesa sale de Hoy. La factura ${p.folio} sigue abierta y se sigue cobrando.`,
      confirmLabel: "No cumplió",
      borra: false,
    });
    if (!ok) return;
    await ejecutar(
      () => api.promesaNoCumplio(p.id),
      "Promesa dada por incumplida. La factura sigue abierta.",
      id,
    );
  }

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
      <Cabeza nombre={p.customer} clienteId={p.customer_id} monto={dinero(p.amount, p.currency)}>
        <span className="font-medium text-ink-2">Promesa vencida</span>
        <span className="tnum">Factura {p.folio}</span>
        <Marca color="warn">
          {dias === 1 ? "venció ayer" : `venció hace ${dias} días`}
        </Marca>
      </Cabeza>

      <div className="cita mt-4 max-w-2xl">
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
          className={`btn ${principal ? "btn-primary" : "btn-secondary"}`}
        >
          Registrar pago
        </button>
        <QuietButton type="button" onClick={recordar} disabled={quieto}>
          Recordar de nuevo
        </QuietButton>
        <QuietButton type="button" onClick={noCumplio} disabled={quieto}>
          No cumplió
        </QuietButton>
      </div>
      {dialog}

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
